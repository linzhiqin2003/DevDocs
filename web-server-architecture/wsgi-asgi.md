# WSGI 与 ASGI：应用服务器和框架之间的协议

> 回到 [总览](./README.md) | 相关：[Gunicorn](./gunicorn.md) · [Uvicorn](./uvicorn.md) · [Django](./django.md) · [Docker](./docker.md) · [进程间通信](./process-communication.md) · [Unix 哲学](./unix-philosophy.md)

## 为什么需要一个协议

[Gunicorn](./gunicorn.md) 是应用服务器，[Django](./django.md) 是 Web 框架。它们是两个独立的项目，由不同的团队开发。那 Gunicorn 怎么知道如何调用 Django？Django 又怎么知道把响应交给谁？

答案是：**双方约定一个标准接口**。这个接口就是 WSGI（或 ASGI）。

```
没有标准协议的世界：
    Gunicorn 只认 Django 的调用方式
    uWSGI 只认 Flask 的调用方式
    每换一个框架或服务器，都要重写对接代码

有标准协议的世界：
    所有服务器都按 WSGI 规范调用
    所有框架都按 WSGI 规范实现
    随便搭配，互相兼容
```

这也是 [Unix 哲学](./unix-philosophy.md) 的体现——通过标准化接口让独立的工具自由组合。

## WSGI：同步时代的标准

WSGI（Web Server Gateway Interface），2003 年通过 PEP 3333 定义。

### 它长什么样

WSGI 规定框架必须提供一个**可调用对象**，接收两个参数：

```python
def application(environ, start_response):
    """
    environ:        一个字典，包含所有 HTTP 请求信息
    start_response: 一个回调函数，用来设置响应状态码和 header
    返回值:          响应体（可迭代对象）
    """
    start_response('200 OK', [('Content-Type', 'text/plain')])
    return [b'Hello, World!']
```

就这么简单。**整个 WSGI 标准的核心就是这一个函数签名。**

### Django 的 WSGI 入口

每个 Django 项目创建时自动生成这个文件：

```python
# config/wsgi.py
import os
from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
application = get_wsgi_application()
```

`get_wsgi_application()` 返回的就是一个符合 WSGI 规范的可调用对象。Django 内部把所有复杂的 middleware、URL 路由、view 处理都包装在里面，但对外暴露的就是 `application(environ, start_response)` 这个标准接口。

### Gunicorn 怎么调用它

```bash
gunicorn config.wsgi:application --workers 4
#        ^^^^^^^^^^^^^^^^^^^^^^^^
#        告诉 Gunicorn：去 config/wsgi.py 里找 application 这个对象
```

[Gunicorn](./gunicorn.md) 内部做的事：

```python
# 简化版伪代码
from config.wsgi import application    # 导入 Django 的 WSGI 对象

while True:
    request = wait_for_request()        # 等 Nginx 转发过来的请求
    environ = parse_to_environ(request) # 把 HTTP 请求转成 environ 字典
    response = application(environ, start_response)  # 调用 Django
    send_back(response)                 # 把响应发回给 Nginx
```

Gunicorn 不知道也不关心 `application` 内部是 Django 还是 Flask 还是你自己写的——只要它符合 WSGI 接口就行。

### WSGI 的局限

WSGI 是**同步、一问一答**的模型：

```
调用 application() → 等它返回 → 拿到完整响应 → 结束

中间不能：
  ✗ 中途发送部分数据（流式响应不好做）
  ✗ 保持长连接（WebSocket 做不了）
  ✗ 异步等待（调外部 API 时线程干等着）
```

2003 年设计 WSGI 的时候，Web 就是"请求 → 响应"，没有 WebSocket，没有 SSE，没有异步。时代变了，WSGI 不够用了。

## ASGI：异步时代的标准

ASGI（Asynchronous Server Gateway Interface），2018 年由 Django 团队提出。

### 它长什么样

```python
async def application(scope, receive, send):
    """
    scope:   一个字典，描述连接信息（类似 WSGI 的 environ，但更丰富）
    receive: 异步函数，用来接收客户端发来的数据
    send:    异步函数，用来向客户端发送数据
    """
    # 接收请求
    event = await receive()

    # 发送响应头
    await send({
        'type': 'http.response.start',
        'status': 200,
        'headers': [[b'content-type', b'text/plain']],
    })

    # 发送响应体
    await send({
        'type': 'http.response.body',
        'body': b'Hello, World!',
    })
```

