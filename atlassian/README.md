# Atlassian Skill (Jira + Confluence + Bitbucket)

让 AI Agent 操作 Atlassian Server / Data Center 全家桶（Jira + Confluence + Bitbucket Server）。基于 mcp-atlassian 复刻 Tier 1+2 核心能力 + 补 Bitbucket 直连（mcp-atlassian 没有）。**Confluence 改用本地 HTML 缓存 + 版本号管理**，富格式不丢、多轮编辑省 token。

## 核心特性

- **Confluence 富格式保真**：默认 storage XHTML 直传，不走 markdown 转换，`<ac:macro>` / `<ac:expand>` / `<ac:code>` 等元素不丢失
- **本地 HTML 缓存**：`<project-cwd>/.atlassian-cache/`，版本号对齐 confluence，支持历史版本保留 + 跨 agent 协作
- **推送前强校验**：push 时再次 GET 远程版本，未变才允许 PUT，**防止覆盖别人的改动**
- **凭据隔离 + 中文 GUI**：URL/user 在 config.env，密码/PAT 在 `~/.netrc`，**AI 全程不接触密码**；setup 弹窗中文界面（label 从外部 UTF-8 文件加载，绕开 PS 5.1 源码编码问题）
- **中文安全搜索**：`atl-search.py` 用 temp file 二步法绕开 PowerShell pipe 编码问题
- **Bitbucket Server 直连**：`atl-bitbucket.py` 提供 PR / branch / commit / file 13 个命令（mcp-atlassian 没有这块）
- **Bitbucket 反查兜底**：通过 Jira development panel 反查关联 PR / branch / commit（无 Bitbucket 凭据时也能用）

## 适用场景

- 写/改 Confluence 富格式报告（压测报告、release notes、复盘文档）
- Jira issue 全流程（查 / 改 / 流转 / 评论 / 工时 / 关联 PR）
- 跨 issue 批量分析（JQL 搜索 + dev-info 反查）
- 多 agent 协作（claude / codex 共享同一项目缓存）

## 目录结构

```text
skills/atlassian/
├── SKILL.md                              # AI 入口（22+ 命令工作流）
├── README.md                             # 本文件
├── agents/                               # （预留）
├── references/
│   ├── confluence-html-workflow.md       # pull/push 缓存机制详解
│   ├── confluence-storage-format.md      # XHTML/macro 速查
│   ├── jql-cookbook.md                   # JQL 30+ 模板
│   ├── cql-cookbook.md                   # CQL 模板
│   ├── jira-fields-reference.md          # 字段 / issuetype / priority
│   └── bitbucket-via-jira.md             # dev-info 详解
└── scripts/
    ├── atl-credential.ps1                # 凭据 GUI 弹窗（中文界面）
    ├── atl-credential-strings.zh-CN.txt  # GUI 中文文案（UTF-8）
    ├── atl-query.ps1                     # 通用 REST 调用（jira/confluence/bitbucket）
    ├── atl-confluence.py                 # Confluence CLI（17 个子命令）
    ├── atl-jira.py                       # Jira CLI（14 个子命令）
    ├── atl-bitbucket.py                  # Bitbucket Server CLI（13 个子命令）
    └── atl-search.py                     # JQL/CQL 中文安全搜索
```

## 前置要求

- **Atlassian Server / DC**：Jira 和/或 Confluence 实例 URL 可访问
- **PowerShell 5.1+**（Windows）或 **pwsh 7+**
- **curl**（系统自带 / Git Bash 自带）
- **Python 3.8+**
- 可选：相同 host 上有 `~/.netrc` 凭据写权限

## 安装

```bash
# Claude Code（项目级）
cp -r skills/atlassian .claude/skills/atlassian

# Claude Code（全局）
cp -r skills/atlassian ~/.claude/skills/atlassian

# Codex
cp -r skills/atlassian ~/.codex/skills/atlassian
```

## 快速开始

### 第 1 步：配置凭据

```powershell
powershell -ExecutionPolicy Bypass -File scripts/atl-credential.ps1 -Action setup
```

中文 GUI 弹出，三个分组（Jira / Confluence / Bitbucket）至少填一个：

```
┌──────────────────────────────────────┐
│ Atlassian 配置（Jira+Confluence+Bitbucket） │
├─ Jira ───────────────────────────────┤
│  服务器地址：[http://jira:8080]      │
│  用户名：    [user1]                 │
│  密码 / Token：[********]            │
├─ Confluence ─────────────────────────┤
│  服务器地址：[http://conf:8090]      │
│  用户名：    [user1]                 │
│  密码 / Token：[********]            │
├─ Bitbucket（可选）───────────────────┤
│  服务器地址：[http://bitbucket:7990] │
│  用户名：    [user1]                 │
│  密码 / Token：[********]            │
└──────────────────────────────────────┘
```

存储位置：
- `~/.claude/skill-config/atlassian/config.env` （URL / user）
- `~/.netrc` 增加 machine 段（密码）

**已配置过想增量加 Bitbucket**：
```powershell
powershell -ExecutionPolicy Bypass -File scripts/atl-credential.ps1 -Action update
```
- GUI 自动**预填**已配置的 URL + user
- 已有的密码框留空（AI/工具不该读密码），保存时自动复用 .netrc
- **只需在 Bitbucket 分组填新值** → 确定 → 完成

### 第 2 步：检查配置

