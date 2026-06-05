# Bitbucket Server / Data Center 操作

本 skill 提供两种 Bitbucket 访问方式：

1. **直连**（v1.5+，推荐）：`atl-bitbucket.py` — Bitbucket Server REST API v1.0
2. **通过 Jira 反查**（兜底）：`atl-jira.py get-dev-info <issue>` — 间接查关联 PR/branch/commit

> **注意**：仅支持 Bitbucket **Server / Data Center**（路径 `/rest/api/1.0/...`）。Bitbucket Cloud 用户**不要**用本 skill（API 路径不同）。

---

## 直连（atl-bitbucket.py）

### 配置

`atl-credential.ps1 -Action setup` 弹窗里第三个分组填 Bitbucket URL + user + password/PAT。

凭据存储：
- `~/.claude/skill-config/atlassian/config.env` 加 `BITBUCKET_URL=...` / `BITBUCKET_USER=...`
- `~/.netrc` 加 `machine <bitbucket-host> login <user> password <pat>` 段
- 如果 Bitbucket 与 Jira/Confluence 同主机（共用一个 PAT），`.netrc` 只存一份

### Repo 命名

所有 repo-scoped 命令用 `PROJECT/REPO` 单参数（Bitbucket 的 project key + repo slug）：

```bash
atl-bitbucket list-prs RDC/auth-service
atl-bitbucket get-pr RDC/auth-service 123
```

### 命令清单

#### 项目 / Repo

```bash
# 列项目
python atl-bitbucket.py list-projects [--limit N]

# 项目下 repo
python atl-bitbucket.py list-repos RDC [--limit N]

# 列 branch
python atl-bitbucket.py list-branches RDC/auth-service [--filter develop] [--limit N]

# 列 commit
python atl-bitbucket.py list-commits RDC/auth-service [--branch master] [--limit N]

# 单个 commit 详情
python atl-bitbucket.py get-commit RDC/auth-service abc12345
```

#### Pull Requests

```bash
# 列 PR（默认 OPEN）
python atl-bitbucket.py list-prs RDC/auth-service [--state OPEN|MERGED|DECLINED|ALL] [--limit N]

# PR 详情（含 reviewers / status）
python atl-bitbucket.py get-pr RDC/auth-service 123

# PR 完整 diff（推荐写文件，不污染 context）
python atl-bitbucket.py get-pr-diff RDC/auth-service 123 --out pr-123.patch

# PR 文件变更列表（仅文件名 + 类型）
python atl-bitbucket.py get-pr-changes RDC/auth-service 123

# PR 评论 + 活动历史
python atl-bitbucket.py get-pr-activities RDC/auth-service 123

# 加 PR 评论
python atl-bitbucket.py add-pr-comment RDC/auth-service 123 --text "looks good"
python atl-bitbucket.py add-pr-comment RDC/auth-service 123 --file comment.md
```

#### 文件读取

```bash
# 列目录
python atl-bitbucket.py browse RDC/auth-service [--path src/main] [--at master]

# 读单个文件（默认 stdout，大文件用 --out）
python atl-bitbucket.py get-file RDC/auth-service --path src/main/java/Foo.java [--at HEAD]
python atl-bitbucket.py get-file RDC/auth-service --path big.csv --at master --out local.csv
```

### Token 优化要点

| 操作 | 错误做法 | 推荐做法 |
|------|---------|---------|
| 看 PR diff（10KB+） | 默认 stdout 进 context | `--out pr.patch` 写文件 + Read 局部 |
| 读源文件 | stdout 全打印 | `--out` 写文件 + Read 按 line range |
| PR 详情 | `--json` 全 dump | 默认表格输出（已抽关键字段） |

### 输出 JSON

所有 list-* / get-* 命令支持 `--json` 输出原始 JSON：

```bash
python atl-bitbucket.py list-prs RDC/auth-service --json | python -c "
import sys, json
prs = json.load(sys.stdin)['values']
unmerged = [p for p in prs if p['state'] != 'MERGED']
print(f'{len(unmerged)} open PRs')
"
```

---

## 通过 Jira 反查（atl-jira get-dev-info）

在你不需要 Bitbucket 直连，或 Bitbucket 暂时没配凭据时使用。**前提**：commit/branch 名带 Jira issue key（如 `feature/PROJ-123-add-foo`）。

```bash
atl-jira get-dev-info PROJ-123
atl-jira get-dev-info PROJ-123 --app-type stash --data-type pullrequest
atl-jira get-dev-info PROJ-123 --json
```

返回：关联 PR（id/状态/URL/reviewers）、branch、commit、repository。

### 直连 vs 反查 怎么选

| 场景 | 推荐 |
|------|------|
| 已知 PR ID，想看 diff | **直连** `get-pr-diff` |
| 想浏览 repo 文件 | **直连** `browse` / `get-file` |
| 只知道 Jira issue，想找关联 PR | **反查** `get-dev-info` |
| Bitbucket 没配凭据 | **反查**（用 Jira 凭据足够） |
| 跨 issue 批量查 PR 状态 | **反查** + 解析 JSON |

### 常见问题

**反查 dev-info 为空**：commit/branch 名没带 issue key。检查 Jira issue 页 "Development" 面板，需要 Bitbucket 端配置 Jira application link + commit message 含 issue key。

**直连和反查数字对不上**：dev-info 是缓存数据，PR 状态可能滞后几秒~几分钟。要实时状态走直连。

---

## Bitbucket Server REST API 端点参考

CLI 不够用时直接调底层：

```bash
powershell -Command "& 'atl-query.ps1' -Service bitbucket -Path 'rest/api/1.0/...'"
```

完整端点列表见 [Bitbucket Server REST API](https://docs.atlassian.com/bitbucket-server/rest/latest/bitbucket-rest.html)。

CLI 当前未覆盖的常见操作（按需用底层 atl-query.ps1）：
- 创建 PR（POST `pull-requests`）
- 批准 PR（POST `.../approve`）
- 删除评论（DELETE `.../comments/{id}`）
- 创建 branch（POST `.../branches`）
- inline comment（POST `.../comments` with anchor）

---

## 工作流示例

### 1. PR Code Review

```bash
# 查 PR 详情、改了哪些文件
atl-bitbucket get-pr RDC/auth-service 123
atl-bitbucket get-pr-changes RDC/auth-service 123

# 拉完整 diff 到本地
atl-bitbucket get-pr-diff RDC/auth-service 123 --out pr-123.patch
# AI 用 Read 工具按 line range 看 diff

# 看历史评论
atl-bitbucket get-pr-activities RDC/auth-service 123

# 评论
atl-bitbucket add-pr-comment RDC/auth-service 123 --text "LGTM, 注意 line 42 的边界条件"
```

### 2. 跨 issue 批量查 PR

```bash
atl-search jql 'sprint in openSprints() AND assignee = currentUser()' --format keys > issues.txt
while read key; do
    echo "=== $key ==="
    atl-jira get-dev-info "$key" --data-type pullrequest
done < issues.txt
```

### 3. 拉文件历史版本对比

```bash
atl-bitbucket get-file RDC/auth-service --path src/Auth.java --at abc12345 --out old.java
atl-bitbucket get-file RDC/auth-service --path src/Auth.java --out new.java
diff old.java new.java
```

### 4. 浏览 repo 结构

```bash
atl-bitbucket browse RDC/auth-service                    # 根目录
atl-bitbucket browse RDC/auth-service --path src/main    # 子目录
atl-bitbucket browse RDC/auth-service --path README.md   # 单文件（输出内容）
```
