# 常用 JQL 模板

> JQL = Jira Query Language。所有 `atl-jira search --jql 'X'` / `atl-search jql 'X'` 都用这个。

## 基础语法

```
field operator value [AND|OR field operator value ...] [ORDER BY field DIR]
```

操作符：`=` `!=` `>` `<` `>=` `<=` `IN (...)` `NOT IN (...)` `~` (contains) `IS EMPTY` `IS NOT EMPTY` `WAS` `CHANGED`

## 我的常用查询

### 我的 issue（待办）

```jql
assignee = currentUser() AND statusCategory != Done ORDER BY priority DESC, updated DESC
```

### 我创建的

```jql
reporter = currentUser() ORDER BY created DESC
```

### 本周更新的

```jql
updated >= startOfWeek() AND assignee = currentUser()
```

### 我参与的（assignee 或 reporter 或评论过）

```jql
assignee = currentUser() OR reporter = currentUser() OR comment ~ currentUser()
```

## 项目维度

### 某项目所有未关闭 issue

```jql
project = PROJ AND statusCategory != Done ORDER BY priority DESC
```

### 某项目某 sprint

```jql
project = PROJ AND sprint = "Sprint 5"
```

### 某项目本月新建

```jql
project = PROJ AND created >= startOfMonth()
```

### 某项目高优先级未解决

```jql
project = PROJ AND priority IN (Highest, High) AND resolution = Unresolved
```

## 状态/流转

### 进行中超过 N 天

```jql
status = "In Progress" AND status CHANGED TO "In Progress" BEFORE -7d
```

### 最近从某状态流转到另一状态

```jql
status CHANGED FROM "In Review" TO "Done" AFTER -1w
```

### 长期未流转

```jql
updated < -30d AND statusCategory != Done
```

## Sprint / 看板

### 当前 active sprint

```jql
sprint in openSprints()
```

### 本人当前 sprint

```jql
sprint in openSprints() AND assignee = currentUser()
```

### 已完成的 sprint

```jql
sprint in closedSprints() AND project = PROJ
```

## 关联关系

### Epic 下所有 issue（Server / DC）

```jql
"Epic Link" = PROJ-100
```

或（部分版本）：

```jql
parent = PROJ-100
```

### 子任务

```jql
parent = PROJ-123
```

### 阻塞我的（被某 issue 阻塞）

```jql
issueLinkType = "is blocked by" AND assignee = currentUser()
```

## 文本搜索

### Summary 含关键词

```jql
summary ~ "登录"
```

### 任意文本字段（summary / description / comment）含关键词

```jql
text ~ "OOM"
```

### 标签

```jql
labels = "regression"

labels IN (regression, urgent)
```

### 组件

```jql
component = "Auth"

component IN ("Auth", "Payment")
```

### Fix Version

```jql
fixVersion = "v2.5.0"

fixVersion IN unreleasedVersions(PROJ)
```

## 时间维度

### 今天创建的

```jql
created >= startOfDay()
```

### 上周关闭的

```jql
resolved >= startOfWeek(-1) AND resolved < startOfWeek()
```

### 截止时间临近（3 天内）

```jql
duedate >= now() AND duedate <= "3d" AND statusCategory != Done
```

### 长期 stale（30 天没动过）

```jql
updated < -30d AND statusCategory != Done
```

## 复杂组合

### 我的紧急未关闭 + 本月内创建

```jql
assignee = currentUser()
  AND priority IN (Highest, High)
  AND statusCategory != Done
  AND created >= startOfMonth()
ORDER BY priority DESC, due ASC
```

### 某 sprint 的 bug 完成率分析

```jql
project = PROJ
  AND sprint = "Sprint 5"
  AND issuetype = Bug
ORDER BY status
```

### 跨项目找某个组件的所有 issue

```jql
component = "API Gateway" AND statusCategory != Done
```

## 函数速查

| 函数 | 含义 |
|------|------|
| `currentUser()` | 当前登录用户 |
| `startOfDay()` `startOfWeek()` `startOfMonth()` `startOfYear()` | 当前时段开始 |
| `startOfWeek(-1)` | 上周开始 |
| `endOfDay()` `endOfWeek()` 等 | 时段结束 |
| `now()` | 现在 |
| `openSprints()` | 所有 active sprint |
| `closedSprints()` | 所有已结束 sprint |
| `unreleasedVersions(PROJ)` | 项目未发布版本 |
| `releasedVersions(PROJ)` | 项目已发布版本 |

## 时间偏移

| 写法 | 含义 |
|------|------|
| `-1d` | 1 天前 |
| `-1w` | 1 周前 |
| `-30d` | 30 天前 |
| `now() - 2h` | 2 小时前 |

## 排序

```jql
ORDER BY priority DESC, updated DESC
ORDER BY created ASC
ORDER BY rank ASC               -- 看板优先级
```

## 常见踩坑

### 1. 中文值要加引号

```jql
✅ status = "进行中"
❌ status = 进行中
```

### 2. 字段名大小写不敏感，但**自定义字段**用 `cf[NNNN]`

```jql
"Story Points" = 5
cf[10001] = 5     -- 同一个字段
```

找自定义字段 ID：Jira admin → Custom Fields。

### 3. `=` vs `~`

- `=` 精确匹配
- `~` 文本搜索（含 stemming + tokenization）

```jql
summary = "Login bug"     -- 精确等于
summary ~ "login"         -- 含 login（不区分大小写）
```

### 4. 状态分类 vs 状态名

```jql
status = "Done"                    -- 精确名字
statusCategory = Done              -- 大类（含 Done / Closed / Resolved 等）
statusCategory != Done             -- 所有未完成
```

### 5. 空值

```jql
assignee IS EMPTY                  -- 未分配
assignee IS NOT EMPTY              -- 已分配
```

不能用 `assignee = null` / `assignee = ""`。

## 调用示例

```bash
# table 输出
atl-jira search --jql 'project = PROJ AND priority = High AND statusCategory != Done'

# 仅 KEY 列表（管道用）
atl-search jql 'assignee = currentUser()' --format keys

# 完整 JSON
atl-search jql 'project = PROJ' --format json --limit 100

# 分页
atl-search jql 'project = PROJ' --start 100 --limit 50
```
