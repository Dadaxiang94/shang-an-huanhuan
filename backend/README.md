# 上岸换换 MVP API

本地启动：

```bash
python3 backend/server.py
```

接口：

- `GET /api/health`
- `GET /api/auth/status`
- `POST /api/auth/wechat`，提交微信小程序 `wx.login()` 返回的临时 `code`
- `GET /api/books`
- `POST /api/users`
- `POST /api/books`
- `POST /api/books/:id/review`，管理员审核资料
- `POST /api/media`，上传 Base64 图片/文件（8 MB 上限；生产环境应改为对象存储预签名上传）
- `GET /api/media`
- `POST /api/exchanges`
- `GET /api/orders`
- `POST /api/orders/:id/status`，按状态机推进订单

当前使用 SQLite，后续可替换为 PostgreSQL；状态机和接口路径保持不变。

## 微信登录与权限

电脑微信已登录不等于小程序服务端已配置。生产环境需要在微信公众平台取得小程序 `AppID`、`AppSecret`，写入环境变量 `WECHAT_APP_ID`、`WECHAT_APP_SECRET`。小程序端调用 `wx.login()`，只把返回的临时 `code` 发给 `/api/auth/wechat`；服务端通过微信 `code2Session` 换取 openid，并签发短期 Bearer token，绝不把 `session_key` 返回客户端。

生产环境设置 `REQUIRE_AUTH=true` 和足够随机的 `JWT_SECRET`。发布资料、上传媒体、发起交换时必须携带 `Authorization: Bearer <access_token>`，且资源归属人与 token 必须一致。本地演示可保持 `REQUIRE_AUTH=false`，但不可用于正式环境。

订单状态：`waiting_confirm` → `waiting_ship` → `shipping` → `waiting_pickup` → `completed`

## 上线前配置

1. 复制 `.env.example` 为 `.env`，替换数据库、对象存储、微信和 JWT 配置。
2. 生产环境使用 PostgreSQL，执行 `schema.sql`，不要把 SQLite 数据库文件提交到 Git。
3. 通过反向代理提供 HTTPS，并限制 CORS 到正式前端域名。
4. 配置小程序 AppID/AppSecret、`JWT_SECRET`、`REQUIRE_AUTH=true`；微信电脑端登录状态不能替代服务端配置。
5. 图片上传应改为对象存储预签名 URL，服务端只保存文件元数据，禁止直接保存用户原图到数据库。
6. 配置管理员角色后才能审核资料、处理申诉和推进异常订单。
7. 启动审核接口前设置 `ADMIN_API_KEY`，请求携带 `X-Admin-Key`；生产环境应替换为管理员 JWT/RBAC。
