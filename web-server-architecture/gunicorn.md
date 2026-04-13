# Gunicorn：进程管理器

> 回到 [总览](./README.md) | 相关：[Nginx](./nginx.md) · [Uvicorn](./uvicorn.md) · [Django](./django.md) · [Redis 与 Celery](./redis-celery.md) · [Docker](./docker.md) · [进程间通信](./process-communication.md) · [WSGI & ASGI](./wsgi-asgi.md) · [Unix 哲学](./unix-philosophy.md)

## Gunicorn 是什么

Gunicorn（Green Unicorn）是一个 **Python WSGI 应用服务器**。说白了，它的工作就是：**启动多个进程，每个进程跑一份 [Django](./django.md)，然后把请求分给它们处理**。

你可以把它理解成一个"包工头"——它自己不干活（不处理业务逻辑），但它管理一群干活的人（worker），确保活有人干、干活的人别累死。

## 为什么不直接用 `manage.py runserver`

Django 自带的 `runserver` 是开发用的，有几个致命问题：

| | `runserver` | Gunicorn |
|--|------------|----------|
| 进程数 | 1 个（单进程） | 可配置（通常 4-17 个） |
| 并发能力 | 同时只能处理 1 个请求 | 多个请求并行处理 |
| 稳定性 | 崩了就崩了 | worker 挂了自动重启 |
| 静态文件 | 自己伺服（慢） | 不管，交给 [Nginx](./nginx.md) |
| 代码热重载 | 有（方便开发） | 无（生产不需要） |
| 安全性 | Django 官方明确说不要用于生产 | 专为生产设计 |

一句话：`runserver` 是给开发者在本地调试用的玩具，Gunicorn 是上战场的正规军。

## Master-Worker 模型

Gunicorn 启动后的进程结构：

```
Gunicorn Master（PID 1000）
│
│  不处理请求，只管理 worker
│  - 启动 / 停止 worker
│  - 监控 worker 健康状态
│  - 收到 SIGHUP 信号时优雅重载
│
├── Worker 1（PID 1001）→ 完整的 Django 应用实例
├── Worker 2（PID 1002）→ 完整的 Django 应用实例
├── Worker 3（PID 1003）→ 完整的 Django 应用实例
└── Worker 4（PID 1004）→ 完整的 Django 应用实例
```

每个 worker 都是一个独立的操作系统进程，有自己的内存空间，互不干扰。Worker 1 崩了不会影响 Worker 2。Master 检测到 Worker 1 死亡后，会自动 fork 一个新的出来替补。

### 一个请求的分配过程

1. [Nginx](./nginx.md) 把请求转发到 Gunicorn 监听的端口（比如 `127.0.0.1:8000`）
2. Master 进程接收请求，放入队列
3. 空闲的 Worker 从队列中取出请求
4. Worker 内部的 Django 处理请求，返回响应
5. Worker 回到空闲状态，等待下一个请求

## Worker 配置

### 启动命令

```bash
gunicorn config.wsgi:application \
    --bind 127.0.0.1:8000 \
    --workers 4 \
    --timeout 120 \
    --access-logfile /var/log/gunicorn/access.log \
    --error-logfile /var/log/gunicorn/error.log
```

### Worker 数量怎么定

官方推荐公式：

```
workers = 2 × CPU 核数 + 1
```

| 服务器 CPU | 推荐 worker 数 | 说明 |
|-----------|---------------|------|
| 1 核（小型 VPS） | 2-3 | 再多 CPU 也切换不过来 |
| 2 核 | 5 | 最常见的中小项目配置 |
| 4 核 | 9 | 能扛一定并发 |
| 8 核 | 17 | 中大型应用 |

为什么是 `2n + 1` 而不是 `n`？因为 worker 处理请求时有很多时间在等 I/O（数据库查询、外部 API 调用），CPU 实际上是空闲的。多开几个 worker 可以让 CPU 在等 I/O 的间隙处理其他请求。

### Worker 类型

这是一个进阶但很重要的概念：

```bash
# 同步 worker（默认）
gunicorn config.wsgi --workers 4 --worker-class sync

# 异步 worker（基于 gevent）
gunicorn config.wsgi --workers 4 --worker-class gevent --worker-connections 1000

# ASGI worker（使用 uvicorn）
gunicorn config.asgi:application --workers 4 --worker-class uvicorn.workers.UvicornWorker
```

