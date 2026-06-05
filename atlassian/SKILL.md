---
name: atlassian
description: >
  Atlassian (Jira + Confluence + Bitbucket) operations for Server / Data Center.
  Confluence pull/push with version-aware local cache (preserves macros, no
  markdown loss). Jira issue CRUD, JQL search, transitions, worklog, links.
  Bitbucket Server direct REST: PR list/diff/comment, branches, commits, file read.
  Plus Bitbucket reverse-lookup via Jira development panel.
  Auto-trigger when user asks to: read/edit Confluence pages (especially with
  macros/expand/code blocks), search Jira issues with JQL/CQL, transition
  Jira status, view/comment on Bitbucket PRs, read commit diffs, browse repo
  files, query linked PRs, work with debug/release reports in Confluence.
---

# Atlassian Skill (Jira + Confluence)

## 连接配置

- 配置文件：`~/.claude/skill-config/atlassian/config.env`（存 `JIRA_URL` / `JIRA_USER` / `CONFLUENCE_URL` / `CONFLUENCE_USER` / `CACHE_DIR`，非敏感）
- 凭据文件：`~/.netrc`（存密码/PAT，仅 `curl --netrc` 读取，**禁止明文**）
- 缓存目录：`<project-cwd>/.atlassian-cache/`（自动 `.gitignore`）
- 响应格式：JSON

### 脚本路径约定

```
# 安装位置（按优先级）：
# 1. 项目级: .claude/skills/atlassian/
# 2. 全局 Claude: ~/.claude/skills/atlassian/
# 3. Codex: ~/.codex/skills/atlassian/
# 4. 源码: skills/atlassian/
```

脚本清单（`$SKILL_DIR/scripts/`）：

| 脚本 | 用途 |
|------|------|
| `atl-credential.ps1` | **中文 GUI** 弹窗设置 URL / user / password（密码不经 AI；中文 label 从 `atl-credential-strings.zh-CN.txt` 加载） |
| `atl-credential-strings.zh-CN.txt` | 弹窗中文文案（UTF-8 LF；只动这个就能本地化） |
| `atl-query.ps1` | 通用 REST 调用（curl + .netrc + UTF-8 raw byte 输出，支持 jira/confluence/bitbucket 三种 service） |
| `atl-confluence.py` | Confluence 完整 CLI：pull/push/diff/cache + 页面 CRUD + 评论 + 附件 |
| `atl-jira.py` | Jira CLI：issue CRUD + transition + worklog + links + dev-info |
| `atl-bitbucket.py` | **Bitbucket Server CLI**：PR/diff/comment + branch/commit + browse/get-file |
| `atl-search.py` | JQL/CQL 搜索（中文安全的二步文件法） |

---

## 初始化（每次使用前必检查）

**第一步：检查配置**

```bash
powershell -ExecutionPolicy Bypass -File "$SKILL_DIR/scripts/atl-credential.ps1" -Action check
```

返回值：
- `CONFIGURED|JIRA=...|CONFLUENCE=...` → 配置已就绪
- `NOT_CONFIGURED` → 必须先 setup

**第二步：首次配置**

```bash
powershell -ExecutionPolicy Bypass -File "$SKILL_DIR/scripts/atl-credential.ps1" -Action setup
```

中文 GUI 弹窗包含三个分组：**Jira / Confluence / Bitbucket（可选）**。三项至少配置一项即可，其他留空跳过。

密码不经终端，AI 只看到 `OK|JIRA=...|CONFLUENCE=...|BITBUCKET=...`。

**增量更新**（已配置过 Jira/Confluence，现在只想加 Bitbucket）：
```bash
powershell -ExecutionPolicy Bypass -File "$SKILL_DIR/scripts/atl-credential.ps1" -Action update
```
- GUI 自动**预填**已配置的 URL + 用户名（密码框留空，因为 AI/工具不该读密码）
- 只在 **Bitbucket 分组**填新 URL + user + password
- 点确定后：Jira/Confluence 密码自动**复用 .netrc 已有条目**（无需重输），Bitbucket 写入新条目

