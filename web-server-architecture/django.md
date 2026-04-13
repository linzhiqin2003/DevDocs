# Django：请求的一生

> 回到 [总览](./README.md) | 相关：[Nginx](./nginx.md) · [Gunicorn](./gunicorn.md) · [Uvicorn](./uvicorn.md) · [Redis 与 Celery](./redis-celery.md) · [Docker](./docker.md) · [进程间通信](./process-communication.md) · [WSGI & ASGI](./wsgi-asgi.md) · [Unix 哲学](./unix-philosophy.md)

## Django 是什么

Django 是一个 Python Web 框架。在整个架构里，它是**真正干活的人**——接收请求、查数据库、调 API、执行业务逻辑、返回结果。

[Nginx](./nginx.md) 和 [Gunicorn](./gunicorn.md) 都是为了让 Django 能更好地服务用户而存在的基础设施。Django 本身并不关心外面有几层代理、有多少个 worker，它只知道：收到一个请求，返回一个响应。

## 一个请求在 Django 里经历了什么

当 [Gunicorn](./gunicorn.md) 的某个 worker 把请求交给 Django 后：

```
HTTP 请求进入
    │
    ▼
┌─────────────────────────────┐
│  1. WSGI Handler             │  把原始 HTTP 请求包装成 Django 的 HttpRequest 对象
└──────────────┬──────────────┘
               ▼
┌─────────────────────────────┐
│  2. Middleware（请求阶段）    │  依次执行：安全检查、Session 加载、认证、CORS...
│     SecurityMiddleware       │
│     SessionMiddleware        │
│     AuthenticationMiddleware │
│     ...                      │
└──────────────┬──────────────┘
               ▼
┌─────────────────────────────┐
│  3. URL Router               │  根据 URL 路径匹配到对应的 view 函数
│     /api/reports/ → views.py │
└──────────────┬──────────────┘
               ▼
┌─────────────────────────────┐
│  4. View 函数                │  真正的业务逻辑
│     - 验证参数               │
│     - 查数据库               │
│     - 调外部 API             │
│     - 构造响应数据            │
└──────────────┬──────────────┘
               ▼
┌─────────────────────────────┐
│  5. Middleware（响应阶段）    │  反向执行：添加 header、处理跨域、压缩...
└──────────────┬──────────────┘
               ▼
HTTP 响应返回
```

