# Python Web 框架：从玩具到全家桶

> 回到 [总览](./README.md) | 相关：[Gunicorn](./gunicorn.md) · [Uvicorn](./uvicorn.md) · [Django](./django.md) · [WSGI & ASGI](./wsgi-asgi.md) · [Docker](./docker.md) · [Unix 哲学](./unix-philosophy.md)

## 四个级别，四种哲学

```
能力由少到多：

http.server ──→ Flask ──→ FastAPI ──→ Django
 静态文件服务     微框架     现代 API 框架   全家桶
 (1997)         (2010)    (2018)        (2003/2005)
```

## http.server — Python 自带的文件服务器

**背景**：Python 标准库的一部分，最早可追溯到 1997 年（Python 1.5）。Python 2 时代叫 `SimpleHTTPServer`，Python 3 合并进 `http.server` 模块。作者是 Guido van Rossum 和 CPython 核心团队。

**设计目的**：零依赖、开箱即用的本地文件服务器。不是为了写 Web 应用，就是为了一行命令分享文件。

```bash
python -m http.server 8000    # Python 3
python -m SimpleHTTPServer     # Python 2（已淘汰）
```

### 能做什么

```
✓ GET /index.html       → 返回文件
✓ GET /images/logo.png  → 返回图片
✓ GET /                 → 返回目录列表
✓ HEAD 请求             → 返回 header
```

### 不能做什么

```
✗ POST / PUT / DELETE   → 没有内置支持
✗ 路由匹配             → 不认识 /api/users
✗ 查询参数解析          → 不会处理 ?id=3
✗ JSON 响应            → 不会序列化
✗ 数据库 / Session     → 没有
✗ 任何动态逻辑          → 它只读文件
```

你可以继承 `BaseHTTPRequestHandler` 手写所有逻辑，但那就是在手动重新发明框架：

```python
from http.server import HTTPServer, BaseHTTPRequestHandler
import json

class MyHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/api/hello':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'msg': 'hi'}).encode())
        else:
            self.send_response(404)
            self.end_headers()

HTTPServer(('', 8000), MyHandler).serve_forever()
```

十行业务逻辑配一百行胶水代码。这就是为什么需要框架。

---

## Flask — 一个愚人节玩笑变成的微框架

**创建时间**：2010 年 4 月 1 日（愚人节）

**创建者**：Armin Ronacher，奥地利开发者，Pocoo 团队成员。Pocoo 之前已经造了两个重要的轮子：Werkzeug（WSGI 工具库，2007）和 Jinja2（模板引擎，2008）。

**诞生故事**：当时 Python Web 框架圈子里微框架泛滥，Ronacher 觉得很荒谬——大家都在造"最小的框架"。他写了一个叫 "Denied" 的愚人节项目，把 Werkzeug 和 Jinja2 塞进一个文件里，讽刺这个现象。结果社区反而觉得"这玩意儿真的挺好用"，于是认真做了下去，改名 Flask。

**解决的问题**：2010 年的 Python Web 世界被 Django 统治，但 Django 太重了——写一个小 API 也要拉一整套项目结构。Flask 给了另一种选择：只提供路由和请求处理，其他全部自选。

```python
from flask import Flask
app = Flask(__name__)

@app.route('/hello')
def hello():
    return 'Hello, World!'
```

### 哲学：空房间，家具自己买

Flask 自带的东西：路由、请求/响应对象、Jinja2 模板。其他全靠扩展：

| 需要什么 | Flask 的答案 |
|---------|-------------|
| 数据库 ORM | 自己装 SQLAlchemy |
| 用户认证 | 自己装 Flask-Login |
| 表单验证 | 自己装 WTForms |
| 后台管理 | 自己装 Flask-Admin |
| API 文档 | 自己装 Flask-Swagger |

### 发展历程

| 时间 | 里程碑 |
|------|--------|
| 2010.4 | v0.1 发布 |
| 2016 | Pocoo 项目转入 Pallets 社区组织 |
| 2018.4 | **Flask 1.0**——在 0.x 待了 8 年终于稳定 |
| 2021.5 | **Flask 2.0**——砍掉 Python 2，加入 async view 支持 |
| 2023 | Flask 3.0，要求 Python 3.8+ |

---

## Django — 新闻编辑室里逼出来的全家桶

**创建时间**：2003 年秋天（内部开发），2005 年 7 月 13 日公开发布

**创建者**：Adrian Holovaty 和 Simon Willison，堪萨斯州 **Lawrence Journal-World** 报社的 Web 开发者。Jacob Kaplan-Moss 在 Willison 实习结束后加入，成为核心维护者。

**命名来源**：爵士吉他手 Django Reinhardt。Holovaty 本人是吉普赛爵士吉他爱好者。

**诞生故事**：报社的新闻编辑室需要在极短的截稿时间内上线数据库驱动的 Web 应用。Holovaty 和 Willison 受够了用 PHP 维护大型网站，发现了 Python，开始建一个内部框架（最初就叫"the CMS"）。它必须能快速开发内容密集、数据库驱动的新闻网站——所以从一开始就自带 ORM、Admin 后台、模板引擎、URL 路由，因为报社没时间让你一个一个挑选组件。

**解决的问题**：在截稿压力下快速构建完整的 Web 应用。不是为了程序员的选择自由，是为了**生产力**。

```python
# Django 不是几行代码能展示的，它是一整套项目结构
django-admin startproject myproject
```