`-Action delete`：清空所有配置（删 config.env + 删相关 .netrc 条目）

---

## 重要原则

- **修改操作（PUT/POST/DELETE）必须先向用户确认**
- **删除操作（delete-page / delete-issue）必须 `--yes` 显式确认**
- **禁止读取 `~/.netrc` 文件内容**
- **禁止调用本文档未列出的 API 端点**，未覆盖的需求告知用户
- Confluence 富格式页面**必须走 pull/push 流程**，不要用 markdown 直接更新

---

## ⚠ Windows 编码

- 所有文档为 UTF-8 无 BOM
- 所有 `.ps1` 脚本源码纯 ASCII（PowerShell 5.1 无 BOM 时按 GBK 解析中文会乱码）
- AI Agent 自己读文件不受影响
- 人手动用 PowerShell 查看时：`Get-Content -Encoding UTF8 <file>`

---

## Confluence 命令（核心：本地 HTML 缓存机制）

### 缓存机制

```
<project-cwd>/.atlassian-cache/
├── .gitignore                                  # 自动 "*"
└── confluence/
    └── <page-id>/
        ├── .meta.json                          # {latest_remote_version, title, ...}
        ├── v18.html                            # 历史版本快照
        ├── v19.html
        ├── v20.html                            # 最新拉取的远程版本（不要改）
        ├── v20.draft.html                      # 你的草稿（编辑这个）
        └── push.log                            # 推送历史
```

### 完整工作流（必读）

```
┌──────────────────────────────────────────────────────────────┐
│  pull  →  edit (Read+Edit on .draft.html)  →  diff  →  push │
└──────────────────────────────────────────────────────────────┘
```

### `pull` — 拉远程到缓存

```bash
python $SKILL_DIR/scripts/atl-confluence.py pull <page-id>
python $SKILL_DIR/scripts/atl-confluence.py pull <page-id> --version 18    # 历史版本
python $SKILL_DIR/scripts/atl-confluence.py pull <page-id> --force         # 强制覆盖本地
```

输出 `.atlassian-cache/confluence/<id>/v<N>.html` + `v<N>.draft.html` + `.meta.json`。

### `push` — 推草稿到远程（版本 +1）

```bash
python $SKILL_DIR/scripts/atl-confluence.py push <page-id>
python $SKILL_DIR/scripts/atl-confluence.py push <page-id> --draft <path>  # 用别的文件
python $SKILL_DIR/scripts/atl-confluence.py push <page-id> --force         # 远程被改了也强推
```

工作机制：
1. 读 `.meta.json` 拿 `cached_version`
2. **再次** GET 远程，校验版本未变
3. 一致 → PUT body, version+1
4. 成功 → 删 draft，写 `v<N+1>.html`，更新 meta

冲突时**默认拒绝推送**，输出三种解决方案。

### `diff` — 推送前看变更

```bash
python $SKILL_DIR/scripts/atl-confluence.py diff <page-id>
```

输出 unified diff（cached remote vs draft）。**push 前强烈建议必跑**。

### `cache-status` — 列缓存状态

```bash
python $SKILL_DIR/scripts/atl-confluence.py cache-status
python $SKILL_DIR/scripts/atl-confluence.py cache-status --page-id <id>
```

### `clear-cache` — 清缓存

```bash
python $SKILL_DIR/scripts/atl-confluence.py clear-cache --page-id <id>     # 单个
python $SKILL_DIR/scripts/atl-confluence.py clear-cache --yes              # 全清
```

`push.log` 永远保留。

### `get-page` — 直接读（不入缓存）

```bash
python $SKILL_DIR/scripts/atl-confluence.py get-page <id>                  # storage XHTML
python $SKILL_DIR/scripts/atl-confluence.py get-page <id> --format view    # 渲染后 HTML
python $SKILL_DIR/scripts/atl-confluence.py get-page <id> --json           # 完整 JSON
```

### `create-page` — 新建页面

```bash
python $SKILL_DIR/scripts/atl-confluence.py create-page \
    --space RDC --title "新页面" --parent 12345 --file my-content.html
```