| Worker 类型 | 原理 | 适用场景 |
|------------|------|---------|
| `sync`（默认） | 一个 worker 同时只处理 1 个请求 | 普通的 CRUD 应用 |
| `gevent` | 协程，一个 worker 可以同时处理上千个请求 | 大量 I/O 等待（调外部 API） |
| `uvicorn` | ASGI 异步，支持 WebSocket | Django async views、实时应用 |

用 `sync` worker 时，4 个 worker 最多同时处理 4 个请求。用 `gevent` 时，4 个 worker 可以同时处理数千个请求——因为大部分时间都在等 I/O，协程在等待时会让出 CPU 给其他请求。

### Timeout 配置

```bash
gunicorn config.wsgi --timeout 30
```

如果一个 worker 处理请求超过 30 秒没有响应，Master 会直接 **kill 掉这个 worker**，然后启动一个新的。这是 Gunicorn 的自保机制——防止一个慢请求永远占着 worker。

注意这个超时和 [Nginx 的 `proxy_read_timeout`](./nginx.md#4-超时控制--504-的来源) 是两层不同的超时：

```
用户 → Nginx（60s 超时）→ Gunicorn（30s 超时）→ Django
```

如果 Gunicorn 超时设 30s、Nginx 设 60s，那 30s 时 Gunicorn 先杀 worker，Nginx 收到错误返回 502 Bad Gateway。如果反过来 Gunicorn 设 120s、Nginx 设 60s，那 60s 时 Nginx 先断开返回 504，但 worker 可能还在继续跑到 120s 才被杀。

## Worker 耗尽：真实场景

假设你有 4 个 sync worker，用户行为如下：

```
时间线：
0s   → 用户 A 上传 PDF，Worker 1 开始索引（预计 90s）
2s   → 用户 B 上传 PDF，Worker 2 开始索引
5s   → 用户 C 上传 PDF，Worker 3 开始索引
8s   → 用户 D 上传 PDF，Worker 4 开始索引
10s  → 用户 E 只是想打开首页... 

     ⚠️ 4 个 worker 全在做 PDF 索引
     ⚠️ 用户 E 的请求进入等待队列
     ⚠️ 如果等待超过 Nginx 的超时时间 → 504
     ⚠️ 不只是用户 E，所有新请求都被堵住了
```

这就是为什么耗时操作不应该在请求里同步执行。解决方案：
- 用 [Celery](./redis-celery.md) 把 PDF 索引丢到后台 worker 执行
- Django 的 view 只负责创建任务，立刻返回，不占 Gunicorn 的 worker

## Gunicorn 配置文件

实际项目中通常不在命令行写一堆参数，而是用配置文件：

```python
# gunicorn.conf.py

bind = "127.0.0.1:8000"
workers = 4
worker_class = "sync"
timeout = 30

# 日志
accesslog = "/var/log/gunicorn/access.log"
errorlog = "/var/log/gunicorn/error.log"
loglevel = "info"

# 优雅重启：收到 SIGHUP 后，逐个重启 worker，不中断服务
graceful_timeout = 30

# 预加载应用：所有 worker 共享同一份代码，节省内存
preload_app = True
```

启动方式：

```bash
gunicorn config.wsgi:application -c gunicorn.conf.py
```

## 常用运维操作

```bash
# 优雅重启（部署新代码后）
kill -HUP <master_pid>
# Master 会逐个重启 worker，期间服务不中断

# 增加 worker 数量
kill -TTIN <master_pid>

# 减少 worker 数量
kill -TTOU <master_pid>

# 优雅停止
kill -TERM <master_pid>
# Master 等待所有 worker 处理完当前请求后退出
```

## Gunicorn vs 其他选择

| | Gunicorn | uWSGI | Daphne | Uvicorn |
|--|---------|-------|--------|---------|
| 协议 | WSGI | WSGI/ASGI | ASGI | ASGI |
| 复杂度 | 简单 | 复杂（配置项极多） | 中等 | 简单 |
| 适合 | Django 同步应用 | 性能极致优化 | Django Channels | FastAPI / Django async |
| 生态 | Python 主流 | 逐渐式微 | Django 官方推荐 | 新项目首选 |

如果你的 [Django](./django.md) 项目是传统同步应用，Gunicorn 是最省心的选择。如果用了 async views 或 WebSocket，考虑 [Uvicorn](./uvicorn.md)（可以作为 Gunicorn 的 worker 类型使用，两者不冲突）。详见 [Uvicorn：异步应用服务器](./uvicorn.md#配合-gunicorn)。
