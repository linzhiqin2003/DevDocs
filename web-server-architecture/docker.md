# Docker：把整个环境装进箱子

> 回到 [总览](./README.md) | 相关：[Nginx](./nginx.md) · [Gunicorn](./gunicorn.md) · [Uvicorn](./uvicorn.md) · [Django](./django.md) · [Redis 与 Celery](./redis-celery.md) · [进程间通信](./process-communication.md) · [WSGI & ASGI](./wsgi-asgi.md) · [Unix 哲学](./unix-philosophy.md)

## Docker 在架构里的位置

Docker 不在请求链路里。它不像 [Nginx](./nginx.md)、[Gunicorn](./gunicorn.md) 那样处理请求。它在所有组件的**下面**，是一个基础设施层：

```
没有 Docker：                          有 Docker：
┌─────────────────────┐          ┌──────────────────────────┐
│  操作系统 (Ubuntu)    │          │  操作系统 (Ubuntu)        │
│                     │          │                          │
│  Nginx              │          │  Docker Engine           │
│  Python + Django    │          │  ┌────────┐ ┌─────────┐ │
│  Gunicorn           │          │  │ Nginx  │ │ Django  │ │
│  Redis              │          │  │ 容器    │ │ 容器     │ │
│  PostgreSQL         │          │  └────────┘ └─────────┘ │
│  Celery             │          │  ┌────────┐ ┌─────────┐ │
│                     │          │  │ Redis  │ │ Celery  │ │
│  全部直接装在系统上    │          │  │ 容器    │ │ 容器     │ │
└─────────────────────┘          │  └────────┘ └─────────┘ │
                                 │  ┌──────────┐           │
                                 │  │PostgreSQL│           │
                                 │  │ 容器      │           │
                                 │  └──────────┘           │
                                 └──────────────────────────┘
```

Docker 解决的问题：**把应用和它的整个运行环境打包成一个标准化的箱子（容器），搬到哪台机器上都能直接跑。**

## 三个核心概念

### 镜像（Image）：文件快照

镜像是一堆打包好的**只读文件**，里面没有任何正在运行的东西。你可以把它理解成一个 U 盘：

```
项目镜像里的文件：
├── /usr/local/bin/python
├── /usr/local/bin/gunicorn
├── /usr/local/bin/celery
├── /app/manage.py
├── /app/config/wsgi.py
├── /app/research/tasks.py
└── ... 所有依赖库
```

镜像怎么来的？通过 Dockerfile 构建：

```dockerfile
# Dockerfile — 描述怎么制作这个 U 盘
FROM python:3.11-slim                    # 基于官方 Python 镜像

WORKDIR /app                             # 工作目录
COPY requirements.txt .                  # 复制依赖清单
RUN pip install -r requirements.txt      # 安装依赖
COPY . .                                 # 复制项目代码

CMD ["gunicorn", "config.wsgi", "--bind", "0.0.0.0:8000"]  # 默认启动命令
```

```bash
docker build -t my-django-app .    # 打包成镜像
```

除了自己构建，也可以直接用别人做好的镜像。Docker Hub 上有大量官方预制镜像：

```bash
docker pull nginx          # Nginx 官方镜像
docker pull redis:7        # Redis 7 官方镜像
docker pull postgres:15    # PostgreSQL 15 官方镜像
```

### 容器（Container）：跑起来的实例

容器是从镜像启动的一个**独立运行环境**。镜像是图纸，容器是按图纸造出来的房子。

**一个镜像可以启动任意多个容器：**

```
                    ┌──────────┐
               ┌──→ │ 容器 1    │  command: gunicorn ...
┌──────────┐   │    └──────────┘
│ 项目镜像  │───┤
│ (文件模板) │   │    ┌──────────┐
└──────────┘   └──→ │ 容器 2    │  command: celery worker
                    └──────────┘
```

镜像里同时有 Gunicorn 和 Celery 的可执行文件。启动容器时你决定执行哪个——就像一个 U 盘里有 Word 和 Excel，你插到电脑上选择打开哪个程序。容器之间是并列关系，不是嵌套关系。

为什么 web 和 celery 用同一个镜像？因为 [Celery Worker](./redis-celery.md) 需要 `import` Django 的 model 和项目代码才能执行任务，它们本来就是同一个代码库。没必要打两个内容 99% 重复的镜像。