### `search` — CQL 搜索

```bash
python $SKILL_DIR/scripts/atl-confluence.py search --cql 'space = "RDC" AND text ~ "压测"'
python $SKILL_DIR/scripts/atl-confluence.py search --cql '...' --limit 50 --json
```

或用 `atl-search cql '...'`（中文安全增强）。

### 其他 Confluence 命令

```bash
# 子页列表
python $SKILL_DIR/scripts/atl-confluence.py get-page-children <id>

# 版本历史
python $SKILL_DIR/scripts/atl-confluence.py get-page-history <id>

# 远程版本 diff
python $SKILL_DIR/scripts/atl-confluence.py get-page-diff <id> --from 18 --to 20

# 评论
python $SKILL_DIR/scripts/atl-confluence.py get-comments <id>
python $SKILL_DIR/scripts/atl-confluence.py add-comment <id> --text "评论内容"
python $SKILL_DIR/scripts/atl-confluence.py add-comment <id> --file comment.html

# 删除（破坏性，必须 --yes）
python $SKILL_DIR/scripts/atl-confluence.py delete-page <id> --yes

# 移动
python $SKILL_DIR/scripts/atl-confluence.py move-page <id> --parent <new-parent>

# 附件
python $SKILL_DIR/scripts/atl-confluence.py upload-attachment <id> --file ./report.pdf
python $SKILL_DIR/scripts/atl-confluence.py download-attachment <id> --filename report.pdf --out ./local.pdf
```

---

## Jira 命令

### `get-issue` — 读单个

```bash
python $SKILL_DIR/scripts/atl-jira.py get-issue PROJ-123
python $SKILL_DIR/scripts/atl-jira.py get-issue PROJ-123 --fields summary,status,customfield_10001
python $SKILL_DIR/scripts/atl-jira.py get-issue PROJ-123 --json
```

### `search` — JQL 搜索

```bash
python $SKILL_DIR/scripts/atl-jira.py search --jql 'project = PROJ AND status = "进行中"'
python $SKILL_DIR/scripts/atl-jira.py search --jql 'assignee = currentUser()' --limit 100
```

或用 `atl-search jql '...'`（中文安全 + 支持 `--format keys` 仅返回 KEY）。

JQL 模板见 `references/jql-cookbook.md`。

### `transitions` + `transition` — 流转状态

```bash
# 1. 列可用流转
python $SKILL_DIR/scripts/atl-jira.py transitions PROJ-123
# 输出：
#   ID    NAME              -> TARGET STATUS
#   31    Start Progress    -> In Progress
#   41    Resolve           -> Resolved

# 2. 执行
python $SKILL_DIR/scripts/atl-jira.py transition PROJ-123 --id 31
python $SKILL_DIR/scripts/atl-jira.py transition PROJ-123 --id 41 --comment "fixed in v2.5"
```

### `update` — 改字段

```bash
python $SKILL_DIR/scripts/atl-jira.py update PROJ-123 --field summary="新标题"
python $SKILL_DIR/scripts/atl-jira.py update PROJ-123 --field assignee=user1 --field priority=High
python $SKILL_DIR/scripts/atl-jira.py update PROJ-123 --field labels=regression,urgent
```

字段说明见 `references/jira-fields-reference.md`。

### `add-comment`

```bash
python $SKILL_DIR/scripts/atl-jira.py add-comment PROJ-123 --text "评论内容"
python $SKILL_DIR/scripts/atl-jira.py add-comment PROJ-123 --file comment.txt
```

### `create-issue` / `delete-issue`

```bash
python $SKILL_DIR/scripts/atl-jira.py create-issue \
    --project PROJ --type Bug --summary "标题" \
    --description "详细描述" \
    --assignee user1 --priority High --labels regression

# 删除（必须 --yes）
python $SKILL_DIR/scripts/atl-jira.py delete-issue PROJ-123 --yes
```

### `get-projects` / `get-project-issues`

```bash
python $SKILL_DIR/scripts/atl-jira.py get-projects
python $SKILL_DIR/scripts/atl-jira.py get-project-issues --key PROJ --limit 100
```

