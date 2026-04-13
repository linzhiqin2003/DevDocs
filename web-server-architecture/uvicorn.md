# Uvicorn：异步应用服务器

> 回到 [总览](./README.md) | 相关：[Gunicorn](./gunicorn.md) · [Django](./django.md) · [Redis 与 Celery](./redis-celery.md) · [Docker](./docker.md) · [进程间通信](./process-communication.md) · [Unix 哲学](./unix-philosophy.md)

## Uvicorn 是什么

Uvicorn 是一个 **ASGI 应用服务器**，和 [Gunicorn](./gunicorn.md) 是同一层的东西。区别在于：Gunicorn 跑同步代码（WSGI），Uvicorn 跑异步代码（ASGI）。

```
Nginx（反向代理）
    ↓
应用服务器（二选一，或组合使用）
    ├── Gunicorn → WSGI 协议（同步）
    └── Uvicorn → ASGI 协议（异步）
    ↓
Django / FastAPI（应用框架）
```

## 同步 vs 异步：到底差在哪

### Gunicorn（sync worker）处理请求

```
Worker 1 的时间线：

0ms   ──→ 收到请求 A
5ms   ──→ 查数据库（发出 SQL）
5-55ms    ┆  干等着... 什么都不做... 数据库还没返回...
55ms  ──→ 数据库返回了，继续处理
60ms  ──→ 调外部 API
60-260ms  ┆  又在干等... 200ms 全浪费了...
260ms ──→ API 返回了，构造响应
265ms ──→ 返回响应

请求 B：排队等着，Worker 1 忙完了才能处理你
```

一个请求耗时 265ms，但 CPU 真正在干活的时间可能只有 10ms，剩下 255ms 都在等 I/O。这个 worker 被白白占着。

### Uvicorn（异步）处理请求

```
Worker 1 的时间线：

0ms   ──→ 收到请求 A
5ms   ──→ 查数据库（await，让出控制权）
5ms   ──→ ✨ 趁等待的空档，接收请求 B
8ms   ──→ 请求 B 也查数据库（await，让出控制权）
8ms   ──→ ✨ 接收请求 C
10ms  ──→ 请求 C 开始处理...
55ms  ──→ 请求 A 的数据库返回了，继续处理 A
56ms  ──→ 请求 A 调外部 API（await，让出控制权）
58ms  ──→ 请求 B 的数据库也返回了，继续处理 B
...

单个 worker 同时在推进多个请求！
```

关键词是 **`await`**。每次遇到 I/O 等待（数据库、网络请求、文件读写），异步代码会说"我先不占着了，有结果了再叫我"，然后 worker 去处理其他请求。

### 用代码对比

```python
# 同步 view（跑在 Gunicorn sync worker 上）
def get_stock_price(request, symbol):
    # requests.get 会阻塞线程，等到 API 返回才继续
    resp = requests.get(f"https://api.example.com/stock/{symbol}")
    return JsonResponse(resp.json())

# 异步 view（跑在 Uvicorn 上）
async def get_stock_price(request, symbol):
    async with httpx.AsyncClient() as client:
        # await 不阻塞，等待期间 worker 去处理其他请求
        resp = await client.get(f"https://api.example.com/stock/{symbol}")
    return JsonResponse(resp.json())
```

两段代码功能一样，但在高并发场景下，异步版本一个 worker 能顶同步版本好几个 worker。

## WSGI 和 ASGI 是什么

它们是**协议规范**——定义了"应用服务器怎么和 Web 框架对话"的标准。

```
WSGI（Web Server Gateway Interface）—— 2003 年定义
    应用服务器调用：response = application(environ, start_response)
    同步，一问一答，等处理完才能返回

ASGI（Asynchronous Server Gateway Interface）—— 2018 年定义
    应用服务器调用：await application(scope, receive, send)
    异步，支持长连接、WebSocket、SSE
```

