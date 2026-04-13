# 进程间通信：谁和谁在同一个进程里

> 回到 [总览](./README.md) | 相关：[Nginx](./nginx.md) · [Gunicorn](./gunicorn.md) · [Uvicorn](./uvicorn.md) · [Django](./django.md) · [Redis 与 Celery](./redis-celery.md) · [Docker](./docker.md) · [Unix 哲学](./unix-philosophy.md)

## 先看全局

```
┌──────────┐     ┌──────────────────────────┐     ┌──────────┐     ┌──────────────┐
│  Nginx   │────→│  Gunicorn Worker(Django)  │────→│  Redis   │────→│Celery Worker │
│  进程 A   │     │  进程 B                   │     │  进程 C   │     │  进程 D       │
└──────────┘     └──────────────────────────┘     └──────────┘     └──────────────┘
     │                    │                            │                   │
     独立进程              同一进程                      独立进程             独立进程
```

关键问题：**这些组件之间怎么通信？**

答案取决于它们是否在同一个进程里。同一个进程内可以直接调用函数，不同进程之间必须通过某种通信机制。

## Gunicorn 与 Django：同一进程

这是最容易搞混的一对。很多人以为 Gunicorn 和 Django 是两个独立的东西，其实它们**在同一个进程里运行**。

### 启动过程

```bash
gunicorn config.wsgi:application --workers 4
```

这行命令做了什么：

1. Gunicorn master 进程启动
2. Master fork 出 4 个 worker 子进程
3. **每个 worker 进程内部**执行 `from config.wsgi import application`
4. 这个 `import` 会加载整个 Django 框架、你的所有 app、model、view...
5. Django 的 WSGI application 对象现在**存在于 worker 进程的内存里**

```python
# config/wsgi.py — 这个文件就是 Gunicorn 和 Django 之间的"接口"
import os
from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
application = get_wsgi_application()  # 返回一个可调用对象
```

### 通信方式：函数调用

```
Gunicorn Worker 进程内部：

┌─────────────────────────────────────────────┐
│                                             │
│  Gunicorn 的请求处理代码：                    │
│    environ = parse_http_request(raw_data)    │
│    response = application(environ, ...)  ◄── │── 直接调用 Django 的 WSGI 接口
│    send_response(response)                   │    就是一个普通的 Python 函数调用
│                                             │    不经过网络，不经过任何中间件
│  Django application 对象：                    │
│    middleware 链 → URL 路由 → view → 响应     │
│                                             │
└─────────────────────────────────────────────┘
```

没有 TCP，没有 Socket，没有 HTTP。就是 Python 代码调用 Python 代码，和你在自己脚本里调用一个函数一模一样。

这就是为什么 Gunicorn 启动后你看不到两个独立的服务——Django 根本不是一个"服务"，它是 Gunicorn worker 进程里加载的一个 Python 模块。

## Nginx 与 Gunicorn：不同进程

Nginx 和 Gunicorn 是完全独立的进程，通常甚至是不同语言写的（Nginx 是 C，Gunicorn 是 Python）。它们之间需要通过**网络通信**。

### 方式一：TCP 连接

```nginx
# Nginx 配置
location / {
    proxy_pass http://127.0.0.1:8000;
}
```

```
Nginx 进程                                    Gunicorn 进程
┌────────────┐    TCP 连接（端口 8000）    ┌────────────┐
│ 收到用户请求 │ ──────────────────────→ │ 监听 8000   │
│ 构造 HTTP   │                         │ 解析请求     │
│ 转发给 8000 │ ←────────────────────── │ 返回响应     │
└────────────┘    TCP 连接返回           └────────────┘
```

走的是完整的 TCP 协议栈：TCP 三次握手 → 发送 HTTP 请求 → 接收 HTTP 响应 → TCP 四次挥手。虽然是 `127.0.0.1` 本地回环地址，不经过网卡，但仍然走了操作系统的网络协议栈。

### 方式二：Unix Socket

```nginx
# Nginx 配置
location / {
    proxy_pass http://unix:/run/gunicorn.sock;
}
```

```bash
# Gunicorn 启动
gunicorn config.wsgi --bind unix:/run/gunicorn.sock
```

```
Nginx 进程                                     Gunicorn 进程
┌────────────┐    Unix Socket 文件           ┌────────────┐
│ 收到用户请求 │ ──→ /run/gunicorn.sock ──→  │ 监听 socket │
│ 写入 socket │                              │ 读取请求    │
│             │ ←── /run/gunicorn.sock ←──  │ 写回响应    │
└────────────┘                               └────────────┘
```

Unix Socket 不走网络协议栈，而是在**内核层面直接传递数据**。就像两个人在同一栋楼里，TCP 是发快递（经过快递公司的分拣），Unix Socket 是直接走过去递给对方。