关键区别：

| | WSGI | ASGI |
|--|------|------|
| 函数类型 | 普通函数 `def` | 异步函数 `async def` |
| 请求获取 | 一次性拿到完整请求（`environ`） | 通过 `await receive()` 按需获取 |
| 响应发送 | 一次性返回完整响应 | 通过 `await send()` 分多次发送 |
| 连接模型 | 一问一答，处理完就断 | 可以保持连接，持续收发数据 |

### 为什么 ASGI 能做 WebSocket 和 SSE

因为 `receive` 和 `send` 可以**多次调用**：

```python
# WSGI：只能返回一次
def application(environ, start_response):
    return [b'done']  # 说完就结束了

# ASGI：可以持续发送
async def application(scope, receive, send):
    # SSE 流式响应
    await send({'type': 'http.response.start', 'status': 200, ...})
    for chunk in generate_llm_response():
        await send({
            'type': 'http.response.body',
            'body': chunk.encode(),
            'more_body': True,           # 还没完，别断开
        })
    await send({
        'type': 'http.response.body',
        'body': b'',
        'more_body': False,              # 这下说完了
    })
```

```python
# WebSocket：双向通信
async def websocket_app(scope, receive, send):
    await send({'type': 'websocket.accept'})       # 接受连接

    while True:
        event = await receive()                      # 等客户端发消息
        if event['type'] == 'websocket.disconnect':
            break
        # 收到消息后回复
        await send({
            'type': 'websocket.send',
            'text': f'你说了: {event["text"]}',
        })
```

### Django 的 ASGI 入口

Django 3.0+ 同时生成两个入口文件：

```python
# config/wsgi.py — 同步入口，给 Gunicorn sync worker 用
application = get_wsgi_application()

# config/asgi.py — 异步入口，给 Uvicorn 用
application = get_asgi_application()
```

用哪个取决于你的应用服务器：

```bash
# 同步部署
gunicorn config.wsgi:application --workers 4

# 异步部署
uvicorn config.asgi:application
# 或
gunicorn config.asgi:application --worker-class uvicorn.workers.UvicornWorker
```

## WSGI 和 ASGI 的兼容关系

ASGI 是 WSGI 的**超集**。Django 的 ASGI 入口可以同时处理同步 view 和异步 view：

```python
# 同步 view — 在 ASGI 下也能跑（Django 自动用线程池包装）
def list_reports(request):
    reports = Report.objects.all()
    return JsonResponse(...)

# 异步 view — 只能在 ASGI 下跑
async def fetch_stock_price(request, symbol):
    async with httpx.AsyncClient() as client:
        resp = await client.get(f'https://api.example.com/stock/{symbol}')
    return JsonResponse(resp.json())
```

所以迁移路径是平滑的：先用 WSGI 跑，需要异步了再切 ASGI，已有的同步 view 不用改。

## 可组合性：协议带来的自由

因为有了标准协议，应用服务器和框架可以自由搭配：

```
WSGI 阵营：
┌─────────────┐     ┌───────────┐
│ Gunicorn    │     │ Django    │
│ uWSGI       │ ──→ │ Flask     │     任意服务器 × 任意框架
│ mod_wsgi    │     │ Bottle    │
└─────────────┘     └───────────┘

ASGI 阵营：
┌─────────────┐     ┌───────────┐
│ Uvicorn     │     │ Django 3+ │
│ Daphne      │ ──→ │ FastAPI   │     任意服务器 × 任意框架
│ Hypercorn   │     │ Starlette │
└─────────────┘     └───────────┘
```

想从 [Gunicorn](./gunicorn.md) 换成 uWSGI？框架代码一行不用改。想从 Django 换成 FastAPI？服务器配置几乎不用动。这就是标准协议的威力。

## 选型指南

```
你的项目需要什么？

只有普通的 HTTP 请求-响应（CRUD API、页面渲染）
└─→ WSGI 足够 → Gunicorn + Django

需要 SSE 流式响应（LLM 聊天逐字输出）
└─→ ASGI 更合适 → Uvicorn + Django async view

需要 WebSocket（实时聊天、通知推送）
└─→ 必须 ASGI → Uvicorn + Django Channels

用 FastAPI
└─→ 只能 ASGI → Uvicorn（FastAPI 基于 Starlette，原生 ASGI）

不确定
└─→ 先用 WSGI，够用就别折腾。需要的时候切 ASGI 成本不高
```
