# Redis 与 Celery：后台任务系统

> 回到 [总览](./README.md) | 相关：[Nginx](./nginx.md) · [Gunicorn](./gunicorn.md) · [Uvicorn](./uvicorn.md) · [Django](./django.md) · [Docker](./docker.md) · [进程间通信](./process-communication.md) · [Unix 哲学](./unix-philosophy.md)

## 先说清楚它们和请求链路的关系

用户的请求走的是这条路：

```
用户 → Nginx → Gunicorn → Django → 响应
```

Redis 和 Celery **不在这条路上**。它们是 Django 在处理请求时，把耗时的活"外包"出去的一套系统：

```
请求链路（快，秒级响应）：
    用户 → Nginx → Gunicorn → Django → "任务已提交" → 用户

后台链路（慢，可以跑几分钟）：
    Django ──发消息──→ Redis ──取消息──→ Celery Worker ──完成后写数据库
```

两条线是完全独立的进程，互不阻塞。详见 [进程间通信](./process-communication.md) 了解为什么需要 Redis 做中间人。

## Redis 是什么

Redis 是一个**内存数据库**。数据存在内存里，所以读写极快（微秒级）。它不是关系型数据库（不能建表、写 SQL），而是一个 key-value 存储，类似一个超快的 Python 字典。

### Redis 在这套架构里的角色

| 角色 | 干什么 | 类比 |
|------|-------|------|
| Celery Broker | 暂存任务消息，等 Worker 来取 | 餐厅里的出菜窗口 |
| Celery Backend | 存任务执行结果和状态（可选） | 取餐号状态板 |
| Django 缓存 | 缓存热点数据，减少数据库查询 | 备忘便签 |
| Session 存储 | 存用户登录状态 | 入场手环 |

一个 Redis 实例身兼数职，这也是大多数项目选 Redis 而不是单独装 RabbitMQ 的原因——反正都要装 Redis 做缓存，顺便让它当 Broker。

### 作为 Broker 时 Redis 里面长什么样

Django 调用 `process_document.delay(doc_id=123)` 时，实际上是往 Redis 里写了一条消息：

```json
{
    "task": "tasks.process_document",
    "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "args": [],
    "kwargs": {"doc_id": 123},
    "retries": 0
}
```

这条消息被推入 Redis 的一个 List（队列）。Celery Worker 在另一端不停地 `BRPOP`（阻塞式弹出），取到消息就执行。

```
Redis 内部：

celery 队列 (List)
┌──────────────────────────────────────────┐
│ task:process_document(123)               │ ← Worker 从这头取
│ task:send_email(user_id=456)             │
│ task:generate_report(report_id=789)      │ ← Django 从这头塞
└──────────────────────────────────────────┘
```

先进先出，公平排队。

## Celery 是什么

Celery 是一个 **分布式任务队列框架**。它不是服务器，不是数据库，而是一套"怎么定义任务、怎么发任务、怎么执行任务"的框架。

### Celery 的三个组成部分

```
┌─────────────────┐
│  1. 任务定义      │  @shared_task 装饰器标记哪些函数是"任务"
│     (你的代码)    │
└────────┬────────┘
         │ .delay() 调用
         ▼
┌─────────────────┐
│  2. Broker       │  Redis / RabbitMQ，暂存任务消息
│     (消息中间件)  │
└────────┬────────┘
         │ Worker 取出
         ▼
┌─────────────────┐
│  3. Worker       │  独立进程，取出任务并执行
│     (执行者)     │
└─────────────────┘
```

### 为什么需要中间件（Broker）

