#!/usr/bin/env python3
"""上岸换换 MVP API：仅使用 Python 标准库，便于本地演示。"""
import base64, hashlib, hmac, json, os, sqlite3, uuid, urllib.parse, urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "shang_an_huanhuan.sqlite3")
UPLOADS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads")
MAX_UPLOAD = 20 * 1024 * 1024  # 本地演示放宽到 20MB，容纳带图 PPT；生产请收紧并按类型限制
ALLOWED_ORIGIN = os.environ.get("ALLOWED_ORIGIN", "http://127.0.0.1:8000")
JWT_SECRET = os.environ.get("JWT_SECRET", "")
REQUIRE_AUTH = os.environ.get("REQUIRE_AUTH", "false").lower() == "true"

def now(): return datetime.now(timezone.utc).isoformat()
def db():
    conn = sqlite3.connect(DB); conn.row_factory = sqlite3.Row
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS users (id TEXT PRIMARY KEY, nickname TEXT NOT NULL, wx_openid TEXT UNIQUE, created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS books (id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, title TEXT NOT NULL, exam TEXT NOT NULL, subject TEXT NOT NULL, want TEXT NOT NULL, quality TEXT NOT NULL, status TEXT NOT NULL, cover_media_id TEXT, file_media_id TEXT, created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS exchanges (id TEXT PRIMARY KEY, book_id TEXT NOT NULL, requester_id TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS orders (id TEXT PRIMARY KEY, exchange_id TEXT NOT NULL, status TEXT NOT NULL, pickup_code TEXT, created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS media (id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, filename TEXT NOT NULL, path TEXT NOT NULL, mime TEXT NOT NULL, size INTEGER NOT NULL, created_at TEXT NOT NULL);
    """)
    columns={r[1] for r in conn.execute("PRAGMA table_info(users)").fetchall()}
    if "wx_openid" not in columns: conn.execute("ALTER TABLE users ADD COLUMN wx_openid TEXT")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS users_wx_openid_uq ON users(wx_openid) WHERE wx_openid IS NOT NULL")
    bcols={r[1] for r in conn.execute("PRAGMA table_info(books)").fetchall()}
    if "cover_media_id" not in bcols: conn.execute("ALTER TABLE books ADD COLUMN cover_media_id TEXT")
    if "file_media_id" not in bcols: conn.execute("ALTER TABLE books ADD COLUMN file_media_id TEXT")
    return conn

def b64url(value): return base64.urlsafe_b64encode(value).rstrip(b"=").decode()
def issue_token(uid):
    if not JWT_SECRET: raise RuntimeError("jwt_config_missing")
    header=b64url(b'{"alg":"HS256","typ":"JWT"}')
    payload=b64url(json.dumps({"sub":uid,"exp":int(datetime.now(timezone.utc).timestamp())+86400},separators=(",",":")).encode())
    signing=f"{header}.{payload}".encode(); sig=hmac.new(JWT_SECRET.encode(),signing,hashlib.sha256).digest()
    return f"{header}.{payload}.{b64url(sig)}"

def token_user(handler):
    value=handler.headers.get("Authorization", "")
    if not value.startswith("Bearer ") or not JWT_SECRET: return None
    try:
        header,payload,signature=value[7:].split("."); signing=f"{header}.{payload}".encode()
        expected=b64url(hmac.new(JWT_SECRET.encode(),signing,hashlib.sha256).digest())
        if not hmac.compare_digest(signature, expected): return None
        data=json.loads(base64.urlsafe_b64decode(payload+"="*((4-len(payload)%4)%4)))
        if int(data.get("exp",0)) < int(datetime.now(timezone.utc).timestamp()): return None
        return data.get("sub")
    except Exception: return None

def wx_login(code):
    appid=os.environ.get("WECHAT_APP_ID"); secret=os.environ.get("WECHAT_APP_SECRET")
    if not appid or not secret: raise RuntimeError("wechat_config_missing")
    query=urllib.parse.urlencode({"appid":appid,"secret":secret,"js_code":code,"grant_type":"authorization_code"})
    with urllib.request.urlopen("https://api.weixin.qq.com/sns/jscode2session?"+query, timeout=8) as r: result=json.loads(r.read())
    if result.get("errcode"): raise RuntimeError("wechat_code_invalid")
    return result

class API(BaseHTTPRequestHandler):
    def send_headers(self, status=200):
        self.send_response(status); self.send_header("Content-Type", "application/json; charset=utf-8"); self.send_header("Access-Control-Allow-Origin", ALLOWED_ORIGIN); self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Admin-Key"); self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS"); self.send_header("X-Content-Type-Options", "nosniff"); self.send_header("Cache-Control", "no-store"); self.end_headers()
    def body(self):
        n=int(self.headers.get("Content-Length",0)); return json.loads(self.rfile.read(n) or b"{}")
    def valid_id(self, value):
        try: uuid.UUID(value); return True
        except (ValueError, TypeError, AttributeError): return False
    def require_admin(self): return bool(os.environ.get("ADMIN_API_KEY")) and hmac.compare_digest(self.headers.get("X-Admin-Key", ""), os.environ["ADMIN_API_KEY"])
    def require_user(self, claimed=None):
        uid=token_user(self)
        if REQUIRE_AUTH and not uid: return None
        if REQUIRE_AUTH and claimed and uid != claimed: return None
        return uid or claimed
    def out(self, data, status=200): self.send_headers(status); self.wfile.write(json.dumps(data, ensure_ascii=False).encode())
    def do_OPTIONS(self): self.send_headers(204)
    def do_GET(self):
        path=urlparse(self.path).path; conn=db()
        if path == "/api/health": return self.out({"ok":True,"service":"shang-an-huanhuan"})
        if path == "/api/auth/status": return self.out({"configured":bool(os.environ.get("WECHAT_APP_ID") and os.environ.get("WECHAT_APP_SECRET") and JWT_SECRET),"wechat_configured":bool(os.environ.get("WECHAT_APP_ID") and os.environ.get("WECHAT_APP_SECRET")),"jwt_configured":bool(JWT_SECRET),"require_auth":REQUIRE_AUTH})
        if path == "/api/books":
            owner=urllib.parse.parse_qs(urlparse(self.path).query).get("owner",[None])[0]
            cols="b.*, c.filename AS cover_name, c.mime AS cover_mime, f.filename AS file_name, f.mime AS file_mime"
            if owner and self.valid_id(owner):
                rows=conn.execute(f"SELECT {cols} FROM books b LEFT JOIN media c ON b.cover_media_id=c.id LEFT JOIN media f ON b.file_media_id=f.id WHERE b.owner_id=? ORDER BY b.created_at DESC",(owner,)).fetchall()
            else:
                rows=conn.execute(f"SELECT {cols} FROM books b LEFT JOIN media c ON b.cover_media_id=c.id LEFT JOIN media f ON b.file_media_id=f.id WHERE b.status='active' ORDER BY b.created_at DESC").fetchall()
            return self.out([dict(x) for x in rows])
        if path == "/api/orders":
            owner=urllib.parse.parse_qs(urlparse(self.path).query).get("mine",[None])[0]
            cols="o.id,o.status,o.pickup_code,o.created_at,b.title,b.exam,b.subject,b.id AS book_id,b.owner_id AS book_owner_id,e.requester_id,e.id AS exchange_id,b.file_media_id,b.cover_media_id"
            if owner and self.valid_id(owner):
                rows=conn.execute(f"SELECT {cols} FROM orders o JOIN exchanges e ON o.exchange_id=e.id JOIN books b ON e.book_id=b.id WHERE e.requester_id=? OR b.owner_id=? ORDER BY o.created_at DESC",(owner,owner)).fetchall()
            else:
                rows=conn.execute(f"SELECT {cols} FROM orders o JOIN exchanges e ON o.exchange_id=e.id JOIN books b ON e.book_id=b.id ORDER BY o.created_at DESC").fetchall()
            return self.out([dict(x) for x in rows])
        if path == "/api/stats":
            uid=urllib.parse.parse_qs(urlparse(self.path).query).get("uid",[None])[0]
            if not uid or not self.valid_id(uid): return self.out({"error":"invalid_uid"},400)
            published=conn.execute("SELECT count(*) FROM books WHERE owner_id=?",(uid,)).fetchone()[0]
            my_orders=conn.execute("SELECT count(*) FROM orders o JOIN exchanges e ON o.exchange_id=e.id JOIN books b ON e.book_id=b.id WHERE e.requester_id=? OR b.owner_id=?",(uid,uid)).fetchone()[0]
            incoming=conn.execute("SELECT count(*) FROM exchanges e JOIN books b ON e.book_id=b.id WHERE b.owner_id=? AND e.requester_id!=?",(uid,uid)).fetchone()[0]
            return self.out({"published":published,"my_orders":my_orders,"incoming_intents":incoming})
        if path == "/api/media":
            rows=conn.execute("SELECT id,owner_id,filename,mime,size,created_at FROM media ORDER BY created_at DESC").fetchall(); return self.out([dict(x) for x in rows])
        if path.count("/")==3 and path.startswith("/api/media/"):
            mid=path.split("/")[3]; row=conn.execute("SELECT * FROM media WHERE id=?",(mid,)).fetchone()
            if not row: return self.out({"error":"media_not_found"},404)
            # 权限：封面图公开；资料文件仅订单双方确认交换（confirmed/completed）后可下载
            q=urllib.parse.parse_qs(urlparse(self.path).query)
            uid=(q.get("uid") or [None])[0]; oid=(q.get("order_id") or [None])[0]
            b=conn.execute("SELECT id,file_media_id FROM books WHERE file_media_id=? OR cover_media_id=?",(mid,mid)).fetchone()
            if b and b["file_media_id"]==mid:
                if not uid or not oid or not self.valid_id(uid) or not self.valid_id(oid):
                    return self.out({"error":"download_forbidden","hint":"确认交换后订单双方可下载"},403)
                o=conn.execute("SELECT o.status,e.book_id,e.requester_id,b.owner_id FROM orders o JOIN exchanges e ON o.exchange_id=e.id JOIN books b ON e.book_id=b.id WHERE o.id=?",(oid,)).fetchone()
                if not o or o["book_id"]!=b["id"] or o["status"] not in ("confirmed","completed") or uid not in (o["requester_id"],o["owner_id"]):
                    return self.out({"error":"download_forbidden","hint":"确认交换后订单双方可下载"},403)
            try:
                with open(row["path"],"rb") as f: blob=f.read()
            except Exception: return self.out({"error":"file_missing"},404)
            # 图片内联展示；文档类（PPT/Excel/Word/TXT 等）强制附件下载，文件名支持中文
            disposition="inline"
            if not str(row["mime"]).startswith("image/"):
                safe="".join(ch for ch in row["filename"] if ch.isascii() and (ch.isalnum() or ch in "._-")).replace(".","_",1) or "download.bin"
                disposition=f'attachment; filename="{safe}"; filename*=UTF-8\'\'{urllib.parse.quote(row["filename"])}'
            self.send_response(200); self.send_header("Content-Type",row["mime"]); self.send_header("Content-Length",str(len(blob))); self.send_header("Content-Disposition",disposition); self.send_header("Cache-Control","no-store"); self.end_headers(); self.wfile.write(blob); return
        return self.out({"error":"not_found"},404)
    def do_POST(self):
        path=urlparse(self.path).path; data=self.body(); conn=db()
        if path == "/api/auth/wechat":
            code=str(data.get("code", "")).strip()
            if not code:return self.out({"error":"code_required"},400)
            try: result=wx_login(code)
            except RuntimeError as e:return self.out({"error":str(e)},503 if str(e)=="wechat_config_missing" else 401)
            except Exception:return self.out({"error":"wechat_service_unavailable"},502)
            openid=result.get("openid"); uid=str(uuid.uuid4()); row=conn.execute("SELECT id,nickname FROM users WHERE wx_openid=?",(openid,)).fetchone()
            if row: uid=row["id"]; nickname=row["nickname"]
            else:
                nickname=str(data.get("nickname","微信用户"))[:50]; conn.execute("INSERT INTO users VALUES (?,?,?,?)",(uid,nickname,openid,now())); conn.commit()
            try: token=issue_token(uid)
            except RuntimeError as e: return self.out({"error":str(e)},503)
            return self.out({"user_id":uid,"nickname":nickname,"access_token":token,"token_type":"Bearer"})
        if path == "/api/users":
            nickname=str(data.get("nickname","新书友")).strip()[:50]
            if not nickname:return self.out({"error":"invalid_nickname"},400)
            uid=str(uuid.uuid4()); conn.execute("INSERT INTO users(id,nickname,created_at) VALUES (?,?,?)",(uid,nickname,now())); conn.commit(); return self.out({"id":uid,"nickname":nickname},201)
        if path == "/api/books":
            required=["owner_id","title","exam","subject","want"]
            if any(not data.get(k) for k in required) or not self.valid_id(data.get("owner_id")): return self.out({"error":"invalid_book_payload","required":required},400)
            if not self.require_user(data.get("owner_id")): return self.out({"error":"auth_required"},401)
            if any(len(str(data[k]))>200 for k in required if k != "owner_id"): return self.out({"error":"field_too_long"},400)
            cover=str(data.get("cover_media_id") or "").strip(); file_mid=str(data.get("file_media_id") or "").strip()
            if cover and not self.valid_id(cover): return self.out({"error":"invalid_cover_media_id"},400)
            if file_mid and not self.valid_id(file_mid): return self.out({"error":"invalid_file_media_id"},400)
            status="active" if not os.environ.get("ADMIN_API_KEY") else "pending"
            bid=str(uuid.uuid4()); conn.execute("INSERT INTO books(id,owner_id,title,exam,subject,want,quality,status,cover_media_id,file_media_id,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",(bid,data["owner_id"],data["title"],data["exam"],data["subject"],data["want"],data.get("quality","轻微笔记"),status,cover or None,file_mid or None,now())); conn.commit(); return self.out({"id":bid,"status":status},201)
        if path == "/api/media":
            owner=str(data.get("owner_id","")); raw=str(data.get("content_base64","")); filename=os.path.basename(str(data.get("filename","upload.bin")))[:120]; mime=str(data.get("mime","application/octet-stream"))[:100]
            if not self.valid_id(owner) or not raw or not filename:return self.out({"error":"invalid_media_payload"},400)
            if not self.require_user(owner): return self.out({"error":"auth_required"},401)
            try: payload=base64.b64decode(raw, validate=True)
            except Exception:return self.out({"error":"invalid_base64"},400)
            if len(payload)>MAX_UPLOAD:return self.out({"error":"file_too_large","max_bytes":MAX_UPLOAD},413)
            os.makedirs(UPLOADS,exist_ok=True); mid=str(uuid.uuid4()); path=os.path.join(UPLOADS,mid+"-"+filename)
            with open(path,"wb") as f:f.write(payload)
            conn.execute("INSERT INTO media VALUES (?,?,?,?,?,?,?)",(mid,owner,filename,path,mime,len(payload),now())); conn.commit(); return self.out({"id":mid,"filename":filename,"size":len(payload)},201)
        if path.startswith("/api/books/") and path.endswith("/review"):
            if not self.require_admin(): return self.out({"error":"admin_required"},403)
            bid=path.split("/")[3]; target=data.get("status")
            if target not in ("active","rejected"): return self.out({"error":"invalid_review_status"},400)
            cur=conn.execute("UPDATE books SET status=? WHERE id=?",(target,bid)); conn.commit()
            if cur.rowcount==0:return self.out({"error":"book_not_found"},404)
            return self.out({"id":bid,"status":target})
        if path == "/api/exchanges":
            if not data.get("book_id") or not data.get("requester_id"): return self.out({"error":"missing_field"},400)
            if not self.require_user(data.get("requester_id")): return self.out({"error":"auth_required"},401)
            eid=str(uuid.uuid4()); conn.execute("INSERT INTO exchanges VALUES (?,?,?,?,?)",(eid,data["book_id"],data["requester_id"],"pending",now())); oid=str(uuid.uuid4()); conn.execute("INSERT INTO orders VALUES (?,?,?,?,?)",(oid,eid,"waiting_confirm",str(uuid.uuid4())[:4].upper(),now())); conn.commit(); return self.out({"exchange_id":eid,"order_id":oid,"status":"waiting_confirm"},201)
        if path.startswith("/api/orders/") and path.endswith("/status"):
            oid=path.split("/")[3]; target=data.get("status"); allowed={"waiting_confirm":"confirmed","confirmed":"completed","waiting_ship":"completed","shipping":"completed","waiting_pickup":"completed"}; row=conn.execute("SELECT status FROM orders WHERE id=?",(oid,)).fetchone()
            if not row:return self.out({"error":"order_not_found"},404)
            if allowed.get(row["status"])!=target:return self.out({"error":"invalid_transition","current":row["status"],"next":allowed.get(row["status"])},409)
            conn.execute("UPDATE orders SET status=? WHERE id=?",(target,oid)); conn.commit(); return self.out({"id":oid,"status":target})
        return self.out({"error":"not_found"},404)

if __name__ == "__main__":
    db().close(); print("API running at http://127.0.0.1:8080")
    ThreadingHTTPServer(("127.0.0.1",8080),API).serve_forever()