### 两种方式对比

| | TCP (`127.0.0.1:8000`) | Unix Socket (`gunicorn.sock`) |
|--|----------------------|------------------------------|
| 性能 | 稍慢（经过网络协议栈） | 更快（内核直传） |
| 配置 | 简单直观 | 需要管理 .sock 文件权限 |
| 跨机器 | 可以 | 不行（必须同一台机器） |
| 调试 | 方便（curl 直接测） | 不太方便 |
| 适用 | 开发环境、Nginx 和 Gunicorn 在不同机器 | 生产环境、同一台机器 |

大多数生产环境用 Unix Socket，因为 Nginx 和 Gunicorn 通常在同一台机器上，没必要绕一圈网络协议栈。

## Django 与 Celery：不同进程

这是理解起来最关键的一对。Django 跑在 [Gunicorn Worker](./gunicorn.md#master-worker-模型) 里，Celery Worker 是完全独立的进程。

### 为什么不能直接调用

```python
# 你可能以为 .delay() 是这样工作的：
process_document(doc_id=123)  # 直接调用函数

# 但实际上 Django 进程和 Celery 进程在不同的内存空间
# Django 进程里的函数地址对 Celery 进程毫无意义
```

打个比方：你在北京的电脑上有个 Excel 文件，你不能告诉上海的同事"打开内存地址 0x7fff5a2b"——这个地址只在你的电脑上有意义。

### 通信方式：通过 Redis 传递序列化消息

```
Django 进程                Redis                    Celery 进程
┌───────────────┐    ┌─────────────────┐    ┌───────────────────┐
│               │    │                 │    │                   │
│ .delay() 调用  │    │  celery 队列     │    │  持续监听队列      │
│      │        │    │                 │    │       │           │
│      ▼        │    │                 │    │       ▼           │
│ 序列化任务参数  │    │                 │    │  取出消息          │
│ {task: "...", │──→ │  存入 List 结构  │──→ │  反序列化参数      │
│  kwargs: {    │    │                 │    │  找到对应函数       │
│    doc_id:123 │    │                 │    │  执行              │
│  }}           │    │                 │    │  process_document  │
│               │    │                 │    │    (doc_id=123)    │
└───────────────┘    └─────────────────┘    └───────────────────┘
```

`.delay()` 并没有执行函数，它做的事情是：
1. 把函数名和参数**序列化**成 JSON
2. 通过 Redis 客户端**写入** Redis 的队列
3. 返回一个 `AsyncResult` 对象（可以用来查任务状态）

Celery Worker 那边：
1. 一直在 `BRPOP` Redis 队列（阻塞等待）
2. 取到消息后**反序列化**
3. 根据函数名找到本地的函数定义
4. 用反序列化出来的参数执行函数

注意第 3 步——Celery Worker **必须能 import 到同样的任务函数**。这就是为什么 Celery Worker 通常需要和 Django 跑同一份代码。

## 完整通信链路总结

一个用户上传 PDF 的完整流程，标注每一步的通信方式：

```
用户浏览器
  │
  │ ① HTTPS（互联网，TCP 连接）
  ▼
Nginx
  │
  │ ② Unix Socket 或 TCP（同一台机器，内核通信）
  ▼
Gunicorn Worker
  │
  │ ③ 函数调用（同一进程，零开销）
  ▼
Django View
  │
  ├─ ④ TCP 连接（Django → PostgreSQL，SQL 查询）
  │     保存文件记录到数据库
  │
  ├─ ⑤ TCP 连接（Django → Redis，写入任务消息）
  │     process_document.delay(doc_id=123)
  │
  │ ③ 函数调用（同一进程）
  ▼
Gunicorn Worker → Nginx → 用户浏览器
  响应 {"status": "processing"}

... 与此同时 ...

Redis
  │
  │ ⑥ TCP 连接（Celery Worker → Redis，取出任务消息）
  ▼
Celery Worker
  │
  ├─ ④ TCP 连接（Celery → PostgreSQL，读写数据库）
  │     解析 PDF、建索引、更新状态
  │
  └─ 任务完成
```

| 编号 | 通信双方 | 方式 | 原因 |
|------|---------|------|------|
| ① | 浏览器 ↔ Nginx | HTTPS (TCP) | 跨互联网 |
| ② | Nginx ↔ Gunicorn | Unix Socket / TCP | 不同进程 |
| ③ | Gunicorn ↔ Django | 函数调用 | 同一进程 |
| ④ | Django/Celery ↔ PostgreSQL | TCP | 不同进程（甚至可能不同机器） |
| ⑤ | Django ↔ Redis | TCP | 不同进程 |
| ⑥ | Celery ↔ Redis | TCP | 不同进程 |