### `add-worklog` / `get-worklog`

```bash
# 加工时
python $SKILL_DIR/scripts/atl-jira.py add-worklog PROJ-123 --time-spent 1h --comment "code review"

# 读单个 issue 的工时明细 + 该 issue 的总和
python $SKILL_DIR/scripts/atl-jira.py get-worklog PROJ-123

# 聚合父任务 + 所有子任务的总工时（重要！）
python $SKILL_DIR/scripts/atl-jira.py get-worklog PROJ-123 --include-subtasks
```

> **⚠ Jira 工时语义关键点**：
> - **`get-issue --fields timetracking`** 返回的 `timetracking.timeSpent` 是**该 issue 自己的 worklog 聚合**，**不包含子任务**
> - **`get-worklog <KEY>`** 默认只读该 issue 自身的 worklog 明细
> - **看父+子任务总工时**必须用 `get-worklog <KEY> --include-subtasks`（自动遍历 subtasks 字段并求和）
> - `get-issue` 现在默认会列出 subtasks，看到有子任务时记得用 `--include-subtasks` 聚合

### `create-link` — Issue 关系

```bash
python $SKILL_DIR/scripts/atl-jira.py create-link PROJ-123 PROJ-456 --type "Relates"
python $SKILL_DIR/scripts/atl-jira.py create-link PROJ-789 PROJ-100 --type "Blocks"
```

### `move` — 子任务 reparent（含跨项目自动化）

**两种路径**：

| 场景 | 实现 |
|------|------|
| 同项目 reparent | REST: `PUT fields.parent` + 校验（要求 admin 把 parent 加到 Edit screen） |
| **跨项目 subtask move** | **9 步 web 表单自动化**（curl + .netrc + atl_token + cookie session） |

跨项目自动化原理：Jira Server REST 不直接支持，但 web UI 走的 9 步向导（ConvertSubTask × 3 + MoveIssue × 3 + ConvertIssue × 3）可以用 curl 模拟 form POST 完成。脚本自动处理：
1. CSRF token (`atl_token`) 提取与续传
2. wizard guid 跨步骤携带
3. Cookie session 共享
4. **fixVersion 自动从新父任务继承**（避免跨项目版本映射问题）
5. 每步 verify form action 已前进，否则 abort

```bash
# Dry-run（看计划，不动数据）
python $SKILL_DIR/scripts/atl-jira.py move SUBTASK-KEY --parent NEW-PARENT-KEY

# 实际执行
python $SKILL_DIR/scripts/atl-jira.py move SUBTASK-KEY --parent NEW-PARENT-KEY --yes
```

**实测案例**（FUDJSZ-515 → JXJYPXTYPT-27287）：
```
Phase 1/3: ConvertSubTask (subtask -> standard issue)...
  GET ConvertSubTask  guid=6
  -> advanced to: ConvertSubTaskUpdateFields.jspa
  -> advanced to: ConvertSubTaskConvert.jspa
  COMMITTED: now standard issue (still in FUDJSZ)
Phase 2/3: MoveIssue (cross-project move)...
  -> advanced to: MoveIssueUpdateFields.jspa
  -> advanced to: MoveIssueConfirm.jspa
  COMMITTED: moved to target project (key changed)
Phase 3/3: ConvertIssue (standard issue -> subtask of new parent)...
  -> advanced to: ConvertIssueUpdateFields.jspa
  -> advanced to: ConvertIssueConvert.jspa
  COMMITTED: converted back to subtask

OK moved FUDJSZ-515 -> JXJYPXTYPT-27287  (parent: FUDJSZ-477 -> JXJYPXTYPT-27282)
   project: FUDJSZ -> JXJYPXTYPT
```

5 秒完成，全部信息保留（assignee / status / created date / description / comments / worklog / attachments），key 自动变。

**已知限制**：
- 仅子任务跨项目移动；标准 issue 跨项目移动尚未实现（用 Web UI）
- 假设 source/target project **issuetype scheme 兼容**（多数实例如此）
- 假设 Jira 版本 7-9（web action URL 与你实例匹配；不同 Jira 版本表单字段名可能微调）
- 单条移动；批量请用 `move-helper` 走 Web UI Bulk Change

