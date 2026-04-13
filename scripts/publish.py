#!/usr/bin/env python3
"""
DevDocs → Blog 同步脚本

扫描 DevDocs 仓库中的 Markdown 文章，自动创建/更新到博客 API。

用法:
    python scripts/publish.py --url https://www.lzqqq.org
    python scripts/publish.py --url http://127.0.0.1:8000
    python scripts/publish.py --url https://www.lzqqq.org --dry-run
"""

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path

import urllib.request
import urllib.error
import urllib.parse

REPO_ROOT = Path(__file__).resolve().parent.parent
STATE_FILE = REPO_ROOT / ".blog-state.json"

# 跳过的文件
SKIP_FILES = {"README.md"}


# ─── HTTP helpers ────────────────────────────────────────────────

def api_request(url, method="GET", data=None, token=None):
    """发送 HTTP 请求，返回 JSON 响应"""
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "DevDocs-Publisher/1.0",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            resp_data = resp.read().decode()
            if not resp_data:
                return {}
            return json.loads(resp_data)
    except urllib.error.HTTPError as e:
        error_body = e.read().decode()
        print(f"  API error {e.code}: {error_body[:200]}")
        raise


def login(base_url, username, password):
    """获取 chef token"""
    data = {"username": username, "password": password}
    resp = api_request(f"{base_url}/api/chef/login/", method="POST", data=data)
    if resp.get("success"):
        return resp["token"]
    raise RuntimeError(f"Login failed: {resp}")


# ─── Markdown 解析 ───────────────────────────────────────────────

def parse_markdown(filepath):
    """从 .md 文件提取 title, summary, content"""
    text = filepath.read_text(encoding="utf-8")

    # 提取标题：第一个 # 开头的行
    title = None
    for line in text.splitlines():
        m = re.match(r"^#\s+(.+)$", line)
        if m:
            title = m.group(1).strip()
            break

    if not title:
        return None

    # 提取 summary：跳过标题、导航行、子标题、代码块，取第一段正文
    summary = ""
    in_body = False
    in_code_block = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code_block = not in_code_block
            continue
        if in_code_block:
            continue
        if stripped.startswith("#"):
            if in_body and summary:
                break
            continue
        if stripped.startswith("> "):
            continue
        if stripped.startswith("|"):
            continue
        if not stripped:
            if in_body and summary:
                break
            continue
        # 清理 markdown 链接语法 [text](url) → text
        clean = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', stripped)
        # 清理加粗/斜体
        clean = re.sub(r'\*\*([^*]+)\*\*', r'\1', clean)
        clean = re.sub(r'\*([^*]+)\*', r'\1', clean)
        in_body = True
        summary += clean + " "

    summary = summary.strip()[:200]

    # 处理内部链接：./xxx.md → /blog/slug（由同目录其他文件的 slug 决定）
    # 先收集同目录文件的 title→slug 映射，在 sync 阶段处理
    # 这里先清理导航行（> 回到 [总览]... 这行对博客读者没用）
    lines = text.splitlines()
    cleaned_lines = []
    for line in lines:
        if line.strip().startswith("> 回到"):
            continue
        cleaned_lines.append(line)
    cleaned_content = "\n".join(cleaned_lines)

    content_hash = hashlib.sha256(text.encode()).hexdigest()

    return {
        "title": title,
        "summary": summary,
        "content": cleaned_content,
        "content_hash": content_hash,
    }


# ─── Category / Tag 管理 ────────────────────────────────────────

def folder_to_display_name(folder_name):
    """web-server-architecture → Web Server Architecture"""
    return folder_name.replace("-", " ").title()


def ensure_category(base_url, token, folder_name):
    """确保 category 存在，返回 category id"""
    resp = api_request(f"{base_url}/api/blog/categories/", token=token)
    display_name = folder_to_display_name(folder_name)

    for cat in resp:
        if cat["slug"] == folder_name or cat["name"] == display_name:
            return cat["id"]

    # 创建新分类
    data = {"name": display_name}
    cat = api_request(f"{base_url}/api/blog/categories/", method="POST", data=data, token=token)
    print(f"  Created category: {display_name} (id={cat['id']})")
    return cat["id"]


def ensure_tag(base_url, token, tag_name):
    """确保 tag 存在，返回 tag id"""
    resp = api_request(f"{base_url}/api/blog/tags/", token=token)

    for tag in resp:
        if tag["name"] == tag_name:
            return tag["id"]

    # 创建新 tag
    data = {"name": tag_name}
    tag = api_request(f"{base_url}/api/blog/tags/", method="POST", data=data, token=token)
    print(f"  Created tag: {tag_name} (id={tag['id']})")
    return tag["id"]


# ─── 状态管理 ────────────────────────────────────────────────────

def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n")


# ─── 扫描与同步 ─────────────────────────────────────────────────

