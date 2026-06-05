# Jira 字段速查（Server / DC）

## 系统字段（标准）

| 字段名 | 类型 | 写法（update / create） |
|--------|------|----------------------|
| `summary` | string | `"summary": "Bug title"` |
| `description` | string (含 wiki markup) | `"description": "h3. Steps\n# Step 1"` |
| `priority` | object | `"priority": {"name": "High"}` |
| `assignee` | object | `"assignee": {"name": "user1"}` |
| `reporter` | object | `"reporter": {"name": "user2"}` |
| `issuetype` | object | `"issuetype": {"name": "Bug"}` |
| `status` | object（**通过 transition 改**，不能直接 set） | 用 `atl-jira transition` |
| `resolution` | object | `"resolution": {"name": "Fixed"}` |
| `labels` | string list | `"labels": ["regression", "urgent"]` |
| `components` | object list | `"components": [{"name": "Auth"}]` |
| `fixVersions` | object list | `"fixVersions": [{"name": "v2.5.0"}]` |
| `affectsVersions` | object list | `"versions": [{"name": "v2.4.0"}]` |
| `duedate` | date | `"duedate": "2026-05-01"` |
| `environment` | string | `"environment": "Production"` |

> ⚠ **status 不能用 update 直接改**，必须用 transition：
> ```bash
> atl-jira transitions PROJ-123    # 列可用流转
> atl-jira transition PROJ-123 --id 31 --comment "fixed"
> ```

## 时间字段（只读，不可写）

| 字段 | 含义 |
|------|------|
| `created` | 创建时间 |
| `updated` | 最后更新时间 |
| `resolutiondate` | 解决时间 |

---

## 工时字段语义（重要，常踩坑）

Jira 有 3 个相关概念，**完全不同**，混用会导致数字错：

### 1. `timetracking` 字段（issue 级简表）

```bash
atl-jira get-issue PROJ-123 --fields timetracking
```

返回结构：
```json
{
  "timetracking": {
    "originalEstimate": "1d",
    "remainingEstimate": "2h",
    "timeSpent": "6h",
    "originalEstimateSeconds": 28800,
    "remainingEstimateSeconds": 7200,
    "timeSpentSeconds": 21600
  }
}
```

`timeSpent` 是 **本 issue 自身 worklog 的聚合**，**不包含子任务**。

| 场景 | 这个字段够用？ |
|------|------------|
| 看单个 task / story 自己的工时 | ✅ |
| 看 epic 总工时 | ❌（不含子 issue） |
| 看父任务 + 子任务总工时 | ❌（不含 subtasks） |

### 2. `worklog` 端点（issue 级明细）

```bash
atl-jira get-worklog PROJ-123
```

读取 `/rest/api/2/issue/{key}/worklog`，返回**该 issue 的每条工时记录**（谁、何时、多久、评论）。

总和 = `sum(timeSpentSeconds)` of all entries — 等于上面 `timetracking.timeSpentSeconds`。

仍然**不包含子任务**。

### 3. 父+子任务聚合（必须自己算）

Jira **不提供**"含子任务总工时"的字段。两种算法：

**方法 A**（推荐）：`get-worklog --include-subtasks`

```bash
atl-jira get-worklog PROJ-123 --include-subtasks
```

脚本自动：
1. 拉父任务 worklog
2. 读父任务的 `subtasks` 字段
3. 逐个拉子任务 worklog
4. 求和后输出 `GRAND TOTAL`

**方法 B**（JQL 聚合，跨任意范围）：

```bash
# 用 JQL `parent = PROJ-123 OR key = PROJ-123` 找出所有相关 issue
atl-search jql 'parent = PROJ-123 OR key = PROJ-123' --format keys
# 然后逐个 get-worklog 求和
```

> **典型场景**：用户问 "FUDJSZ-477 这个任务总共花了多少工时" → **务必加 `--include-subtasks`**，否则只看到父任务自己的（通常是 0，因为大家在子任务上记工时）。

### 字段差异速查

| 来源 | 含义 | 含子任务？ | 用法 |
|------|------|-----------|------|
| `timetracking.timeSpent` | 本 issue 工时简表 | ❌ | `get-issue --fields timetracking` |
| `worklog.timeSpentSeconds` 总和 | 本 issue 工时明细总和 | ❌ | `get-worklog <KEY>` |
| `aggregatetimespent` 字段 | 含子任务的聚合（部分版本支持） | ✅（如果存在） | `get-issue --fields aggregatetimespent` |
| 本脚本 `--include-subtasks` | 父+所有 subtasks 总和 | ✅ | `get-worklog <KEY> --include-subtasks` |

> `aggregatetimespent` 字段在不同 Jira 版本表现不一，Server 较老版本可能没有。**最可靠的还是用 `--include-subtasks` 自己聚合**。

