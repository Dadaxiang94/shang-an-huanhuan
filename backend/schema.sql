-- 生产环境迁移基线（PostgreSQL 版）。本地 MVP 使用 SQLite 自动建表。
CREATE TABLE users (id UUID PRIMARY KEY, nickname VARCHAR(50) NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE TABLE books (id UUID PRIMARY KEY, owner_id UUID NOT NULL REFERENCES users(id), title VARCHAR(200) NOT NULL, exam VARCHAR(30) NOT NULL, subject VARCHAR(50) NOT NULL, want VARCHAR(200) NOT NULL, quality VARCHAR(30) NOT NULL, status VARCHAR(20) NOT NULL DEFAULT 'pending', created_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE TABLE exchanges (id UUID PRIMARY KEY, book_id UUID NOT NULL REFERENCES books(id), requester_id UUID NOT NULL REFERENCES users(id), status VARCHAR(30) NOT NULL DEFAULT 'pending', created_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE TABLE orders (id UUID PRIMARY KEY, exchange_id UUID NOT NULL REFERENCES exchanges(id), status VARCHAR(30) NOT NULL DEFAULT 'waiting_confirm', pickup_code VARCHAR(8), created_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE TABLE media (id UUID PRIMARY KEY, owner_id UUID NOT NULL REFERENCES users(id), filename VARCHAR(120) NOT NULL, path TEXT NOT NULL, mime VARCHAR(100) NOT NULL, size INTEGER NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE INDEX books_match_idx ON books(status, exam, subject);
CREATE INDEX orders_status_idx ON orders(status);