def scan_articles():
    """扫描所有 .md 文件（跳过 README.md）"""
    articles = []
    for md_file in sorted(REPO_ROOT.rglob("*.md")):
        if md_file.name in SKIP_FILES:
            continue
        if md_file.parent == REPO_ROOT:
            continue  # 跳过根目录的非 README 文件（如 .gitignore 等不可能出现的 .md）
        # scripts/ 目录跳过
        rel = md_file.relative_to(REPO_ROOT)
        if str(rel).startswith("scripts"):
            continue

        articles.append(md_file)
    return articles


def convert_internal_links(content, slug_map):
    """将 ./xxx.md 链接转为 /blog/{slug} 内链"""
    def replace_link(m):
        text = m.group(1)
        filename = m.group(2)
        if filename in slug_map:
            return f"[{text}](/blog/{slug_map[filename]})"
        return text  # 找不到映射就只保留文本

    return re.sub(r'\[([^\]]+)\]\(\./([^)]+\.md)(?:#[^)]*)?\)', replace_link, content)


def build_slug_map(articles):
    """构建 filename → slug 映射（slug = slugify(title)）"""
    from urllib.parse import quote
    slug_map = {}
    for filepath in articles:
        parsed = parse_markdown(filepath)
        if not parsed:
            continue
        title = parsed["title"]
        # Django slugify with allow_unicode
        slug = re.sub(r'[^\w\s-]', '', title.lower()).strip()
        slug = re.sub(r'[-\s]+', '-', slug)
        slug_map[filepath.name] = quote(slug)
    return slug_map


def sync_article(base_url, token, filepath, state, slug_map, dry_run=False):
    """同步单篇文章"""
    rel_path = str(filepath.relative_to(REPO_ROOT))
    folder_name = filepath.parent.name

    parsed = parse_markdown(filepath)
    if not parsed:
        print(f"  SKIP {rel_path} (no title found)")
        return

    # 转换内部链接
    parsed["content"] = convert_internal_links(parsed["content"], slug_map)

    existing = state.get(rel_path)

    # 内容没变 → 跳过
    if existing and existing.get("content_hash") == parsed["content_hash"]:
        print(f"  UNCHANGED {rel_path}")
        return

    # 确保 category 和 tag
    if not dry_run:
        category_id = ensure_category(base_url, token, folder_name)
        tag_name = folder_to_display_name(folder_name)
        tag_id = ensure_tag(base_url, token, tag_name)

    if existing and existing.get("post_id"):
        # 更新已有文章
        action = "UPDATE"
        if not dry_run:
            post_id = existing["post_id"]
            data = {
                "title": parsed["title"],
                "summary": parsed["summary"],
                "content": parsed["content"],
                "category_id": category_id,
                "tag_ids": [tag_id],
                "is_published": True,
            }
            api_request(f"{base_url}/api/blog/posts/{post_id}/", method="PATCH", data=data, token=token)
            state[rel_path] = {"post_id": post_id, "content_hash": parsed["content_hash"]}
    else:
        # 创建新文章
        action = "CREATE"
        if not dry_run:
            data = {
                "title": parsed["title"],
                "summary": parsed["summary"],
                "content": parsed["content"],
                "category_id": category_id,
                "tag_ids": [tag_id],
                "is_published": True,
            }
            resp = api_request(f"{base_url}/api/blog/posts/", method="POST", data=data, token=token)
            state[rel_path] = {"post_id": resp["id"], "content_hash": parsed["content_hash"]}

    print(f"  {action} {rel_path} → {parsed['title']}")


# ─── Main ────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Sync DevDocs articles to blog")
    parser.add_argument("--url", default=os.environ.get("BLOG_URL", "http://127.0.0.1:8000"),
                        help="Blog API base URL")
    parser.add_argument("--username", default=os.environ.get("CHEF_USERNAME", "chef"))
    parser.add_argument("--password", default=os.environ.get("CHEF_PASSWORD", "kitchen123"))
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without executing")
    args = parser.parse_args()

    base_url = args.url.rstrip("/")
    print(f"Target: {base_url}")
    print(f"Dry run: {args.dry_run}")
    print()

    # 登录
    token = None
    if not args.dry_run:
        print("Logging in...")
        token = login(base_url, args.username, args.password)
        print(f"  Token: {token[:8]}...")
        print()

    # 扫描文章
    articles = scan_articles()
    print(f"Found {len(articles)} articles")
    print()

    # 加载状态
    state = load_state()

    # 构建内部链接映射
    slug_map = build_slug_map(articles)

    # 同步
    created = 0
    updated = 0
    unchanged = 0

    for filepath in articles:
        rel_path = str(filepath.relative_to(REPO_ROOT))
        existing = state.get(rel_path)
        parsed = parse_markdown(filepath)
        if not parsed:
            continue

        if existing and existing.get("content_hash") == parsed["content_hash"]:
            unchanged += 1
            print(f"  UNCHANGED {rel_path}")
            continue

        if existing and existing.get("post_id"):
            updated += 1
        else:
            created += 1

        sync_article(base_url, token, filepath, state, slug_map, args.dry_run)

    # 保存状态
    if not args.dry_run:
        save_state(state)

    print()
    print(f"Done: {created} created, {updated} updated, {unchanged} unchanged")


if __name__ == "__main__":
    main()
