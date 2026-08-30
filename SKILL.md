---
name: wechat-article-extract
description: 基于 Windows 客户端渲染层内存 DOM 解析技术，将正在阅读的公众号文章提取并转换为结构化 Markdown 离线文档。当用户需要离线备份、笔记整理或结构化导出已打开的微信文章时使用本 Skill。
license: MIT
compatibility: Windows, Python 3.8+, WeChat desktop client
metadata:
  version: "1.0.0"
---

# 微信公众号文章本地内存结构化提取 (wechat-article-extract)

本 Skill 专门面向 AI Agent 设计，基于**客户端渲染层内存 DOM 分析技术（In-Memory DOM Extraction）**，提供确定性、高保真、跨语言的本地已打开文章离线整理与 Markdown 解析标准作业程序（SOP）。解析结果默认自动保存至独立的 `./output/` 文件夹。

---

## 🤖 Agent 标准操作流程（SOP）

当用户请求整理、归档或提取当前已在微信中打开的文章时，Agent 请按以下步骤执行：

### Step 1: 扫描已打开的文章（结构化探测）
在终端运行：
```bash
python scripts/wechat_article_extract.py --list --json
```
* **输出**：返回包含所有当前内存中真实已渲染文章的 JSON 数组（按打开时间**由新到旧**排序，含 `title`, `account`, `author`, `pid`, `char_count`, `preview`）。
* **自动过滤机制**：底层自动剔除 Chromium 预加载的空模板（`content_noencode.DATA` 等噪点），通过向前回溯 `#activity-name` 捕获真实主标题，并完成跨进程指纹去重。

### Step 2: 目标匹配与提取
* **场景 A：用户未指定具体文章 / 提取最新打开的文章**：
  直接执行无参数命令（默认解析时间上最新打开的第 1 篇文章并输出至 `./output/`）：
  ```bash
  python scripts/wechat_article_extract.py
  ```
* **场景 B：用户指定了特定文章（如提供了 URL、标题关键词、公众号名称）**：
  带目标关键词精准匹配提取：
  ```bash
  python scripts/wechat_article_extract.py "目标关键词"
  ```
* **场景 C：用户要求批量整理当前打开的全部文章**：
  ```bash
  python scripts/wechat_article_extract.py --all
  ```

### Step 3: 返回与交付
* 提取出的 Markdown 文档默认保存在 `./output/` 文件夹（或 `--output-dir` 自定义指定目录）。
* 向用户反馈文章元信息（标题、公众号、字数、提取时间）及生成的 Markdown 文件路径（如 `output/xxxx.md`）。

---

## 🛠️ CLI 接口规范

| 命令 / 参数 | 说明 | Agent 适用场景 |
|---|---|---|
| `--list --json` | 以 JSON 格式输出当前内存中所有打开的文章列表（时间由新到旧） | 用于 Agent 探测与做决策 |
| `--list` | 打印人类可读的文章列表及预览 | 人类交互调试 |
| `--all` | 批量解析并保存内存中打开的所有文章至 `./output/` | 批量整理多标签页文章 |
| `"<target>"` | 根据 URL、标题、公众号或正文关键词精准过滤提取某一篇 | 用户提供了明确关键词时 |
| 无参数 | 默认解析最新打开（最顶层）的有效文章至 `./output/` | 默认快速提取 |
| `--output-dir` | 指定输出目录（**默认 `./output/`**） | 需要自定义保存目录时 |

---

## 💡 核心机制与技术原理

1. **独立输出隔离**：
   默认将解析后的 Markdown 文件保存在 `./output/` 文件夹，自动创建目录，保持工程工作区整洁。
2. **真实主标题与元数据回溯**：
   通过向前回溯内存切片，将位于 `#js_content` 上方的 `<h1 id="activity-name">`、`#js_name`（公众号）与 `#js_author_name`（作者）完整捕获，确保元数据准确。
3. **多语言与代码混排支持**：
   全面支持中文、英文、符号及代码块，自动统计有效字符数。
4. **确定性模板过滤与时间倒序排序**：
   自动排除 Chromium 预加载的空模板；按渲染进程 `StartTime` 时间倒序排列，确保首选目标永远是用户最新打开的页面。
5. **排版与媒体保真**：
   保留 H1~H4 标题层级、代码块（`pre/code`）、图片引用直链（`mmbiz.qpic.cn`）并自动清洗底部广告与微信 UI 组件。