Django 和 Celery Worker 是**两个独立的进程**，内存空间完全隔离，不能直接调用对方的函数。这跟 [Gunicorn 和 Django 在同一个进程里](./process-communication.md#gunicorn-与-django同一进程) 完全不同。

需要一个双方都能访问的"公告栏"来传递消息，Redis 就是这个公告栏。详细的进程间通信原理见 [进程间通信](./process-communication.md#django-与-celery不同进程)。

### 实际代码

**定义任务：**

```python
# tasks.py
from celery import shared_task

@shared_task(bind=True, max_retries=3)
def process_document(self, doc_id):
    """后台处理文档：解析 + 索引"""
    try:
        doc = Document.objects.get(id=doc_id)
        doc.status = 'processing'
        doc.save()

        content = parse_pdf(doc.file.path)       # 慢操作，10 秒
        index_document(content, doc.id)           # 慢操作，30 秒

        doc.status = 'done'
        doc.save()
    except Exception as exc:
        doc.status = 'failed'
        doc.save()
        raise self.retry(exc=exc, countdown=60)   # 60 秒后重试
```

**发送任务（在 Django view 里）：**

```python
# views.py
def upload_document(request):
    doc = save_file(request.FILES['file'])

    # .delay() 不会执行函数，而是往 Redis 写一条消息
    process_document.delay(doc_id=doc.id)

    # 立刻返回，不等任务完成
    return Response({"status": "processing", "doc_id": doc.id})
```

**前端轮询进度：**

```python
# views.py
def document_status(request, doc_id):
    doc = Document.objects.get(id=doc_id)
    return Response({"status": doc.status})  # processing / done / failed
```

```javascript
// 前端每 3 秒查一次
const poll = setInterval(async () => {
    const res = await fetch(`/api/documents/${docId}/status/`);
    const data = await res.json();
    if (data.status === 'done') {
        clearInterval(poll);
        showSuccess('文档处理完成');
    } else if (data.status === 'failed') {
        clearInterval(poll);
        showError('处理失败');
    }
}, 3000);
```

## Celery Worker 的运行方式

```bash
# 启动 Celery Worker
celery -A config worker --loglevel=info --concurrency=4
```

这会启动 4 个并发工作单元，持续监听 Redis 队列。一有任务就取走执行。

```
Celery Worker 进程
├── 工作单元 1 ← 正在跑 process_document(123)
├── 工作单元 2 ← 正在跑 send_email(456)
├── 工作单元 3 ← 空闲，等待任务
└── 工作单元 4 ← 空闲，等待任务
```

注意：Celery Worker 和 [Gunicorn Worker](./gunicorn.md#master-worker-模型) 是**两拨完全不同的 worker**：

| | Gunicorn Worker | Celery Worker |
|--|----------------|---------------|
| 处理什么 | HTTP 请求 | 后台任务 |
| 要求 | 快，秒级返回 | 可以慢，跑几分钟都行 |
| 谁触发 | 用户发请求 | Django 代码调用 `.delay()` |
| 挂了影响 | 用户看到 502 | 任务失败，可重试 |

## Celery Beat：定时任务

Celery 除了处理"Django 丢过来的即时任务"，还能做定时任务：

```python
# config/celery.py
from celery.schedules import crontab

app.conf.beat_schedule = {
    'daily-report': {
        'task': 'tasks.generate_daily_report',
        'schedule': crontab(hour=8, minute=0),    # 每天早上 8 点
    },
    'cleanup-old-files': {
        'task': 'tasks.cleanup_temp_files',
        'schedule': crontab(hour=3, minute=0),    # 凌晨 3 点清理
    },
}
```

```bash
# 额外启动一个 beat 进程（定时发任务的闹钟）
celery -A config beat --loglevel=info
```

Beat 进程不执行任务，它只是到点了往 Redis 里塞一条任务消息，然后 Worker 来取走执行。

## 什么时候不需要 Celery

| 场景 | 建议 |
|------|------|
| 所有请求都在 5 秒内完成 | 不需要 |
| 只有 1-2 个简单定时任务 | 用系统 cron 就行 |
| 个位数用户，偶尔慢一下能接受 | 不需要 |
| 需要可靠的任务重试和状态追踪 | 需要 |
| 多个耗时操作会堵住 [Gunicorn Worker](./gunicorn.md#worker-耗尽真实场景) | 需要 |

引入 Celery 的代价：多维护一个 Worker 进程 + 一个 Redis 实例 + Beat 进程（如果要定时任务），代码复杂度也会增加。小项目别过早引入。
