# DevDocs

个人技术知识库，持续沉淀开发过程中的学习与实践。

## 目录

### Web 服务架构
从一个 HTTP 请求出发，理解 Nginx、Gunicorn、Django 等组件的职责与协作方式。

[进入 →](./web-server-architecture/README.md)

```
Nginx → Gunicorn → Django → Redis → Celery
  │        │         │                  │
  反向代理   进程管理    业务逻辑    后台任务
```

涵盖：Nginx / Gunicorn / Uvicorn / Django / Redis & Celery / Docker / 进程间通信 / Unix 设计哲学