## 父子 / 关联

| 字段 | 写法 |
|------|------|
| `parent`（subtask 用） | `"parent": {"key": "PROJ-100"}` |
| `Epic Link`（custom field） | 需查 `cf[10001]` 编号，或 Server 用 `customfield_NNNN` |

或用专门 API：
```bash
atl-jira create-link PROJ-123 PROJ-456 --type "Relates"
```

## 自定义字段（custom field）

不同 Jira 实例的 custom field ID 不同。查询：

```bash
# 列出所有字段（找 customfield_NNNN）
atl-jira search --jql 'project = PROJ' --fields '*all' --limit 1 --json | grep -i 'customfield'
```

或通过 Jira admin → Custom Fields → 字段 ID 在 URL 里。

写入 custom field：

```bash
atl-jira update PROJ-123 --field customfield_10001=value
```

部分自定义字段是对象类型（select list），需要：

```bash
atl-jira update PROJ-123 --field customfield_10010='{"value":"option1"}'
```

> 本 skill 的 `atl-jira update` CLI 把 value 当字符串处理，object 类型字段需手写 JSON 或用底层 `atl-query.ps1`。

## 常见 issuetype 名称

| 名称 | 含义 |
|------|------|
| `Bug` | bug |
| `Task` | 任务 |
| `Story` | 故事 |
| `Epic` | epic |
| `Sub-task` | 子任务 |
| `Improvement` | 改进 |
| `New Feature` | 新特性 |

## 常见 priority

| 名称 | 含义 |
|------|------|
| `Highest` | 最高 |
| `High` | 高 |
| `Medium` | 中 |
| `Low` | 低 |
| `Lowest` | 最低 |

实际可用的 priority 取决于实例配置，查询：

```bash
# 用 jira_get_field_options 等价：直接 REST
powershell -Command "& 'atl-query.ps1' -Service jira -Path 'rest/api/2/priority'"
```

## 常见 link types（issue link）

| 名称 | inward | outward |
|------|--------|---------|
| `Relates` | relates to | relates to |
| `Blocks` | is blocked by | blocks |
| `Cloners` | is cloned by | clones |
| `Duplicate` | is duplicated by | duplicates |
| `Causes` | is caused by | causes |

查实例的所有 link types：

```bash
powershell -Command "& 'atl-query.ps1' -Service jira -Path 'rest/api/2/issueLinkType'"
```

## 创建 issue 必填字段

| 字段 | 必填？ | 说明 |
|------|------|------|
| `project` | ✅ | `{"key": "PROJ"}` |
| `summary` | ✅ | |
| `issuetype` | ✅ | |
| `description` | 推荐 | wiki markup |
| `priority` | 项目配置决定 | |
| `assignee` | 项目配置决定 | |

## update 字段值的几种格式

### 字符串

```bash
atl-jira update PROJ-123 --field summary="新标题"
```

### 对象（name 引用）

```bash
atl-jira update PROJ-123 --field priority=High
# CLI 自动包成 {"name": "High"}
```

CLI 自动处理：`assignee` / `reporter` / `priority` / `issuetype` / `status` / `components` / `fixVersions`。

### 列表

```bash
# labels（plain string list）
atl-jira update PROJ-123 --field labels=regression,urgent

# components / fixVersions（对象 list）
atl-jira update PROJ-123 --field components=Auth,Payment
```

### 自定义字段（手动 JSON）

复杂字段当前 CLI 不支持，需直接调底层：

```bash
powershell -Command "& 'atl-query.ps1' -Service jira -Path 'rest/api/2/issue/PROJ-123' -Method PUT -Body '{\"fields\":{\"customfield_10010\":{\"value\":\"option1\"}}}'"
```

## description 的 wiki markup 速查

Jira Server description 用 wiki markup 不是 markdown：

