# 常用 CQL 模板

> CQL = Confluence Query Language。所有 `atl-confluence search --cql 'X'` / `atl-search cql 'X'` 都用这个。

## 基础语法

```
field operator value [AND|OR ...] [ORDER BY field DIR]
```

操作符：`=` `!=` `~` (contains) `IN (...)` `NOT IN (...)` `>` `<` `>=` `<=`

## 按内容找

### 标题精确匹配

```cql
title = "压测性能分析【注册，第3轮】"
```

### 标题含关键词

```cql
title ~ "压测"
```

### 全文搜索（标题 + 正文 + 评论）

```cql
text ~ "OOM"
```

### 关键词组合

```cql
text ~ "OOM" AND text ~ "Flink"
```

## 按位置找

### 某空间内

```cql
space = "RDCenterKnowledge"
```

### 某空间下某父页的子孙

```cql
space = "RDC" AND ancestor = 586252320
```

### 某父页的直接子页

```cql
parent = 586252320
```

## 按时间找

### 最近一周更新

```cql
lastModified > "now('-7d')"
```

### 今天更新

```cql
lastModified > startOfDay()
```

### 我创建的

```cql
creator = currentUser()
```

### 我最近一周更新的

```cql
contributor = currentUser() AND lastModified > "now('-7d')"
```

## 按类型找

### 仅页面

```cql
type = page
```

### 仅评论

```cql
type = comment
```

### 仅附件

```cql
type = attachment
```

### 博客

```cql
type = blogpost
```

## 按标签

### 含某 label

```cql
label = "release-notes"

label IN (release-notes, postmortem)
```

## 复杂组合

### 某空间下某父页的所有页面，按更新时间倒序

```cql
space = "RDC"
  AND ancestor = 586252320
  AND type = page
ORDER BY lastModified DESC
```

### 我贡献过的所有 release-notes

```cql
contributor = currentUser() AND label = "release-notes"
```

### 某关键词在某空间最近一月内的页面

```cql
space = "RDC" AND text ~ "压测" AND lastModified > "now('-30d')"
ORDER BY lastModified DESC
```

## 字段速查

| 字段 | 含义 |
|------|------|
| `space` | 空间 key |
| `title` | 页面标题 |
| `text` | 全文（含正文/标题/评论） |
| `type` | 内容类型：`page` / `comment` / `attachment` / `blogpost` |
| `parent` | 父页 ID |
| `ancestor` | 任何祖先页 ID |
| `creator` | 创建人 |
| `contributor` | 贡献者（含创建+编辑） |
| `lastModified` | 最后修改时间 |
| `created` | 创建时间 |
| `label` | 标签 |
| `mention` | 提及的用户 |

## 函数

| 函数 | 含义 |
|------|------|
| `currentUser()` | 当前用户 |
| `startOfDay()` `startOfWeek()` `startOfMonth()` | 时段开始 |
| `now('-7d')` | 7 天前（**注意单引号嵌套**） |
| `now('-1w')` | 1 周前 |

## 常见踩坑

### 1. `now()` 偏移要嵌套引号

```cql
✅ lastModified > "now('-7d')"
❌ lastModified > now('-7d')        -- 缺外层引号
❌ lastModified > "now(-7d)"        -- 缺内层引号
```

### 2. 中文值要加引号

```cql
✅ title ~ "压测"
❌ title ~ 压测
```

### 3. `~` 不是模糊匹配，是分词搜索

```cql
title ~ "压测 性能"     -- 找含 "压测" 或 "性能" 的页
title = "压测性能分析"   -- 标题精确等于
```

### 4. 父页用 `parent`，子孙都要用 `ancestor`

```cql
parent = 12345           -- 直接子页
ancestor = 12345         -- 子页 + 子子页 + 子子子页 + ...
```

### 5. 删除的页面 默认不出现

CQL 不返回 trash 中的内容。要找已删除的，用 admin 工具或 REST API 直接查 trash。

### 6. 排序：CQL 默认按 relevance

```cql
... ORDER BY lastModified DESC      -- 显式排序
... ORDER BY title ASC
```

## 调用示例

```bash
# 在某父页下找含关键词的页
atl-confluence search --cql 'ancestor = 586252320 AND text ~ "压测"' --limit 10

# 仅返回 page id 列表（脚本管道用）
atl-search cql 'space = "RDC" AND lastModified > "now(\"-7d\")"' --format ids

# JSON 完整
atl-search cql 'creator = currentUser()' --format json
```
