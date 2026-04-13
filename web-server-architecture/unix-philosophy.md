# Unix 设计哲学：为什么不造一个大一统工具

> 回到 [总览](./README.md) | 相关：[Nginx](./nginx.md) · [Gunicorn](./gunicorn.md) · [Uvicorn](./uvicorn.md) · [Django](./django.md) · [Redis 与 Celery](./redis-celery.md) · [Docker](./docker.md) · [进程间通信](./process-communication.md)

## 从一个问题说起

> 为什么没有一个工具同时做 Gunicorn 的进程管理和 Uvicorn 的异步处理？

这个问题的答案，藏在 1978 年 Unix 操作系统的设计理念里。

## Unix 哲学的核心规则

Ken Thompson 和 Doug McIlroy（Unix 的创造者们）总结了几条原则：

### 1. 每个程序只做一件事，把它做好

不是"做不了别的"，而是**选择只做一件事**。

```
反面例子（假想的 SuperServer）：
┌──────────────────────────────────────┐
│  SuperServer v1.0                    │
│  ├── 反向代理（类似 Nginx）           │
│  ├── 进程管理（类似 Gunicorn）        │
│  ├── 异步事件循环（类似 Uvicorn）     │
│  ├── 任务队列（类似 Celery）          │
│  ├── 消息存储（类似 Redis）           │
│  └── Web 框架（类似 Django）          │
│                                      │
│  代码量：50 万行                      │
│  配置项：2000 个                      │
│  出 bug 了谁来修：😢                  │
└──────────────────────────────────────┘
```

```
Unix 的做法：
┌────────┐  ┌──────────┐  ┌─────────┐  ┌────────┐  ┌───────┐  ┌────────┐
│ Nginx  │→ │ Gunicorn │→ │ Django  │  │ Redis  │→ │Celery │  │Uvicorn │
│ 做代理  │  │ 管进程    │  │ 写业务  │  │ 存消息  │  │ 跑任务 │  │ 跑异步  │
└────────┘  └──────────┘  └─────────┘  └────────┘  └───────┘  └────────┘

每个工具：几万行代码，配置清晰，各自有专门的维护团队
```

### 2. 程序之间通过简单的接口组合

Unix 命令行用**管道**（`|`）把小工具串起来：

```bash
cat access.log | grep "POST" | awk '{print $7}' | sort | uniq -c | sort -rn | head -10
```

六个独立的小工具，通过管道组合，完成了"统计访问量最高的 10 个 POST 接口"这个复杂任务。

Web 架构里也是一样的思路：

```
Nginx 和 Gunicorn 之间的"管道"：TCP / Unix Socket
Gunicorn 和 Django 之间的"管道"：WSGI 协议
Django 和 Redis 之间的"管道"：Redis 协议（TCP）
Redis 和 Celery 之间的"管道"：Redis 协议（TCP）
Gunicorn 和 Uvicorn 之间的"管道"：--worker-class 插件机制
```

每个组件只需要遵守约定好的接口（协议），不需要知道对方内部怎么实现。[Nginx](./nginx.md) 不知道后面是 Gunicorn 还是 uWSGI，它只知道往 `127.0.0.1:8000` 发 HTTP 请求。

### 3. 尽早构建原型，尽早验证

Unix 的做法是先用现有工具组合出一个能跑的方案，而不是花三年从零造一个完美的大工具。

```
需求：Django 项目需要处理异步请求

方案 A（Unix 哲学）：
    gunicorn --worker-class uvicorn.workers.UvicornWorker
    → 5 分钟搞定，马上能跑

方案 B（大一统思维）：
    等 Granian 项目成熟... 等社区完善... 等文档写好...
    → 可能等一两年
```

## 这套哲学在我们架构里的体现

### Gunicorn + Uvicorn 的组合