### `move-helper` — 跨项目批量迁移助手（备用）

如果 `move` 单条自动化遇到问题，或想 Web UI 一次性批量做：

```bash
python $SKILL_DIR/scripts/atl-jira.py move-helper FUDJSZ-477 --new-parent JXJYPXTYPT-27282
```

输出 Issue Navigator URL（自动选中所有子任务）+ Web UI Bulk Change 7 步操作指南。

### `get-dev-info` — Bitbucket / GitHub / GitLab 反查（**Bitbucket 唯一入口**）

```bash
python $SKILL_DIR/scripts/atl-jira.py get-dev-info PROJ-123
python $SKILL_DIR/scripts/atl-jira.py get-dev-info PROJ-123 --app-type stash --data-type pullrequest
python $SKILL_DIR/scripts/atl-jira.py get-dev-info PROJ-123 --json
```

返回关联的 PR / branch / commit / repository。详见 `references/bitbucket.md`。

---

## Bitbucket 命令（直连，atl-bitbucket.py）

支持 **Bitbucket Server / Data Center**（REST API v1.0）。Cloud 用户**不要**用本 skill。

### Repo 命名约定

所有 repo-scoped 命令用 `PROJECT/REPO` 单参数：

```bash
atl-bitbucket list-prs RDC/auth-service
atl-bitbucket get-pr RDC/auth-service 123
```

### 项目 / Repo 探索

```bash
python $SKILL_DIR/scripts/atl-bitbucket.py list-projects
python $SKILL_DIR/scripts/atl-bitbucket.py list-repos RDC
python $SKILL_DIR/scripts/atl-bitbucket.py list-branches RDC/auth-service [--filter develop]
python $SKILL_DIR/scripts/atl-bitbucket.py list-commits RDC/auth-service [--branch master]
python $SKILL_DIR/scripts/atl-bitbucket.py get-commit RDC/auth-service abc12345
```

### Pull Requests

```bash
# 列 PR
python $SKILL_DIR/scripts/atl-bitbucket.py list-prs RDC/auth-service [--state OPEN|MERGED|DECLINED|ALL]

# PR 详情
python $SKILL_DIR/scripts/atl-bitbucket.py get-pr RDC/auth-service 123

# PR diff（推荐写文件，不污染 context）
python $SKILL_DIR/scripts/atl-bitbucket.py get-pr-diff RDC/auth-service 123 --out pr-123.patch

# 文件变更列表
python $SKILL_DIR/scripts/atl-bitbucket.py get-pr-changes RDC/auth-service 123

# PR 评论 + 活动
python $SKILL_DIR/scripts/atl-bitbucket.py get-pr-activities RDC/auth-service 123

# 加 PR 评论
python $SKILL_DIR/scripts/atl-bitbucket.py add-pr-comment RDC/auth-service 123 --text "LGTM"
```

### 文件读取

```bash
# 列目录
python $SKILL_DIR/scripts/atl-bitbucket.py browse RDC/auth-service [--path src/main] [--at master]

# 读单文件（默认 stdout，大文件用 --out）
python $SKILL_DIR/scripts/atl-bitbucket.py get-file RDC/auth-service --path src/main/Foo.java
python $SKILL_DIR/scripts/atl-bitbucket.py get-file RDC/auth-service --path big.csv --out local.csv
```

### 直连 vs Jira 反查的选择

| 场景 | 推荐 |
|------|------|
| 已知 PR ID 看 diff/changes | **直连** |
| 浏览 repo 文件 / 读源码 | **直连** |
| 只知 Jira issue 找关联 PR | **反查** `atl-jira get-dev-info` |
| Bitbucket 没配凭据 | **反查** |
| 跨 issue 批量查 PR 状态 | **反查** + 解析 JSON |

详见 `references/bitbucket.md`。

---

## 搜索增强（中文安全）