而 [Nginx](./nginx.md)、[Redis](./redis-celery.md#redis-是什么)、PostgreSQL 不需要你的项目代码，所以它们各自是独立的官方镜像。

### Docker Engine：施工队 + 物业

Docker 本身是管理镜像和容器的工具：

```
Docker Engine
├── 构建镜像    docker build
├── 存储镜像    docker images
├── 启动容器    docker run
├── 停止容器    docker stop
├── 查看容器    docker ps
├── 容器间网络  自动创建虚拟网络，让容器互相访问
└── 数据卷管理  持久化存储（容器删了数据还在）
```

镜像是图纸，容器是房子，Docker 是施工队 + 物业——负责按图纸造房子、管理所有房子的水电网络、房子出问题了拆掉重建。

## 容器 vs 虚拟机

容器不是虚拟机。虚拟机模拟了一整台电脑（包括操作系统内核），容器只是用 Linux 内核的隔离功能把进程关在"围栏"里。

```
虚拟机：
┌───────────────────────────────┐
│  宿主机 OS                     │
│  ┌─────────────┐ ┌──────────┐ │
│  │ 完整的 OS    │ │ 完整的 OS │ │  ← 每个虚拟机装一个完整操作系统
│  │ (Ubuntu)    │ │ (CentOS) │ │     几个 GB，启动几十秒
│  │  ┌────────┐ │ │ ┌──────┐ │ │
│  │  │ Nginx  │ │ │ │Redis │ │ │
│  │  └────────┘ │ │ └──────┘ │ │
│  └─────────────┘ └──────────┘ │
└───────────────────────────────┘

Docker 容器：
┌───────────────────────────────┐
│  宿主机 OS（共享内核）           │
│  ┌────────┐ ┌──────┐         │
│  │ Nginx  │ │Redis │         │  ← 没有完整 OS，共享宿主机内核
│  │ 几十MB  │ │几十MB │         │     启动几秒
│  └────────┘ └──────┘         │
└───────────────────────────────┘
```

| | 虚拟机 | Docker 容器 |
|--|-------|------------|
| 隔离级别 | 硬件级别（完整 OS） | 进程级别（共享内核） |
| 体积 | 几 GB | 几十 MB ~ 几百 MB |
| 启动速度 | 几十秒 | 几秒 |
| 性能 | 有损耗（虚拟化开销） | 接近原生 |
| 适用 | 需要不同操作系统 | 同一 OS 上隔离应用 |

## Docker Compose：一键编排多容器

单独管理 5 个容器很麻烦。Docker Compose 用一个 YAML 文件描述所有容器和它们的关系，一条命令全部启动：

```yaml
# docker-compose.yml
services:
  nginx:
    image: nginx
    ports: ["443:443"]
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf

  web:
    build: .
    command: gunicorn config.wsgi --bind 0.0.0.0:8000 --workers 4
    depends_on:
      - db
      - redis

  redis:
    image: redis:7

  celery:
    build: .
    command: celery -A config worker --loglevel=info
    depends_on:
      - redis

  db:
    image: postgres:15
    volumes:
      - pgdata:/var/lib/postgresql/data    # 数据持久化

volumes:
  pgdata:    # 容器删了，数据库数据还在
```

```bash
docker compose up -d      # 一键启动全部 5 个容器
docker compose down        # 一键停止并移除
docker compose logs web    # 查看某个容器日志
docker compose restart celery  # 单独重启某个容器
```

### 容器间怎么通信

Docker Compose 自动创建一个内部虚拟网络，容器之间用**服务名**互相访问：

```python
# Django settings.py
DATABASES = {
    'default': {
        'HOST': 'db',              # ← 直接写服务名，Docker DNS 自动解析
        'PORT': '5432',
    }
}

REDIS_URL = 'redis://redis:6379/0'  # ← "redis" 就是 redis 容器
```

不需要写 IP 地址。对外只暴露 Nginx 的 443 端口，其他容器完全不暴露，外面访问不到。

这些容器间的通信本质上仍然是 [TCP 连接](./process-communication.md)，只不过走的是 Docker 创建的虚拟网络。

## 迁移服务器：Docker 的核心价值

### 没有 Docker 的迁移

```
旧服务器 → 新服务器

1. 安装 Ubuntu，配置系统           30 分钟
2. 装 Python 3.11（编译安装）       20 分钟
3. 装 Nginx，改配置文件            15 分钟
4. 装 PostgreSQL，建库建表          15 分钟
5. 装 Redis                       5 分钟
6. git clone 项目代码               2 分钟
7. pip install 依赖                5 分钟
8. 配 systemd 服务（Gunicorn、Celery）  20 分钟
9. 调试各种环境不一致的问题          ??? 分钟

总计：2 小时 ~ 半天（如果遇到坑）
```

### 有 Docker 的迁移

```
旧服务器 → 新服务器

1. 安装 Docker                     5 分钟
2. 复制 docker-compose.yml + .env   1 分钟
3. docker compose up -d            3 分钟（拉镜像 + 启动）
4. 导入数据库备份                    几分钟

总计：10 分钟，零环境问题
```

## 优势与代价

### 优势

| 收益 | 说明 |
|------|------|
| 环境一致 | 镜像锁死所有版本，不存在"我本地能跑" |
| 迁移简单 | 新服务器装个 Docker，`docker compose up`，完事 |
| 隔离干净 | 同一台机器跑三个项目，Python 3.9 / 3.11 / 3.13 各自容器互不冲突 |
| 回滚方便 | 切回上一个镜像版本，几秒钟。裸机部署回滚基本靠祈祷 |
| 扩容简单 | 需要更多 [Celery Worker](./redis-celery.md)？多启几个容器就行 |
| 新人友好 | 加入团队，`docker compose up`，开发环境就搭好了 |

### 代价

| 代价 | 说明 |
|------|------|
| 多一层抽象 | 调试链路变长。以前直接看进程日志，现在要 `docker logs`、`docker exec` 进容器排查 |
| 性能微损 | 容器虚拟网络比裸机直连稍慢。对 Web 应用可忽略，对极端性能场景（高频交易）可能在意 |
| 学习成本 | Dockerfile 怎么写、Compose 怎么编排、数据卷怎么持久化、网络怎么配——这些都要学 |
| 数据持久化 | 容器本身是临时的，删了就没。数据库、用户上传的文件必须挂载 volume，否则数据丢失 |
| 日志管理 | 日志在容器里，需要额外配置收集方案（ELK、Loki 等） |
| 磁盘占用 | 镜像会积累，不清理的话几十个 GB 很常见。需要定期 `docker system prune` |

### 实际建议

| 场景 | 建议 |
|------|------|
| 一台服务器跑一个项目，不打算迁移 | 可用可不用，裸机部署也行 |
| 可能换服务器、或多台机器部署 | 用 Docker，迁移成本极低 |
| 同一台机器跑多个项目 | 用 Docker，隔离冲突 |
| 团队协作，新人要搭环境 | 用 Docker，一键搞定 |
| 学习投资 | 值得。Docker 是现代后端开发的基础技能 |

## Docker 和其他组件的关系总结

Docker 不替代任何现有组件，它是把这些组件"装箱"的工具：

```
┌─ Docker Compose 编排 ──────────────────────────────┐
│                                                     │
│  ┌────────┐                                        │
│  │ Nginx  │ ← 官方镜像，开箱即用                     │
│  │ 容器    │                                        │
│  └───┬────┘                                        │
│      │ 虚拟网络                                      │
│  ┌───▼────────┐    ┌────────┐    ┌──────────┐     │
│  │  Web 容器   │───→│ Redis  │───→│ Celery   │     │
│  │  Gunicorn  │    │ 容器    │    │ 容器      │     │
│  │  + Django  │    └────────┘    └──────────┘     │
│  └───┬────────┘                                    │
│      │                                             │
│  ┌───▼────────┐                                    │
│  │ PostgreSQL │ ← 数据挂载到 volume，容器删了数据还在  │
│  │ 容器        │                                    │
│  └────────────┘                                    │
│                                                     │
└─────────────────────────────────────────────────────┘
```

[Nginx](./nginx.md) 还是做代理，[Gunicorn](./gunicorn.md) 还是管进程，[Django](./django.md) 还是跑业务，[Celery](./redis-celery.md) 还是跑后台任务——它们的职责没有任何变化（[Unix 哲学](./unix-philosophy.md)）。Docker 只是让部署、迁移、扩容这些运维操作变得标准化和可重复。
