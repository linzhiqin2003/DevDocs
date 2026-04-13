# Nginx：守门人与调度员

> 回到 [总览](./README.md) | 相关：[Gunicorn](./gunicorn.md) · [Uvicorn](./uvicorn.md) · [Django](./django.md) · [Redis 与 Celery](./redis-celery.md) · [Docker](./docker.md) · [进程间通信](./process-communication.md) · [Unix 哲学](./unix-philosophy.md)

## Nginx 是什么

Nginx（读作 "engine-x"）是一个**反向代理服务器**，也是一个**高性能 Web 服务器**。

在我们的架构里，Nginx 是用户请求到达的**第一站**。它不执行任何 Python 代码，也不懂你的业务逻辑。它做的事情很纯粹：**接收请求，决定交给谁处理，然后把结果送回去**。

## 正向代理 vs 反向代理

这俩名字容易搞混，区别很简单：

- **正向代理**：你用 VPN 翻墙，VPN 服务器帮你请求 Google → 代理的是**客户端**
- **反向代理**：用户访问 `your-app.com`，Nginx 帮你把请求转给后端 → 代理的是**服务端**

用户根本不知道 Nginx 背后有个 [Gunicorn](./gunicorn.md) 在跑，他们以为自己在跟 Nginx 直接对话。关于 Nginx 和 Gunicorn 之间具体怎么通信（TCP vs Unix Socket），详见 [进程间通信](./process-communication.md#nginx-与-gunicorn不同进程)。

## Nginx 具体干了什么

### 1. 静态文件直接返回

CSS、JS、图片这些不需要 Python 处理的文件，Nginx 直接从磁盘读取返回，速度极快。如果让 [Django](./django.md) 来处理静态文件，每个请求都要经过 Python 解释器，白白浪费资源。

```nginx
server {
    # 静态文件 — Nginx 自己处理
    location /static/ {
        alias /var/www/your-app/static/;
        expires 30d;  # 缓存 30 天
    }

    # 媒体文件（用户上传的）
    location /media/ {
        alias /var/www/your-app/media/;
    }

    # 其他所有请求 — 转发给 Gunicorn
    location / {
        proxy_pass http://127.0.0.1:8000;
    }
}
```

一个典型的页面加载可能有 1 个 HTML 请求 + 20 个静态资源请求。Nginx 自己搞定那 20 个，只把 1 个动态请求交给 [Gunicorn](./gunicorn.md)。这就是为什么需要 Nginx 而不是让 Gunicorn 直接面对用户。

### 2. SSL/TLS 终止

HTTPS 加解密是 CPU 密集型操作。Nginx 专门优化过这件事，用 C 语言实现，性能远超 Python。

```nginx
server {
    listen 443 ssl;
    server_name your-app.com;

    ssl_certificate     /etc/letsencrypt/live/your-app.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/your-app.com/privkey.pem;

    location / {
        # 解密后，用普通 HTTP 转发给 Gunicorn（内网通信，不需要加密）
        proxy_pass http://127.0.0.1:8000;
    }
}
```

用户 ↔ Nginx 之间是 HTTPS（加密），Nginx ↔ Gunicorn 之间是 HTTP（明文）。因为 Nginx 和 Gunicorn 在同一台机器上，走的是 `127.0.0.1`，不经过外网，明文没问题。

### 3. 负载均衡

当一台 [Gunicorn](./gunicorn.md) 扛不住时，可以部署多台，Nginx 自动分发请求：

```nginx
upstream backend {
    server 10.0.0.1:8000;  # 服务器 1
    server 10.0.0.2:8000;  # 服务器 2
    server 10.0.0.3:8000;  # 服务器 3
}

server {
    location / {
        proxy_pass http://backend;  # Nginx 自动轮询分配
    }
}
```

### 4. 超时控制 — 504 的来源

这是最实际的一个点。Nginx 转发请求给 [Gunicorn](./gunicorn.md) 后会开始计时：

```nginx
location / {
    proxy_pass http://127.0.0.1:8000;
    proxy_connect_timeout 5s;    # 连接 Gunicorn 超时
    proxy_read_timeout    60s;   # 等待 Gunicorn 响应超时（关键！）
    proxy_send_timeout    60s;   # 发送请求到 Gunicorn 超时
}
```

**`proxy_read_timeout 60s`** 就是 504 的根源。场景：

1. 用户上传 PDF，请求到达 [Django](./django.md)
2. Django 开始做文档索引，预计耗时 90 秒
3. 60 秒过去了，Nginx 没收到 Django 的响应
4. Nginx 主动断开连接，返回 **504 Gateway Timeout** 给用户
5. 但 Django 那边可能还在继续跑（也可能被 Gunicorn 杀掉）

解决方案有三种思路：
- **调大超时**：`proxy_read_timeout 300s` — 治标不治本
- **异步化**：用 [Celery](./django.md#celery-什么时候该引入) 把耗时任务丢后台，请求立刻返回
- **流式响应**：用 SSE 持续发送数据，Nginx 认为连接是活跃的就不会超时

## 一份实际的 Nginx 配置

把上面的东西组合起来，一个 Django 项目的 Nginx 配置大概长这样：

```nginx
server {
    listen 80;
    server_name your-app.com;
    return 301 https://$host$request_uri;  # HTTP 强制跳转 HTTPS
}

server {
    listen 443 ssl;
    server_name your-app.com;

    ssl_certificate     /etc/letsencrypt/live/your-app.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/your-app.com/privkey.pem;

    # 静态文件
    location /static/ {
        alias /var/www/your-app/static/;
        expires 30d;
    }

    # 动态请求转发
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 60s;
    }
}
```

`proxy_set_header` 那几行是在告诉 [Django](./django.md)："这个请求真正的来源 IP 是什么，用的是 HTTPS 还是 HTTP"。因为 Django 看到的直接来源是 Nginx（`127.0.0.1`），不加这些 header 它就不知道用户的真实信息。

## Nginx 的性能为什么这么强

Nginx 用的是 **事件驱动 + 异步非阻塞** 模型。传统服务器（如 Apache）是一个请求一个线程，10000 个并发就要 10000 个线程，内存直接爆。Nginx 用少量 worker 进程 + epoll 事件循环，轻松处理数万并发连接，内存占用极低。

这也是为什么 Nginx 适合当"守门人"——它能同时接待大量客人，而不会自己先倒下。

## 什么时候不需要 Nginx

- **本地开发**：`manage.py runserver` 或 Vite dev server 直接访问就行
- **云平台托管**：Vercel、Railway、Fly.io 等平台自带反向代理和 SSL
- **纯内部服务**：如果 [Gunicorn](./gunicorn.md) 只被内部微服务调用，不面向公网

但只要你的服务要面向公网用户，Nginx（或类似的 Caddy、Traefik）几乎是标配。