### 哲学：精装房，拎包入住

Django 自带：

| 功能 | 说明 |
|------|------|
| ORM | 数据库模型定义、查询、迁移 |
| Admin 后台 | 自动生成管理界面 |
| 用户认证 | 注册、登录、权限、组 |
| 表单系统 | 验证、渲染、CSRF 防护 |
| 模板引擎 | Django Template Language |
| Session | 多种后端（数据库、缓存、文件） |
| 中间件 | 安全、CORS、压缩... |
| 命令行工具 | makemigrations、migrate、createsuperuser... |

### 发展历程

| 时间 | 里程碑 |
|------|--------|
| 2003 秋 | Lawrence Journal-World 内部开始开发 |
| 2005.7.13 | 公开发布，BSD 许可证 |
| 2008.6 | Django Software Foundation（DSF）成立 |
| 2008.9 | **Django 1.0**——首个稳定版 |
| 2014.9 | Django 1.7——**内置数据库迁移**（替代 South） |
| 2017.12 | **Django 2.0**——砍掉 Python 2 |
| 2019.12 | **Django 3.0**——加入 async 支持（view、middleware） |
| 2023.12 | Django 5.0 |

---

## FastAPI — 站在巨人肩膀上的后来者

**创建时间**：2018 年 12 月 5 日

**创建者**：Sebastian Ramirez（GitHub: tiangolo），哥伦比亚开发者，居住在柏林。

**诞生故事**：Ramirez 研究了市面上所有 Python Web 框架后发现一个矛盾——Flask 简单但没有数据校验和 API 文档；Django 全面但对纯 API 项目太重。而 2015-2016 年 Python 3.5/3.6 引入了 type hints，Pydantic 也出现了用类型注解做数据校验。Ramirez 把 Starlette（异步 Web 层）和 Pydantic（类型校验）组合起来，用 Python 类型提示同时驱动**参数校验 + API 文档生成 + 编辑器补全**。

**解决的问题**：写 API 时的重复劳动——手动写参数校验、手动写文档、手动写序列化。FastAPI 让你写一次类型声明，自动完成这三件事。

```python
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()

class User(BaseModel):
    name: str
    age: int

@app.post('/users')
async def create_user(user: User):    # 自动校验请求体
    return {'id': 1, **user.dict()}    # 自动生成文档
```

访问 `/docs` 就能看到 Swagger UI，直接在浏览器里测试 API。不用写一行文档代码。

### 哲学：类型即文档、类型即校验

FastAPI 的杀手锏：

| 特性 | Flask 怎么做 | FastAPI 怎么做 |
|------|------------|---------------|
| 参数校验 | 手动写 `if not request.json.get('name')` | 声明类型，自动校验 |
| API 文档 | 装 flask-swagger，手动维护 | 自动从类型生成 Swagger |
| 异步 | 2.0 才支持，非原生 | 原生 `async/await` |
| 编辑器补全 | 弱 | 强（类型驱动） |

### 发展历程

| 时间 | 里程碑 |
|------|--------|
| 2018.12 | v0.1.0 发布 |
| 2020-2022 | Uber、Netflix、Microsoft 等采用 |
| 2024 末 | GitHub Star 数超过 Flask（78.9k vs 68.4k） |
| 2025.12 | PyPI 下载量首次超过 Flask |
| 2026 | 成为新 Python API 项目的默认选择 |

---

## 总览对比

| | http.server | Flask | FastAPI | Django |
|--|-------------|-------|---------|--------|
| 诞生年份 | ~1997 | 2010 | 2018 | 2003/2005 |
| 创建者 | CPython 团队 | Armin Ronacher | Sebastian Ramirez | Holovaty & Willison |
| 诞生背景 | 标准库需要 HTTP 工具 | 愚人节玩笑 → 真框架 | 类型提示时代的产物 | 报社截稿压力 |
| 定位 | 文件服务器 | 微框架 | 现代 API 框架 | 全功能框架 |
| 协议 | 自己处理 | [WSGI](./wsgi-asgi.md) | [ASGI](./wsgi-asgi.md) | WSGI / ASGI |
| 应用服务器 | 自带（玩具级） | [Gunicorn](./gunicorn.md) | [Uvicorn](./uvicorn.md) | Gunicorn / Uvicorn |
| 自带功能 | 文件读取 | 路由 + 模板 | 路由 + 校验 + 文档 | 全家桶 |
| 异步 | 无 | 2.0 起部分支持 | 原生 | 3.0 起部分支持 |
| 学习曲线 | 低 | 低 | 低 | 中高 |

## 选型指南

```
临时传个文件
└─→ python -m http.server

几个简单的页面或接口，不想学太多
└─→ Flask

写 REST API，在意自动文档和类型校验
└─→ FastAPI

需要用户系统、Admin 后台、ORM、完整的 Web 应用
└─→ Django

不确定
└─→ 小项目 Flask，API 项目 FastAPI，大项目 Django
```

## 它们不是互斥的

同一个团队完全可以：
- 用 **Django** 做主站（用户系统、后台管理、内容管理）
- 用 **FastAPI** 做对外 API 服务（高性能、自动文档）
- 用 **Flask** 做内部小工具（快速原型、运维脚本的 Web 界面）

每个框架做自己最擅长的事——又是 [Unix 哲学](./unix-philosophy.md)。