整个流程是**同步、线性、阻塞**的。从进入到返回，这个 [Gunicorn worker](./gunicorn.md#master-worker-模型) 一直被占用。

## Middleware：请求的安检通道

Middleware 就像机场安检——每个请求进来都要过一遍，每个响应出去也要过一遍。

```python
# settings.py
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',      # 安全头、HTTPS 重定向
    'django.contrib.sessions.middleware.SessionMiddleware', # Session 处理
    'corsheaders.middleware.CorsMiddleware',                # CORS 跨域
    'django.middleware.common.CommonMiddleware',            # URL 规范化
    'django.middleware.csrf.CsrfViewMiddleware',           # CSRF 防护
    'django.contrib.auth.middleware.AuthenticationMiddleware', # 用户认证
]
```

**顺序很重要**。请求进来时从上往下走，响应出去时从下往上走。比如 `SessionMiddleware` 必须在 `AuthenticationMiddleware` 前面，因为认证依赖 session。

你也可以写自定义 middleware，比如记录每个请求的耗时：

```python
import time
import logging

logger = logging.getLogger(__name__)

class RequestTimingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        start = time.time()
        response = self.get_response(request)  # 这一行执行了后面所有的 middleware + view
        duration = time.time() - start
        logger.info(f"{request.method} {request.path} → {response.status_code} ({duration:.2f}s)")
        return response
```

## View：业务逻辑的核心

URL 匹配到 view 后，view 函数开始执行。以一个报告列表接口为例：

```python
# views.py
class ReportViewSet(viewsets.ModelViewSet):
    queryset = Report.objects.all()
    serializer_class = ReportSerializer

    def list(self, request):
        # 1. 从数据库查所有报告（同步阻塞，等数据库返回）
        reports = self.get_queryset().filter(user=request.user)

        # 2. 序列化成 JSON
        serializer = self.get_serializer(reports, many=True)

        # 3. 返回响应
        return Response(serializer.data)
```

这个 view 很快，几毫秒就完成了。但如果换成：

```python
def upload_and_index(self, request):
    file = request.FILES['document']

    # 1. 保存文件到磁盘（快，几十 ms）
    doc = Document.objects.create(file=file, user=request.user)

    # 2. 解析 PDF 内容（慢，可能 5-10 秒）
    content = parse_pdf(doc.file.path)

    # 3. 做文档索引（慢，可能 20-60 秒）
    index_document(content, doc.id)

    # 4. 终于返回了...
    return Response({"status": "done", "doc_id": doc.id})
```

从步骤 1 到步骤 4，这个请求占用了一个 [Gunicorn worker](./gunicorn.md#worker-耗尽真实场景) 长达几十秒。如果 4 个用户同时上传 PDF，4 个 worker 全被占满，其他用户连首页都打不开。

## 同步 vs 异步：WSGI 和 ASGI

### WSGI（同步，传统方式）

Django 默认跑在 WSGI 协议上。一个请求进来，从头到尾占用一个进程/线程，中间所有操作都是阻塞的。

```python
# wsgi.py — Django 项目自带
import os
from django.core.wsgi import get_wsgi_application
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
application = get_wsgi_application()
```

[Gunicorn](./gunicorn.md) 默认就是通过这个 `application` 对象来调用 Django 的。

### ASGI（异步，新方式）

Django 3.0+ 支持 ASGI，允许写异步 view：

```python
# asgi.py — Django 项目自带
import os
from django.core.asgi import get_asgi_application
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
application = get_asgi_application()
```

```python
# 异步 view 示例
import httpx

async def fetch_stock_price(request, symbol):
    async with httpx.AsyncClient() as client:
        # 这里不会阻塞线程！等待网络响应时，worker 可以去处理其他请求
        resp = await client.get(f"https://api.example.com/stock/{symbol}")
    return JsonResponse(resp.json())
```

区别在哪：
- **WSGI**：调外部 API 时，线程干等着，啥也不干
- **ASGI**：调外部 API 时，`await` 让出控制权，worker 去处理其他请求，API 返回后再继续

但 ASGI 不是银弹。Django 的 ORM 目前大部分操作仍然是同步的（虽然有 `async` 接口，底层还是用线程池包装的同步调用）。完全异步化需要整条链路都支持异步，包括数据库驱动、缓存客户端等。

### 什么时候用 ASGI

| 场景 | WSGI 还是 ASGI |
|------|---------------|
| 普通 CRUD（增删改查） | WSGI 足够 |
| 大量调外部 API（搜索、LLM） | ASGI 有优势 |
| WebSocket（实时聊天、通知） | 必须 ASGI |
| SSE 流式响应 | ASGI 更合适 |
| 传统模板渲染网站 | WSGI 足够 |

## Celery：什么时候该引入

先明确一点：**Celery 不是 Django 的一部分**，它是一个独立的分布式任务队列。但它和 Django 配合得最好，几乎成了 Django 处理后台任务的标配。

### 不用 Celery 的世界

```python
def upload_document(request):
    doc = save_file(request.FILES['file'])
    content = parse_pdf(doc.file.path)        # 阻塞 10 秒
    index_document(content, doc.id)            # 阻塞 30 秒
    send_notification_email(request.user)      # 阻塞 2 秒
    return Response({"status": "done"})        # 用户等了 42 秒
```

问题：
1. 用户等 42 秒看转圈，体验极差
2. 占着 [Gunicorn worker](./gunicorn.md#worker-耗尽真实场景) 42 秒
3. 中途用户关掉页面，任务直接中断
4. 如果 [Nginx 超时](./nginx.md#4-超时控制--504-的来源) 设为 60s，处理时间只要超过 60s 就 504

### 用 Celery 的世界

```python
# tasks.py
from celery import shared_task

@shared_task
def process_document(doc_id):
    doc = Document.objects.get(id=doc_id)
    content = parse_pdf(doc.file.path)        # 慢慢来，不着急
    index_document(content, doc.id)            # 后台 worker 在跑
    send_notification_email(doc.user)          # 跑完了通知用户
    doc.status = 'done'
    doc.save()
```

```python
# views.py
def upload_document(request):
    doc = save_file(request.FILES['file'])
    process_document.delay(doc.id)             # 丢给 Celery，立即返回
    return Response({
        "status": "processing",
        "doc_id": doc.id
    })  # 用户 1 秒就看到响应
```

架构变成了：

```
用户请求
    │
    ▼
Django View → 创建任务 → 立即返回 "processing"
                │
                ▼
           Redis（消息队列）
                │
                ▼
         Celery Worker（独立进程）
                │
                ├── 解析 PDF
                ├── 建索引
                └── 发邮件
                │
                ▼
           任务完成，更新数据库状态
```

前端拿到 `doc_id` 后，可以每隔几秒轮询 `/api/documents/{doc_id}/status/`，或者通过 WebSocket/SSE 实时推送进度。

### 什么时候该引入 Celery

不是所有项目都需要。问自己几个问题：

| 问题 | 不需要 Celery | 需要 Celery |
|------|-------------|------------|
| 最慢的请求要多久？ | < 5 秒 | > 10 秒 |
| 有定时任务吗？ | 没有，或用 cron 就行 | 复杂的定时逻辑 |
| 并发用户多吗？ | 个位数 | 几十到几百 |
| 任务失败需要重试吗？ | 不需要 | 需要可靠的重试机制 |
| 用户能接受等待吗？ | 能 | 不能，需要立即响应 |

**引入 Celery 的代价**：多一个进程要维护（Celery worker）、多一个中间件要部署（Redis/RabbitMQ）、代码复杂度增加（异步调试比同步难）。小项目别过早引入。

## Django 在整个架构中的位置

回到全局视角：

```
用户浏览器
    ↓
Nginx        ← 不懂 Python，只做转发和静态文件（详见 nginx.md）
    ↓
Gunicorn     ← 不懂业务，只管理进程（详见 gunicorn.md）
    ↓
Django       ← 真正处理业务逻辑的地方（你写的代码在这里跑）
    ↓
Celery       ← 可选，处理后台耗时任务（独立进程，不在请求链路中）
```

每一层都只做自己擅长的事。Nginx 擅长高并发连接管理，Gunicorn 擅长进程管理，Django 擅长业务逻辑。这种分层让每个组件都可以独立优化和替换，而不是把所有事情堆在一起变成一坨。
