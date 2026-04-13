# 知识有向图设计方案

## 背景

博客文章之间存在大量交叉引用（如 Nginx 文章引用 Gunicorn、Django 文章引用 Celery），传统的卡片/列表视图无法体现这种知识关联。知识有向图将文章作为节点、引用关系作为有向边，让读者直观看到知识体系的结构。

## 效果

```
         ┌──────────┐
    ┌────│  Nginx   │────┐
    │    └──────────┘    │
    ▼                    ▼
┌────────┐        ┌──────────┐         ┌────────────┐
│Gunicorn│───────→│  Django  │────────→│Redis/Celery│
└────────┘        └──────────┘         └────────────┘
    │                  │
    ▼                  ▼
┌────────┐        ┌──────────┐
│Uvicorn │        │WSGI/ASGI │
└────────┘        └──────────┘
                       │
                       ▼
                ┌────────────┐
                │ Unix 哲学   │
                └────────────┘
```

- 每个圆形节点 = 一篇文章
- 有向箭头 = A 文章引用了 B 文章
- 点击节点直接跳转到文章
- 支持拖拽、缩放、hover 预览

## 架构

### 数据流

```
Markdown 文章
    │
    │ publish.py 同步时自动解析 [text](/blog/slug) 内链
    ▼
Django API: GET /api/blog/posts/graph/?category=xxx
    │
    │ 返回 { nodes: [...], edges: [...] }
    ▼
Vue 前端 BlogListView.vue
    │
    │ 传递 nodes + edges
    ▼
KnowledgeGraph.vue（D3.js 力导向图）
    │
    └→ SVG 渲染 + 交互
```

### 边的数据来源

两种来源，合并去重：

1. **自动提取**（主要来源）：后端 `graph()` API 解析每篇文章 Markdown 内容中的 `/blog/{slug}` 链接，自动生成有向边
2. **手动关联**（补充）：BlogPost 模型的 `related_posts` M2M 字段，可在 Admin 后台或 API 手动添加

### 节点显示名规则

文章标题格式约定为 `专有名词：副标题`（如 "Nginx：守门人与调度员"），图谱中只显示冒号前的专有名词。

优先级：
1. `short_title` 字段（后端预留，未来可自定义）
2. 标题冒号前的文字
3. 完整标题（无冒号时）

### 节点大小

按显示文字长度自适应。CJK 字符算 2 宽度单位，ASCII 算 1：

```javascript
const textWidth = [...name].reduce((w, c) =>
  w + (/[\u4e00-\u9fff]/.test(c) ? 2 : 1), 0
)
const radius = Math.max(36, textWidth * 5 + 20)
```

## 技术选型

| 组件 | 选型 | 原因 |
|------|------|------|
| 图渲染 | D3.js v7 | 最成熟的数据可视化库，力导向布局算法完善 |
| 布局算法 | `d3-force` | 力导向自动布局，节点自动散开避免重叠 |
| 交互 | `d3-zoom` + `d3-drag` | 缩放平移 + 节点拖拽 |
| 渲染 | SVG | 矢量清晰，DOM 事件方便绑定 |

力模拟参数：
```javascript
forceLink:     distance=180, strength=0.4   // 连线弹簧
forceManyBody: strength=-800                // 节点斥力
forceCollide:  radius=nodeRadius+15         // 碰撞检测
forceCenter:   画布中心                      // 居中引力
```

## API 设计

### `GET /api/blog/posts/graph/`

**参数**：
- `category` (可选)：按分类 slug 过滤

**响应**：
```json
{
  "nodes": [
    {
      "id": 1,
      "title": "Nginx：守门人与调度员",
      "slug": "nginx守门人与调度员",
      "summary": "Nginx 是一个反向代理服务器...",
      "reading_time": 8,
      "view_count": 42
    }
  ],
  "edges": [
    { "source": 1, "target": 2 },
    { "source": 1, "target": 3 }
  ]
}
```

**边提取逻辑**（后端 Python）：
```python
# 从 Markdown content 中正则匹配内链
for match in re.finditer(r'\(/blog/([^)]+)\)', post.content):
    target_slug = unquote(match.group(1))
    if target_slug in slug_to_id:
        edges.add((post.id, slug_to_id[target_slug]))

# 合并手动关联
for related in post.related_posts.filter(is_published=True):
    edges.add((post.id, related.id))
```

## 前端组件

### KnowledgeGraph.vue

**Props**：
| Prop | 类型 | 说明 |
|------|------|------|
| `nodes` | `Array` | 节点数组 |
| `edges` | `Array` | 边数组 `{source, target}` |
| `isDarkTheme` | `Boolean` | 主题 |

**交互**：
| 操作 | 行为 |
|------|------|
| 点击节点 | `router.push('/blog/{slug}')` 跳转文章 |
| 拖拽节点 | 力模拟重新计算布局 |
| hover 节点 | 高亮关联边 + tooltip（标题、摘要、阅读时间） |
| 滚轮 | 缩放（0.3x - 3x） |
| 拖拽空白 | 平移画布 |

**主题样式**：

| 元素 | Dark | Light |
|------|------|-------|
| 节点填充 | `#1e1e2e` | `#ffffff` |
| 节点边框 | `#6366f1` (violet) | `#cbd5e1` (slate) |
| 节点文字 | `#e2e8f0` | `#1e293b` |
| 连线 | `#334155` | `#e2e8f0` |
| hover 高亮 | violet | slate-dark |

## 视图切换

博客列表页（打开文件夹后）提供两种视图：

```
[图谱图标] [列表图标]     ← 右上角切换按钮
```

- **图谱视图**（默认）：D3 力导向图
- **列表视图**：保留原有的序号列表

视图偏好存储在 `localStorage('blog_view_mode')`。

## 文件清单

| 文件 | 角色 |
|------|------|
| `backend/api/models.py` | `BlogPost.related_posts` M2M 字段 |
| `backend/api/views.py` | `BlogPostViewSet.graph()` action |
| `frontend/src/components/blog/KnowledgeGraph.vue` | D3 图组件 |
| `frontend/src/views/BlogListView.vue` | 视图切换集成 |

## 扩展方向

- **short_title 字段**：后端加字段，允许自定义节点显示名（前端已预留读取逻辑）
- **边权重**：可以按引用次数加权，连线粗细不同
- **节点颜色编码**：按阅读量/创建时间/分类着不同颜色
- **跨分类图谱**：去掉 category 过滤，展示全站知识关联
- **搜索高亮**：搜索关键词时，匹配的节点高亮放大
- **迷你地图**：大量节点时，右下角显示缩略全景图