`atl-search.py` 用 temp file 二步法绕开 PowerShell pipe 编码问题：

```bash
# JQL（含中文 summary 时用这个，不要用 atl-jira search 的管道）
python $SKILL_DIR/scripts/atl-search.py jql 'project = PROJ AND text ~ "压测"'
python $SKILL_DIR/scripts/atl-search.py jql 'assignee = currentUser()' --format keys

# CQL
python $SKILL_DIR/scripts/atl-search.py cql 'space = "RDC" AND title ~ "压测"'
python $SKILL_DIR/scripts/atl-search.py cql '...' --format ids
```

`--format keys` / `--format ids` 适合脚本管道（仅输出 KEY 或 page ID 列表）。

---

## 典型工作流

### 1. 编辑 Confluence 富格式页面（保留 macro）

```bash
# 1. 拉到本地
python $SKILL_DIR/scripts/atl-confluence.py pull 586252316

# 2. 用 Edit 工具改 .atlassian-cache/confluence/586252316/v20.draft.html
#    （AI 用 Read 看局部 + Edit 精确 search-replace）

# 3. 看变化
python $SKILL_DIR/scripts/atl-confluence.py diff 586252316

# 4. 用户确认后推送
python $SKILL_DIR/scripts/atl-confluence.py push 586252316
```

### 2. 处理 Jira issue 全流程

```bash
# 查
python $SKILL_DIR/scripts/atl-jira.py get-issue PROJ-123

# 评论
python $SKILL_DIR/scripts/atl-jira.py add-comment PROJ-123 --text "调查中"

# 流转
python $SKILL_DIR/scripts/atl-jira.py transitions PROJ-123
python $SKILL_DIR/scripts/atl-jira.py transition PROJ-123 --id 31

# 改字段
python $SKILL_DIR/scripts/atl-jira.py update PROJ-123 --field assignee=user1

# 工时
python $SKILL_DIR/scripts/atl-jira.py add-worklog PROJ-123 --time-spent 2h --comment "debug + fix"

# 关联 PR
python $SKILL_DIR/scripts/atl-jira.py get-dev-info PROJ-123
```

### 3. 跨 issue / 跨 PR 批量分析

```bash
# 找当前 sprint 我的所有 issue
python $SKILL_DIR/scripts/atl-search.py jql 'sprint in openSprints() AND assignee = currentUser()' --format keys > my_issues.txt

# 逐个查关联 PR
while read key; do
    echo "=== $key ==="
    python $SKILL_DIR/scripts/atl-jira.py get-dev-info "$key" --data-type pullrequest
done < my_issues.txt
```

### 4. 写压测/release 报告到 Confluence

```bash
# 1. 拉模板页
python $SKILL_DIR/scripts/atl-confluence.py pull 586252316

# 2. AI 在 v20.draft.html 里替换占位符（保留 ac:macro / ac:expand / 表格）

# 3. 推送
python $SKILL_DIR/scripts/atl-confluence.py diff 586252316
python $SKILL_DIR/scripts/atl-confluence.py push 586252316
```

---

## 命令速查

### Confluence（17 个）

| 命令 | 用途 |
|------|------|
| `pull <id> [--version N] [--force]` | 拉到缓存 |
| `push <id> [--draft P] [--force]` | 推草稿 |
| `diff <id>` | 缓存 vs 草稿 |
| `cache-status [--page-id ID]` | 列缓存 |
| `clear-cache [--page-id ID] [--yes]` | 清缓存 |
| `get-page <id> [--format storage\|view] [--json]` | 直接读 |
| `create-page --space K --title T --file F [--parent P]` | 建页 |
| `search --cql 'CQL' [--limit N] [--json]` | CQL 搜索 |
| `get-page-children <id>` | 子页列表 |
| `get-page-history <id>` | 版本历史 |
| `get-page-diff <id> --from V --to V` | 远程版本 diff |
| `get-comments <id>` | 列评论 |
| `add-comment <id> --text T` | 加评论 |
| `delete-page <id> --yes` | 删页 |
| `move-page <id> --parent P` | 移动 |
| `upload-attachment <id> --file F` | 上传附件 |
| `download-attachment <id> --filename N` | 下载附件 |

