# Confluence 本地 HTML 推送工作流

> 来源：综合 `D:\work\demos\data\stress-testing\gszj\confluence-report-template.md §6` 实战 + 本 skill 的缓存设计。

## 为什么不直接用 markdown

Confluence 默认 API 接受 markdown 时会经服务端 markdown→storage 转换，**会丢失 `ac:macro` / `expand` / `code-block` 等富格式元素**。

实测对比同一个含 `<ac:structured-macro>` 的 30KB 页面：

| 方式 | 富格式保真 | 大小限制 | Token 消耗 |
|------|-----------|---------|-----------|
| MCP markdown 模式 | ❌ 丢 macro | ⚠️ MCP 限制 | HTML 进 context |
| MCP storage 模式 | ✅ | ⚠️ 受限 | HTML 进 context |
| **本 skill: pull → 编辑 → push** | ✅ | ✅ 无限 | **0**（读本地文件） |

## 完整工作流

### 第一次接触某个页面

```bash
atl-confluence pull 586252316
```

输出：
```
Fetching page 586252316...
OK fetched v20 -> .atlassian-cache/confluence/586252316/v20.html (31245 chars)
OK draft created: .atlassian-cache/confluence/586252316/v20.draft.html

Next: edit v20.draft.html, then 'atl-confluence diff 586252316' before push.
```

缓存目录结构：
```
.atlassian-cache/
├── .gitignore                          # 自动写入 "*"
└── confluence/
    └── 586252316/
        ├── .meta.json                  # {page_id, title, latest_remote_version, ...}
        ├── v20.html                    # 远程 v20 的快照（不要改）
        └── v20.draft.html              # 你的草稿（编辑这个）
```

### 编辑

AI Agent 用 Read / Edit 工具直接操作 `v20.draft.html`：
- AI 不需要 cat 整个文件到 context（按需 line range）
- Edit 工具用 search-replace 精确改

人类用任意编辑器：
```bash
code .atlassian-cache/confluence/586252316/v20.draft.html
```

### 推送前 diff

```bash
atl-confluence diff 586252316
```

输出 unified diff（cached remote v20 vs draft）。能看清你改了什么。

### 推送

```bash
atl-confluence push 586252316
```

工作机制：
1. 读 `.meta.json` 拿 `cached_version=20`
2. **再次** GET 远程版本，校验仍是 v20
3. 一致 → PUT body, version=21
4. 成功 → 删 draft，写 `v21.html`，更新 .meta.json

### 冲突场景

如果在你 pull 之后、push 之前别人改了页面：

```
ERROR: remote at v22, your cache at v20.
Your draft is based on outdated version.
Options:
  1. atl-confluence pull 586252316 --force          # discard local, refetch latest
  2. atl-confluence pull 586252316 --version 22     # add v22 to cache, manually merge draft
  3. atl-confluence push 586252316 --force          # force push (overwrites remote v22)
```

**默认拒绝推送**，避免覆盖别人。

### 清理

```bash
# 单个页面
atl-confluence clear-cache --page-id 586252316

# 全清（保险起见要 --yes）
atl-confluence clear-cache --yes
```

`push.log` 永远保留（记录历史推送动作）。

### 查看缓存状态

```bash
atl-confluence cache-status
```

输出：
```
PAGE-ID         VERSION  TITLE                                    DRAFT    FETCHED-AT             BY
--------------------------------------------------------------------------------------------------------------
586252316       v20      压测性能分析【注册，第3轮】              Yes      2026-04-27T10:00:00Z   claude
  versions: [18, 19, 20]
586252320       v15      每轮压测性能分析（父页）                 -        2026-04-26T15:30:00Z   codex
  versions: [15]
```

## 多 Agent 协作场景

**场景**：Claude 改完 push 了 v21，Codex 接着改。

```bash
# Codex
atl-confluence pull 586252316       # 拉到 v21（识别到 cache 是 v20，远程已是 v21）
# → cache 更新为 v21.html + v21.draft.html
# 编辑 v21.draft.html
atl-confluence diff 586252316
atl-confluence push 586252316       # 校验远程仍 v21 → PUT v22 成功
```

历史版本本地保留：`v18.html v19.html v20.html v21.html v22.html` 都在。

## Worktree 处理

每个 git worktree 是独立 cwd，独立 cache：

```
project-root/
  .atlassian-cache/                 # 主分支的缓存
worktrees/feature-x/
  .atlassian-cache/                 # feature-x 分支独立缓存
```

不冲突。如果想共享，用 `--cache-dir` 指向同一目录或在 `config.env` 设 `CACHE_DIR`。

## Token 优化要点（写给 AI 用的）

```
✅ DO:
- pull 后用 Read 工具 + line range 看局部
- 用 Edit 工具 search-replace 精确改
- diff 看变化，push 前必做
- 失败重试直接 push（draft 还在）

❌ DON'T:
- 不要把整个 .draft.html 内容打印到对话
- 不要用 Write 全文重写（用 Edit 局部改）
- 不要靠记忆改，先 Read 拿到当前状态
- 不要直接调 confluence_update_page 这类 MCP 工具（绕过缓存机制）
```

## 与 MCP 工具的对比

| 操作 | MCP 工具 | 本 skill |
|------|---------|---------|
| 读小页 | `confluence_get_page` ✓ | `atl-confluence get-page <id>` |
| 改大页 富格式 | ❌ markdown 毁 macro | ✅ pull → edit `.html` → push |
| 多轮编辑 | 每轮全文进 context | ✅ 本地文件，0 token |
| 冲突防护 | 无 | ✅ 推送前强校验版本 |
| 历史回滚 | 需 history API | ✅ `cp v18.html v22.draft.html && push` |
| 跨 agent 协作 | 各自全文 | ✅ 共享 .atlassian-cache/ |