| 效果 | wiki | markdown 对照 |
|------|------|------|
| 标题 | `h1. ` `h2. ` `h3. ` | `# ## ###` |
| 加粗 | `*text*` | `**text**` |
| 斜体 | `_text_` | `*text*` |
| 列表 | `* item` `# item` | `- item` `1. item` |
| 代码块 | `{code:python}\n...\n{code}` | ` ```python ` |
| 引用 | `bq. text` | `> text` |
| 链接 | `[text\|url]` | `[text](url)` |
| issue 引用 | `PROJ-123`（自动链接） | — |
| 表格 | <code>&#124;&#124;header&#124;&#124;<br/>&#124;cell1&#124;cell2&#124;</code> | — |

## 实用 JQL：找特定字段为空的

```jql
assignee IS EMPTY                       -- 未分配
duedate IS EMPTY AND priority = High    -- 高优先级但没截止
"Epic Link" IS EMPTY AND project = PROJ -- 没挂 Epic 的
```

## 字段值大小写

- `status = "In Progress"` — **精确大小写**
- `priority = High` — 名字关键字一般首字母大写

不确定时先查实例：

```bash
atl-jira search --jql 'project = PROJ' --fields status,priority --limit 5 --json
```

---

## 子任务迁移（reparent）

`atl-jira move <KEY> --parent <NEW>` 支持两种路径，自动选择：

1. **同项目**：试 `PUT fields.parent` + verify（要求 admin 把 parent 加到 Edit screen）
2. **跨项目**：自动跑 9 步 web 表单 wizard（curl 模拟 ConvertSubTask + MoveIssue + ConvertIssue）

跨项目自动化已实测通过（Jira Server 8.3，约 5 秒完成单条移动）。下面是历史背景说明 — REST 直接路径为什么不存在。

### 何时可能成功

- 同项目内 reparent + 当前用户有 Edit Issue 权限 + `parent` 在 Edit screen 上
- 这种情况罕见，因为 Jira 默认不把 parent 字段放到 Edit screen 上

### 何时一定失败

- **跨项目子任务迁移**（绝大多数实际场景）
- `parent` 字段不在该项目/issue type 的 Edit screen 上
- 没有 Edit Issue 权限

### 失败的两种表现

1. **HTTP 200 静默 no-op**：API 返回成功但 parent 实际未变。这是用 `fields.parent` 的典型表现。
2. **HTTP 400 显式拒绝**：`{"errors":{"parent":"Field 'parent' cannot be set. It is not on the appropriate screen, or unknown."}}`。这是用 `update.parent` 的典型表现。

`atl-jira move` 命令做了 **PUT 后 GET 校验**，能正确识别上述两种失败并退出码 2。

### 为什么 REST 不能做完整跨项目移动

Jira Web UI 的 Move Wizard 实际做了多步操作：
1. 校验目标项目允许该 issue type
2. 映射 source workflow 状态 → target workflow 状态
3. 映射 source 字段 scheme → target 字段 scheme（包括自定义字段）
4. 处理 fix version / component 的项目作用域（这些都是项目内的）
5. 更新 issue key（FUDJSZ-516 → JXJYPXTYPT-???）
6. 重定向所有引用（issue link、comment 引用、PR 关联...）

这些操作 Jira REST API **不暴露**。只能通过 Web UI 完成。

### 推荐工作流

**批量跨项目（最常见）**：用 `move-helper` + Web UI Bulk Change
```bash
atl-jira move-helper OLD_PARENT --new-parent NEW_PARENT
```
输出：
- 自动列出所有子任务（key + 状态 + 摘要）
- 生成预填 Issue Navigator URL（所有 key URL-encoded，**点开就全选**）
- 7 步 Bulk Change 操作指南

实际操作 ~3 分钟：点开 URL → Tools → Bulk Change → Move → Next ×5 → Confirm。

**单个子任务**：直接点 Web UI Move Wizard
```
http://<jira>/secure/MoveIssue!default.jspa?key=<KEY>
```

**装插件解锁 REST**（可选）：
- "JIRA Misc Workflow Extensions"（JMWE）
- "ScriptRunner for JIRA"
- 这些插件可暴露 cross-project move 的 REST 端点
- 装上后可改 skill 的 cmd_move 使用插件 endpoint

### 同项目 reparent

`atl-jira move <KEY> --parent <SAME_PROJ_PARENT> --yes` 会尝试 PUT。

成功条件：
- 当前用户有 Edit Issue 权限
- `parent` 字段在该 issue type/project 的 Edit screen 上（**默认不在**，需 Jira admin 配置）

成功 → exit 0。失败（比如 silent no-op） → exit 2，给出 Web UI URL。

### 实测案例（cross-project，refuse）

```
$ atl-jira move FUDJSZ-516 --parent JXJYPXTYPT-27282 --yes
=== Move plan ===
  Source:         FUDJSZ-516  [子任务]
  Current parent: FUDJSZ-477
  New parent:     JXJYPXTYPT-27282  [主任务]
  Source project: FUDJSZ
  Target project: JXJYPXTYPT  (CROSS-PROJECT)

REFUSED: cross-project subtask move is not supported by Jira Server REST.
Reasons (per Atlassian: JRA-13763, JRASERVER-15259):
  1. The Move Wizard is a multi-step process:
     convert subtask -> standard issue -> move cross-project -> convert back to subtask.
  2. The convert-subtask-to-issue step has no REST endpoint (JRA-27893).
  ...

Fastest manual path:
  atl-jira move-helper FUDJSZ-477 --new-parent JXJYPXTYPT-27282
```

退出码 2，issue 完全未受影响（不浪费 API call，不撒谎说"试过了"）。