### Jira（16 个）

| 命令 | 用途 |
|------|------|
| `get-issue <KEY> [--fields ...]` | 读 issue |
| `search --jql 'JQL'` | JQL 搜索 |
| `add-comment <KEY> --text T` | 加评论 |
| `transitions <KEY>` | 列流转 |
| `transition <KEY> --id ID [--comment]` | 执行流转 |
| `update <KEY> --field name=value ...` | 改字段 |
| `create-issue --project --type --summary ...` | 建 issue |
| `delete-issue <KEY> --yes` | 删 issue |
| `get-projects` | 列项目 |
| `get-project-issues --key K` | 项目 issue |
| `add-worklog <KEY> --time-spent` | 加工时 |
| `get-worklog <KEY> [--include-subtasks]` | 读工时；`--include-subtasks` 聚合父+子任务总和 |
| `create-link <FROM> <TO> --type` | 建关系 |
| `move <KEY> --parent NEW [--yes]` | subtask reparent（跨项目走 9 步 web wizard 自动化） |
| `move-helper <PARENT> [--new-parent NP]` | 备用：生成 Bulk Change URL 走 Web UI 批量 |
| `get-dev-info <KEY>` | Bitbucket 反查（间接） |

### Bitbucket（13 个）

| 命令 | 用途 |
|------|------|
| `list-projects` | 列项目 |
| `list-repos PROJECT` | repo 列表 |
| `list-prs PROJECT/REPO [--state ...]` | PR 列表 |
| `get-pr PROJECT/REPO PR_ID` | PR 详情 |
| `get-pr-diff PROJECT/REPO PR_ID --out F` | PR diff（写文件） |
| `get-pr-changes PROJECT/REPO PR_ID` | 文件变更列表 |
| `get-pr-activities PROJECT/REPO PR_ID` | PR 评论 + 活动 |
| `add-pr-comment PROJECT/REPO PR_ID --text T` | 加 PR 评论 |
| `list-branches PROJECT/REPO [--filter F]` | branch 列表 |
| `list-commits PROJECT/REPO [--branch B]` | commit 列表 |
| `get-commit PROJECT/REPO SHA` | commit 详情 |
| `browse PROJECT/REPO [--path P] [--at REF]` | 列目录 |
| `get-file PROJECT/REPO --path P [--out F]` | 读文件 |

### 搜索（2 个）

| 命令 | 用途 |
|------|------|
| `atl-search.py jql 'JQL' [--format keys]` | JQL 中文安全 |
| `atl-search.py cql 'CQL' [--format ids]` | CQL 中文安全 |

---

## 参考文档

- `references/confluence-html-workflow.md` — pull/push 完整流程 + 缓存机制
- `references/confluence-storage-format.md` — XHTML / macro 速查
- `references/jql-cookbook.md` — 常用 JQL 30+ 模板
- `references/cql-cookbook.md` — 常用 CQL 模板
- `references/jira-fields-reference.md` — 字段 / issuetype / priority / link types
- `references/bitbucket.md` — Bitbucket 直连 CLI + Jira 反查 + REST 端点速查

---

## 与 mcp-atlassian 对比

本 skill 复刻 mcp-atlassian 的 Tier 1+2 核心能力（约 32 个命令）+ Bitbucket Server 直连 13 个（mcp-atlassian 完全没有），保留 95%+ 实际场景。**舍弃**的 ~40 个工具：
- Sprint / 看板（7 个）
- Service Desk（3 个）
- ProForma 表单（3 个）
- batch_* 系列（4 个）
- Watcher（3 个）
- 各种字段元信息查询（field options / link types / project components 等）
- 重叠的小众端点（issue dates / SLA / page views 等）

**改进**的 Confluence：
- 默认 storage 直传，**不再用 markdown 转换**（保留 macro）
- 本地 HTML 缓存 + 版本号管理（多轮编辑省 token）
- 推送前强校验远程版本（防覆盖）
- 大内容（30KB+）无限制