| | WSGI | ASGI |
|--|------|------|
| 年代 | 2003，Python Web 的老标准 | 2018，新标准 |
| 模型 | 同步：一个请求占一个线程 | 异步：一个线程处理多个请求 |
| 支持 | HTTP 请求-响应 | HTTP + WebSocket + SSE + 长连接 |
| 服务器 | Gunicorn、uWSGI | Uvicorn、Daphne、Hypercorn |
| 框架 | Django（传统）、Flask | FastAPI、Django（async views）、Starlette |

Django 从 3.0 开始支持 ASGI，项目里同时有 `wsgi.py` 和 `asgi.py` 两个入口文件。

## Uvicorn 单独跑 vs 配合 Gunicorn

### 单独跑

```bash
uvicorn config.asgi:application --host 0.0.0.0 --port 8000
```

这样启动只有**一个进程**。可以通过 `--workers` 开多进程：

```bash
uvicorn config.asgi:application --host 0.0.0.0 --port 8000 --workers 4
```

但 Uvicorn 的多进程管理比较粗糙：
- worker 挂了重启的逻辑简单
- 没有优雅重启（平滑部署）
- 没有信号处理（`SIGHUP` 重载配置）
- 没有动态增减 worker

### 配合 Gunicorn

```bash
gunicorn config.asgi:application \
    --workers 4 \
    --worker-class uvicorn.workers.UvicornWorker \
    --bind 0.0.0.0:8000
```

这**不是嵌套**，而是分工：

```
Gunicorn Master（进程管理专家）
│
│  职责：
│  - 启动 / 停止 worker 进程
│  - 监控 worker 健康，挂了自动重启
│  - 收到 SIGHUP 时优雅重载（不中断服务）
│  - 动态增减 worker（TTIN / TTOU 信号）
│
├── Worker 1 ── 内部跑 Uvicorn 事件循环 ── 异步处理请求
├── Worker 2 ── 内部跑 Uvicorn 事件循环 ── 异步处理请求
├── Worker 3 ── 内部跑 Uvicorn 事件循环 ── 异步处理请求
└── Worker 4 ── 内部跑 Uvicorn 事件循环 ── 异步处理请求
```

`--worker-class uvicorn.workers.UvicornWorker` 的意思是：Gunicorn 你别用你默认的 sync worker 了，每个 worker 进程启动后，用 Uvicorn 的方式来处理请求。

这就是 [Unix 设计哲学](./unix-philosophy.md) 的体现——每个工具做好一件事，组合起来比造一个大而全的工具更灵活。

### 对比

| | `uvicorn` 单独跑 | `gunicorn + uvicorn worker` |
|--|-----------------|---------------------------|
| 进程管理 | 基础 | 成熟（十几年打磨） |
| 优雅重启 | 不支持 | 支持（零停机部署） |
| worker 挂了 | 简单重启 | 自动重启 + 日志 + 监控 |
| 适合 | 开发环境、小项目 | 生产环境 |
| 配置复杂度 | 低 | 中 |

## Uvicorn vs Gunicorn 选型指南

```
你的项目是纯同步 Django（没有 async view）？
    └─→ Gunicorn + sync worker 就够了，不需要 Uvicorn

你用了 async view、WebSocket、SSE？
    └─→ Gunicorn + Uvicorn worker

你用的是 FastAPI？
    └─→ Gunicorn + Uvicorn worker（FastAPI 必须跑在 ASGI 上）

本地开发？
    └─→ uvicorn config.asgi:application --reload
        或者 manage.py runserver（Django 会自动检测 ASGI）
```

## 为什么没有一个"既有 Gunicorn 的进程管理又有 Uvicorn 的异步"的工具

有人在做——比如 [Granian](https://github.com/emmett-framework/granian)，Rust 写的，自带多进程管理 + 异步事件循环。但还太年轻，生态不成熟，生产环境没几个人敢用。

现实是 `gunicorn --worker-class uvicorn.workers.UvicornWorker` 一行命令就解决了。每个组件可以独立升级：Gunicorn 更新了进程管理策略？直接生效。Uvicorn 优化了事件循环？更新 Uvicorn 包就行。不需要等一个大一统工具同时把两边都更新。

这正是 [Unix 哲学](./unix-philosophy.md) 的智慧——组合小工具，胜过一个大工具。