这是最直接的例子。详见 [Uvicorn](./uvicorn.md#配合-gunicorn)。

```bash
gunicorn config.asgi:application --worker-class uvicorn.workers.UvicornWorker
```

- [Gunicorn](./gunicorn.md) 专注做进程管理（fork、监控、重启、信号处理）
- [Uvicorn](./uvicorn.md) 专注做异步事件循环（`asyncio`、HTTP 解析）

两边各自迭代更新，互不影响：
- Gunicorn 发布新版优化了进程调度？升级 Gunicorn，Uvicorn 不用动
- Uvicorn 修了一个 HTTP/2 的 bug？升级 Uvicorn，Gunicorn 不用动

如果是大一统工具，任何一个子系统的改动都可能影响其他部分。

### Nginx + Gunicorn 的组合

```
为什么不让 Gunicorn 直接面对用户？

因为 Gunicorn 不擅长：
  ✗ 处理 SSL/TLS 加密
  ✗ 伺服静态文件
  ✗ 应对慢客户端（slow loris 攻击）
  ✗ 负载均衡到多台后端

Nginx 不擅长：
  ✗ 执行 Python 代码
  ✗ 理解 WSGI/ASGI 协议

各做各擅长的 → 组合起来 → 比任何一个单独做都强
```

详见 [Nginx](./nginx.md) 和 [进程间通信](./process-communication.md#nginx-与-gunicorn不同进程)。

### Django + Celery + Redis 的组合

```
为什么 Django 不内置任务队列？

因为不是所有 Django 项目都需要后台任务。
硬塞进去会让 Django 变臃肿，不需要的人也得背着这个包袱。

需要的时候：pip install celery → 接入
不需要的时候：Django 干干净净
```

详见 [Redis 与 Celery](./redis-celery.md)。

## 组合的好处

### 1. 独立替换

```
不喜欢 Nginx？换 Caddy：
    Caddy → Gunicorn → Django      ✅ 其他组件不用改

不喜欢 Gunicorn？换 uWSGI：
    Nginx → uWSGI → Django         ✅ 其他组件不用改

不喜欢 Redis？换 RabbitMQ：
    Django → RabbitMQ → Celery     ✅ 其他组件不用改
```

如果是大一统工具，想换掉其中一个子系统？整个重写。

### 2. 独立扩展

```
请求量暴涨，需要更多 Web 处理能力：
    → 多加几台 Gunicorn 服务器，Nginx 做负载均衡
    → Celery 和 Redis 不用动

后台任务积压严重：
    → 多加几个 Celery Worker 节点
    → Nginx 和 Gunicorn 不用动

静态文件访问量大：
    → 前面加 CDN，或者 Nginx 加缓存
    → 后端完全不用动
```

### 3. 独立故障隔离

```
Celery Worker 全挂了：
    → 后台任务停了
    → 但用户还能正常访问网站、发请求

Redis 挂了：
    → 新的后台任务发不出去
    → 但已有的请求处理不受影响

某个 Gunicorn Worker 内存泄漏：
    → Gunicorn Master 自动杀掉重启
    → 其他 Worker 继续服务
    → 用户完全感知不到
```

## 这套哲学的代价

当然也不是没有缺点：

| 代价 | 说明 |
|------|------|
| 部署复杂 | 要装 Nginx + Gunicorn + Redis + Celery，每个都要配置 |
| 调试困难 | 出问题要在多个组件之间排查，日志分散 |
| 学习成本 | 要理解每个工具的职责和它们之间的关系（比如你现在在读的这些文章） |
| 版本兼容 | 升级一个组件可能需要检查和其他组件的兼容性 |

这也是为什么 Docker Compose 和 Kubernetes 这类工具流行的原因——用一个编排工具把这些零散的组件统一管理起来：

```yaml
# docker-compose.yml — 一键启动所有组件
services:
  nginx:
    image: nginx
    ports: ["443:443"]

  web:
    build: .
    command: gunicorn config.wsgi --workers 4

  redis:
    image: redis

  celery:
    build: .
    command: celery -A config worker

  celery-beat:
    build: .
    command: celery -A config beat
```

Unix 哲学说的是"每个工具做一件事"，不是说"让人类手动管所有工具"。编排工具解决的是管理问题，不改变每个工具各司其职的设计。

## 一句话总结

> 做一件事，做好它。需要做更多的事？组合多个做好一件事的工具。

我们整个 Web 架构就是这句话的实践：

| 工具 | 做好的那一件事 |
|------|-------------|
| [Nginx](./nginx.md) | 接收连接、转发请求、伺服静态文件 |
| [Gunicorn](./gunicorn.md) | 管理 Python 应用进程 |
| [Uvicorn](./uvicorn.md) | 在单个进程里高效处理异步请求 |
| [Django](./django.md) | 实现 Web 业务逻辑 |
| [Redis](./redis-celery.md) | 高速存取内存数据 |
| [Celery](./redis-celery.md) | 分布式任务调度与执行 |