```bash
powershell -ExecutionPolicy Bypass -File scripts/atl-credential.ps1 -Action check
# CONFIGURED|JIRA=http://jira:8080|CONFLUENCE=http://conf:8090
```

### 第 3 步：开干

**Confluence 编辑富格式页面**：
```bash
python scripts/atl-confluence.py pull 586252316
# → .atlassian-cache/confluence/586252316/v20.draft.html

# AI 用 Edit 工具改 v20.draft.html

python scripts/atl-confluence.py diff 586252316       # 看变化
python scripts/atl-confluence.py push 586252316       # 推送（v20→v21）
```

**Jira 处理 issue**：
```bash
python scripts/atl-jira.py get-issue PROJ-123
python scripts/atl-jira.py transitions PROJ-123
python scripts/atl-jira.py transition PROJ-123 --id 31
python scripts/atl-jira.py add-comment PROJ-123 --text "调查中"
```

**JQL 搜索（中文安全）**：
```bash
python scripts/atl-search.py jql 'project = PROJ AND text ~ "压测"'
python scripts/atl-search.py jql 'assignee = currentUser()' --format keys
```

**Bitbucket Server 直连（v1.5+）**：
```bash
# PR 列表
python scripts/atl-bitbucket.py list-prs RDC/auth-service

# PR diff（写文件，不污染 context）
python scripts/atl-bitbucket.py get-pr-diff RDC/auth-service 123 --out pr-123.patch

# 读 repo 文件
python scripts/atl-bitbucket.py get-file RDC/auth-service --path src/main/Foo.java

# 加 PR 评论
python scripts/atl-bitbucket.py add-pr-comment RDC/auth-service 123 --text "LGTM"
```

**Bitbucket 通过 Jira 反查（无 BB 凭据时也能用）**：
```bash
python scripts/atl-jira.py get-dev-info PROJ-123
```

## 与 mcp-atlassian 对比

本 skill 是 mcp-atlassian 的精简复刻 + Confluence 处理改进：

| 维度 | mcp-atlassian | 本 skill |
|------|--------------|---------|
| 工具数 | ~70 | ~46 |
| 部署方式 | MCP server（独立进程） | shell 脚本（无服务） |
| Confluence 富格式 | 默认 markdown 模式毁 macro | **storage 直传，本地缓存** |
| Confluence 大内容 | MCP context 限制 | **无限制（temp file）** |
| 多轮编辑 | 每次全文进 context | **本地文件，0 token** |
| 推送冲突防护 | 无 | **强校验远程版本** |
| 凭据 | 环境变量 | `.netrc` + 中文 GUI 弹窗 |
| **Bitbucket Server 直连** | ❌ 完全没有 | ✅ 13 个命令（PR/diff/comment/branch/commit/file） |
| Bitbucket 通过 Jira 反查 | ✅ jira_get_issue_development_info | ✅ 保留 |
| Sprint / 看板 / Service Desk / ProForma | ✅ 全做 | ❌ 砍掉（频次低） |

## 自然语言示例

| 你说 | AI 做 |
|------|------|
| "拉一下 Confluence 页面 12345 改一下" | `pull 12345` → Edit `.draft.html` → `diff` → `push` |
| "PROJ-123 是什么状态？" | `get-issue PROJ-123` |
| "把 PROJ-123 流转到 Done" | `transitions` 查 ID → `transition --id N` |
| "搜一下我所有未关闭 issue" | `atl-search jql 'assignee = currentUser() AND statusCategory != Done'` |
| "PROJ-123 关联了哪些 PR？" | `get-dev-info PROJ-123` |
| "找含'压测'的 Confluence 页面" | `atl-search cql 'text ~ "压测"'` |

## 限制 / 未做

按 Tier 3 砍掉的功能（v1 不实现，未来按需补）：

- **Sprint / 看板**：`get_agile_boards` / `get_sprint_issues` / `add_issues_to_sprint` 等 7 个
- **Service Desk**：`get_service_desk_for_project` / `get_queue_issues` 等 3 个
- **ProForma 表单**：3 个
- **批量操作**：`batch_create_issues` / `batch_get_changelogs` 等 4 个
- **Watcher**：3 个
- **字段元信息**：`get_field_options` / `search_fields` / `get_link_types` 等（用 reference 文档静态化）
- **页面统计**：`get_page_views` / `get_labels` / `add_label`
- **edit-comment**：用 add 新 comment 替代

需要时直接调底层：
```bash
powershell -Command "& 'scripts/atl-query.ps1' -Service jira -Path 'rest/api/2/任意端点'"
```

## 已知坑（更多见 references/）

1. **Confluence markdown 模式毁富格式** → 用 pull/push 流程
2. **PowerShell 5.1 `.ps1` 中文乱码** → 脚本源码全 ASCII
3. **PowerShell pipe 编码毁中文** → 用 `atl-search.py`（temp file 法）
4. **MSYS 路径转换吃 `/path`** → 脚本顶部 `export MSYS_NO_PATHCONV=1`
5. **Bitbucket Cloud（云端）路径不同** → 本 skill **仅支持 Bitbucket Server / DC**，Cloud 用户不能直接用

## Roadmap

- v1.0：Jira + Confluence 核心 + Bitbucket 反查 ✅
- **v1.5（本版）**：Bitbucket Server 直连 13 个命令 + 中文 GUI ✅
- v2（按需）：Sprint / 看板 / Service Desk 等 Tier 3 功能补回
- v3（按需）：Bitbucket 写操作（创建 PR / approve / inline comment）
