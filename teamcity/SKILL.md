---
name: teamcity
description: >
  TeamCity CI/CD operations. Auto-trigger when user asks to deploy, trigger builds,
  check build status/logs, cancel builds, view build queue, search projects/build configs,
  query templates, modify template/build config parameters/steps/features/triggers,
  check template change history, or interact with TeamCity.
---

# TeamCity REST API Skill

## 连接配置

- 配置文件: `~/.claude/skill-config/teamcity/config.env`（存 TC_URL 和 TC_USER，非敏感）
- 凭据文件: `~/.netrc`（存密码，仅 curl.exe --netrc 读取，**禁止在命令中出现明文密码**）
- 脚本目录: `$SKILL_DIR/scripts/`（见下方路径约定）
- 响应格式: JSON

### 脚本路径约定

本 Skill 的脚本位于 `SKILL.md` 同级的 `scripts/` 目录下。安装位置因 Agent 而异，**首次使用时需定位 `SKILL.md` 所在目录**，设定 `$SKILL_DIR` 变量：

```
# 可能的安装位置（按优先级检查，取第一个存在的）：
# 1. 项目级: .claude/skills/teamcity/
# 2. 全局 Claude: ~/.claude/skills/teamcity/
# 3. Codex: ~/.codex/skills/teamcity/
# 4. 源码: skills/teamcity/（开发环境）
```

脚本清单：
- `$SKILL_DIR/scripts/tc-query.ps1` — API 调用封装（配置加载、UTF-8 编码、HTTP 状态检查）
- `$SKILL_DIR/scripts/tc-diff.py` — 配置版本 diff（自动解码 base64 脚本）
- `$SKILL_DIR/scripts/tc-search.py` — 搜索工具（项目/模板/构建配置/审计，中文安全）
- `$SKILL_DIR/scripts/tc-export.py` — 模板导出（当前/历史版本）
- `$SKILL_DIR/scripts/tc-import.py` — 模板导入（JSON → REST API PUT）
- `$SKILL_DIR/scripts/tc-package.py` — 导入交付物打包

## API 调用方式

**所有 REST API 调用统一使用 `tc-query.ps1` 脚本**，自动处理配置加载、UTF-8 编码、curl.exe 调用和 .netrc 认证。

**重要：必须使用 `-Command` 模式调用**（`-File` 模式会导致路径参数解析错误）：

```bash
# 初始化脚本路径变量（每次会话设置一次）
TC_Q="$SKILL_DIR/scripts/tc-query.ps1"

# GET 请求
powershell -ExecutionPolicy Bypass -Command "& '$TC_Q' -Path '请求路径'"

# POST 请求（JSON body，注意 \" 转义）
powershell -ExecutionPolicy Bypass -Command "& '$TC_Q' -Path '请求路径' -Method POST -Body '{\"key\":\"value\"}'"

# PUT 请求（非 JSON body 需指定 ContentType）
powershell -ExecutionPolicy Bypass -Command "& '$TC_Q' -Path '请求路径' -Method PUT -Body 'finished' -ContentType 'text/plain'"

# 非 REST API 端点（如构建日志）使用 -RawPath
powershell -ExecutionPolicy Bypass -Command "& '$TC_Q' -Path 'httpAuth/downloadBuildLog.html?buildId=123' -RawPath"

# 搜索项目/模板/构建配置（中文安全，避免管道编码问题）
python $SKILL_DIR/scripts/tc-search.py projects 关键词
python $SKILL_DIR/scripts/tc-search.py templates 关键词
python $SKILL_DIR/scripts/tc-search.py builds 关键词 --project 项目ID
python $SKILL_DIR/scripts/tc-search.py audit 模板ID --version 版本号
```

> **禁止使用 `powershell ... | python -c` 管道过滤中文 JSON**，PowerShell 5.1 管道编码会破坏中文。所有含中文的搜索/过滤操作统一用 `tc-search.py`。

> `-Path` 参数不需要前导 `/`，脚本自动拼接 `$TC_URL/httpAuth/app/rest/` 前缀。
> 后续示例中 `$TC_Q` 均指 `$SKILL_DIR/scripts/tc-query.ps1`。

## 搜索策略（重要）

TeamCity 2020.1.x 的 `name:(value:...,matchType:contains)` locator **在 buildTypes 和 projects 上不可用**（返回空结果）。

**可用的搜索方式**：
1. **直接 ID 查询**（最可靠）：`buildTypes/id:构建配置ID`
2. **按项目列出**：`buildTypes?locator=project:(id:项目ID)`
3. **列出后本地过滤**：列出全部 + Python 过滤名称/ID

TeamCity 的 ID 通常是英文驼峰命名（如 `FlinkDeployK8SImageGradleTemplate`），优先按 ID 查询。

## 初始化引导（每次使用前必须执行）

**第一步：检查配置状态**
```bash
powershell -ExecutionPolicy Bypass -File "$SKILL_DIR/scripts/tc-credential.ps1" -Action check
```

返回值说明：
- `CONFIGURED|http://...` → 配置已就绪
- `NOT_CONFIGURED` → **必须先运行 setup**（见第二步）

**第二步：首次配置（仅未配置时执行）**
```bash
powershell -ExecutionPolicy Bypass -File "$SKILL_DIR/scripts/tc-credential.ps1" -Action setup
```
弹出 Windows GUI 窗口，用户填写 Server URL、Username、Password。
密码不经过终端，AI 只看到 `OK|http://...` 或 `CANCELLED`。

**第三步：设置脚本路径变量**
```bash
TC_Q="$SKILL_DIR/scripts/tc-query.ps1"
```

> tc-query.ps1 内部自动加载 TC_URL，无需手动 source config.env。
> 若需要 TC_USER（如查询当前用户构建），从 config.env 中读取：
> `powershell -Command "(Get-Content ~/.claude/skill-config/teamcity/config.env | Select-String 'TC_USER=').Line -replace 'TC_USER=',''"`

**更新配置**：`-Action update`（弹窗中会预填现有值）
**删除配置**：`-Action delete`

## 重要注意事项

- 实例可能有大量项目和构建配置，查询时**必须使用 locator 过滤和 fields 限制返回字段**
- 项目命名规则示例：`{产品key}_{分支类型}_{产品key}_{版本}_{环境}_{步骤}`
- 分支类型包括: feature / hotfix / release
- **禁止**读取 `~/.netrc` 文件内容
- **修改操作（PUT/POST/DELETE）必须先向用户确认**，特别是整体替换（PUT all）操作
- **禁止**调用本文档未列出的 API 端点，遇到未覆盖的需求应告知用户

---

## 查询操作

### 服务器信息
```bash
powershell -ExecutionPolicy Bypass -Command "& '$TC_Q' -Path 'server'"
```

### 搜索项目（按名称关键词）

> **注意**：`name` locator 在 2020.1.x 不可用，用 tc-search.py 本地过滤。

```bash
python $SKILL_DIR/scripts/tc-search.py projects 关键词
```

### 列出某个项目下的子项目
```bash
powershell -ExecutionPolicy Bypass -Command "& '$TC_Q' -Path 'projects?locator=parentProject:(id:项目ID)&fields=project(id,name,description)'"
```

### 搜索构建配置（按名称或 ID 关键词）

```bash
# 按关键词搜索（支持 --project 限定项目）
python $SKILL_DIR/scripts/tc-search.py builds 关键词
python $SKILL_DIR/scripts/tc-search.py builds 关键词 --project 项目ID

# 已知 ID 直接查（最可靠）
powershell -ExecutionPolicy Bypass -Command "& '$TC_Q' -Path 'buildTypes/id:构建配置ID?fields=id,name,projectName'"
```

### 列出某项目下的构建配置
```bash
powershell -ExecutionPolicy Bypass -Command "& '$TC_Q' -Path 'buildTypes?locator=project:(id:项目ID)&fields=buildType(id,name,projectName)'"
```

### 获取构建配置详情（含参数和步骤）
```bash
powershell -ExecutionPolicy Bypass -Command "& '$TC_Q' -Path 'buildTypes/id:构建配置ID?fields=id,name,projectName,parameters(property(name,value)),steps(step(name,type))'"
```

---

## 模板操作

TeamCity 的模板（Template）也是 buildType 的一种，通过 `templateFlag` locator 区分。

### 搜索模板（按名称或 ID 关键词）

```bash
python $SKILL_DIR/scripts/tc-search.py templates 关键词

# 已知 ID 直接查
powershell -ExecutionPolicy Bypass -Command "& '$TC_Q' -Path 'buildTypes/id:模板ID?fields=id,name,projectName,templateFlag'"
```

### 列出某项目下的所有模板
```bash
powershell -ExecutionPolicy Bypass -Command "& '$TC_Q' -Path 'buildTypes?locator=templateFlag:true,project:(id:项目ID)&fields=buildType(id,name,projectName)'"
```

### 获取模板详情（含参数、步骤）
```bash
powershell -ExecutionPolicy Bypass -Command "& '$TC_Q' -Path 'buildTypes/id:模板ID?fields=id,name,projectName,templateFlag,parameters(property(name,value)),steps(step(name,type))'"
```

### 反查哪些构建配置引用了某模板
```bash
powershell -ExecutionPolicy Bypass -Command "& '$TC_Q' -Path 'buildTypes?locator=template:(id:模板ID)&fields=buildType(id,name,projectName,projectId)'"
```

### 查询模板关联的所有构建（按时间范围）
```bash
powershell -ExecutionPolicy Bypass -Command "& '$TC_Q' -Path 'builds?locator=buildType:(template:(id:模板ID)),sinceDate:20250101T000000%2B0800,count:100&fields=build(id,buildTypeId,number,status,state,startDate,finishDate)'"
```

> sinceDate 格式为 `yyyyMMddTHHmmss+时区`，URL 中 `+` 需编码为 `%2B`。

---

## 构建操作

### 查看最近 N 次构建
```bash
powershell -ExecutionPolicy Bypass -Command "& '$TC_Q' -Path 'builds?locator=buildType:(id:构建配置ID),count:10&fields=build(id,number,status,state,startDate,finishDate,branchName)'"
```

### 查看某次构建详情
```bash
# 基础信息（触发人、变更记录）
powershell -ExecutionPolicy Bypass -Command "& '$TC_Q' -Path 'builds/id:构建ID?fields=id,buildTypeId,status,statusText,state,startDate,finishDate,triggered(type,user(username)),changes(change(version,username,comment))'"

# 含最终生效参数（resultingProperties 比 properties 更可靠，合并了模板默认值+覆盖值+触发时传入值）
powershell -ExecutionPolicy Bypass -Command "& '$TC_Q' -Path 'builds/id:构建ID?fields=id,buildTypeId,status,state,properties(property(name,value)),resultingProperties(property(name,value))'"
```

### 查看构建日志

构建日志不走 REST API，走专用下载端点。使用 `-RawPath` 参数。日志可能很长，截取末尾查看。
```powershell
powershell -ExecutionPolicy Bypass -Command "& '$TC_Q' -Path 'httpAuth/downloadBuildLog.html?buildId=构建ID' -RawPath" | Select-Object -Last 100
```

### 查看构建失败的问题
```bash
powershell -ExecutionPolicy Bypass -Command "& '$TC_Q' -Path 'builds/id:构建ID/problemOccurrences?fields=problemOccurrence(id,type,identity,details)'"
```

### 查看构建统计（耗时等）
```bash
powershell -ExecutionPolicy Bypass -Command "& '$TC_Q' -Path 'builds/id:构建ID/statistics'"
```

---

## 触发构建

### 基础触发
```bash
powershell -ExecutionPolicy Bypass -Command "& '$TC_Q' -Path 'buildQueue' -Method POST -Body '{\"buildType\":{\"id\":\"构建配置ID\"}}'"
```

### 指定分支触发
```bash
powershell -ExecutionPolicy Bypass -Command "& '$TC_Q' -Path 'buildQueue' -Method POST -Body '{\"buildType\":{\"id\":\"构建配置ID\"},\"branchName\":\"refs/heads/分支名\"}'"
```

### 覆盖参数触发
```bash
powershell -ExecutionPolicy Bypass -Command "& '$TC_Q' -Path 'buildQueue' -Method POST -Body '{\"buildType\":{\"id\":\"构建配置ID\"},\"properties\":{\"property\":[{\"name\":\"参数名\",\"value\":\"参数值\"}]}}'"
```

---

## 构建队列

### 查看当前队列
```bash
powershell -ExecutionPolicy Bypass -Command "& '$TC_Q' -Path 'buildQueue?fields=build(id,buildTypeId,state,branchName)'"
```

### 取消排队中的构建
```bash
powershell -ExecutionPolicy Bypass -Command "& '$TC_Q' -Path 'builds/id:构建ID' -Method POST -Body '{\"comment\":\"取消原因\",\"readdIntoQueue\":false}'"
```

### 停止运行中的构建
```bash
powershell -ExecutionPolicy Bypass -Command "& '$TC_Q' -Path 'builds/id:构建ID/state' -Method PUT -Body 'finished' -ContentType 'text/plain'"
```

---

## 审计日志

查询配置变更历史，常用于追踪模板或构建配置的修改记录。

### 查询修改历史

```bash
# 用 tc-search.py 查看审计事件（自动解析版本号）
python $SKILL_DIR/scripts/tc-search.py audit 模板或构建配置ID

# 原始 API（需要自行解析 settingsChange.internalId 中的版本号）
powershell -ExecutionPolicy Bypass -Command "& '$TC_Q' -Path 'audit?locator=buildType:(id:模板或构建配置ID),action:build_type_template_edit_settings,count:50,start:0'"
```

> 版本号在 `relatedEntities.entity[type=settingsChange].internalId` 中，格式 `template:btNNNNN|fromVer|toVer`。
> comment 字段表示变更类型："runners of '...' were updated" = 步骤修改，"parameters of '...' were updated" = 参数修改。

### 定位指定版本的审计事件

```bash
# 列出审计事件（含版本号解析）
python $SKILL_DIR/scripts/tc-search.py audit 模板ID

# 过滤指定版本
python $SKILL_DIR/scripts/tc-search.py audit 模板ID --version 55
```

### 查询审计事件详情
```bash
powershell -ExecutionPolicy Bypass -Command "& '$TC_Q' -Path 'audit/id:审计事件ID'"
```

> 审计详情接口返回的字段与列表接口相同，不包含 before/after 参数差异。
> 要看具体改了什么，使用下方"查看配置版本差异"章节的 `settingsDiffView` 方式。

### 查看配置版本差异（版本 diff）

使用 `tc-diff.py` 脚本一键获取两个版本之间的配置差异。脚本自动：
- 从 `settingsDiffView.html` 提取 before/after XML
- 检测并解码嵌入的 base64 脚本（如 `PRE_DEPLOY_B64`、`APOLLO_B64`），输出可读 diff
- 输出标准 unified diff 格式

**完整流程：审计事件 → diff**

```bash
# 第一步：查审计记录，拿到版本号
python $SKILL_DIR/scripts/tc-search.py audit 模板ID
```

```bash
# 第二步：用 tc-diff.py 输出可读 diff
python $SKILL_DIR/scripts/tc-diff.py 模板ID 64 65

# 构建配置（非模板）需指定 --type
python $SKILL_DIR/scripts/tc-diff.py 构建配置ID 10 11 --type buildType

# 不解码 base64，输出原始 diff
python $SKILL_DIR/scripts/tc-diff.py 模板ID 64 65 --raw
```

> **注意**：ID 使用 REST API 外部 ID（如 `FlinkDeployK8SImageGradleTemplate`），不是审计 `internalId` 中的 `btNNNNN`。
> `--type` 默认 `template`，构建配置改动用 `--type buildType`。

### 按时间过滤审计记录

TeamCity 2020.1.x 的 audit locator **不支持 `sinceDate`**。
适配方式：用 `count`+`start` 分页拉取，本地按 `timestamp` 字段过滤：
```bash
powershell -ExecutionPolicy Bypass -Command "& '$TC_Q' -Path 'audit?locator=buildType:(id:模板ID),action:build_type_template_edit_settings,count:50,start:0'"
```
timestamp 格式为 `yyyyMMddTHHmmss+时区`（如 `20260101T000000+0800`），在本地做时间范围比较。

---

## 模板导出与导入

使用 `tc-export.py` 和 `tc-import.py` 实现模板/构建配置的完整导出导入，支持当前版本和历史任意版本。

### 导出（tc-export.py）

```bash
# 导出当前版本（通过 REST API，含 inherited 标记）
python $SKILL_DIR/scripts/tc-export.py 模板ID -o template_current.json

# 导出历史版本（通过 settingsDiffView XML → JSON 转换）
python $SKILL_DIR/scripts/tc-export.py 模板ID --version 65 -o template_v65.json

# 构建配置（非模板）
python $SKILL_DIR/scripts/tc-export.py 构建配置ID --type buildType -o build_current.json
```

输出 JSON 包含：`meta`（元信息）、`parameters`、`steps`、`features`、`triggers`、`settings`、`vcs-root-entries`、`agent-requirements`。

> **当前版本** vs **历史版本**的区别：
> - 当前版本：REST API 返回全部参数（含 inherited），导入时自动过滤
> - 历史版本：XML 只包含模板自身定义的参数，天然不含 inherited

### 导入（tc-import.py）

```bash
# 预览（不执行修改）
python $SKILL_DIR/scripts/tc-import.py 目标模板ID template_v65.json --dry-run

# 执行导入（--yes 跳过交互确认，非交互环境必须加此参数）
python $SKILL_DIR/scripts/tc-import.py 目标模板ID template_v65.json --yes

# 只导入指定组件
python $SKILL_DIR/scripts/tc-import.py 目标模板ID template_v65.json --only parameters,steps --yes
```

导入行为：
- **整体替换**：每个组件（参数、步骤等）整体 PUT，目标中未包含的项会被删除
- **inherited 参数自动过滤**：REST API 导出的 JSON 含 inherited 参数，导入时自动排除
- **VCS root entries 不导入**：跨环境时 VCS root ID 可能不同，需手动处理
- 导入前**必须先 --dry-run 确认**

### 典型场景

```bash
# 回滚到历史版本
python $SKILL_DIR/scripts/tc-export.py 模板ID --version 60 -o rollback.json
python $SKILL_DIR/scripts/tc-import.py 模板ID rollback.json --dry-run
python $SKILL_DIR/scripts/tc-import.py 模板ID rollback.json --yes
```

---

## 模板导入交付物

将导出的模板打包为独立交付物，可脱离 skill 环境在任意 Windows/Linux 机器上执行导入。

### 生成交付物

```bash
# 1. 导出模板（当前或历史版本）
python $SKILL_DIR/scripts/tc-export.py 模板ID --version 65 -o template_v65.json

# 2. 打包为交付物目录
python $SKILL_DIR/scripts/tc-package.py template_v65.json -o $SKILL_DIR/artifact
```

生成目录结构：
```
artifact/<模板ID>-v<版本>-<日期>/
├── README.md          # 使用说明（含 Windows/Linux 命令示例）
├── template.json      # 模板配置数据
├── import.sh          # Linux 导入脚本（依赖 curl + python3）
└── import.ps1         # Windows 导入脚本（依赖 curl.exe + python）
```

### 交付物使用

```bash
# Linux
./import.sh -u http://tc.example.com:8111 -U admin -p password -t 目标模板ID --dry-run

# Windows
.\import.ps1 -TcUrl http://tc.example.com:8111 -Username admin -Password password -TargetId 目标模板ID -DryRun
```

> 交付物完全独立，只需 curl + python。详细说明见交付物内 README.md。

---

## 模板/构建配置修改

模板和构建配置共用 `buildTypes` 端点。修改前**必须 GET 当前状态 → 确认范围 → 执行 → 验证**。

> **PUT all 会覆盖该类别下的所有内容**。优先用单个资源的 PUT，避免误删。

### 参数 CRUD

```bash
# 查看所有参数
powershell -ExecutionPolicy Bypass -Command "& '$TC_Q' -Path 'buildTypes/id:模板ID/parameters'"

# 查看单个参数
powershell -ExecutionPolicy Bypass -Command "& '$TC_Q' -Path 'buildTypes/id:模板ID/parameters/参数名'"

# 修改单个参数值（最常用，安全）
powershell -ExecutionPolicy Bypass -Command "& '$TC_Q' -Path 'buildTypes/id:模板ID/parameters/参数名' -Method PUT -Body '{\"name\":\"参数名\",\"value\":\"新值\"}'"

# 新增一个参数
powershell -ExecutionPolicy Bypass -Command "& '$TC_Q' -Path 'buildTypes/id:模板ID/parameters' -Method POST -Body '{\"name\":\"新参数名\",\"value\":\"参数值\"}'"

# 删除一个参数
powershell -ExecutionPolicy Bypass -Command "& '$TC_Q' -Path 'buildTypes/id:模板ID/parameters/参数名' -Method DELETE"

# 整体替换所有参数（危险：会删除未包含的参数）
powershell -ExecutionPolicy Bypass -Command "& '$TC_Q' -Path 'buildTypes/id:模板ID/parameters' -Method PUT -Body '{\"property\":[{\"name\":\"参数1\",\"value\":\"值1\"},{\"name\":\"参数2\",\"value\":\"值2\"}]}'"
```

参数 JSON 格式：
- 单个参数：`{"name":"参数名","value":"参数值"}`
- 参数列表：`{"property":[{"name":"参数名","value":"参数值"}, ...]}`

### 构建步骤 CRUD

步骤通过 `id`（如 `RUNNER_1380`）标识，新增步骤时 TC 自动分配 ID。

```bash
# 查看所有步骤（含内部属性）
powershell -ExecutionPolicy Bypass -Command "& '$TC_Q' -Path 'buildTypes/id:模板ID/steps?fields=step(id,name,type,properties(property(name,value)))'"

# 查看单个步骤
powershell -ExecutionPolicy Bypass -Command "& '$TC_Q' -Path 'buildTypes/id:模板ID/steps/步骤ID'"

# 修改单个步骤（整个步骤 JSON 替换）
powershell -ExecutionPolicy Bypass -Command "& '$TC_Q' -Path 'buildTypes/id:模板ID/steps/步骤ID' -Method PUT -Body '{\"id\":\"步骤ID\",\"name\":\"步骤名\",\"type\":\"simpleRunner\",\"properties\":{\"property\":[{\"name\":\"script.content\",\"value\":\"echo hello\"},{\"name\":\"teamcity.step.mode\",\"value\":\"default\"},{\"name\":\"use.custom.script\",\"value\":\"true\"}]}}'"

# 新增一个步骤（追加到末尾）
powershell -ExecutionPolicy Bypass -Command "& '$TC_Q' -Path 'buildTypes/id:模板ID/steps' -Method POST -Body '{\"name\":\"新步骤\",\"type\":\"simpleRunner\",\"properties\":{\"property\":[{\"name\":\"script.content\",\"value\":\"echo new step\"},{\"name\":\"teamcity.step.mode\",\"value\":\"default\"},{\"name\":\"use.custom.script\",\"value\":\"true\"}]}}'"

# 删除一个步骤
powershell -ExecutionPolicy Bypass -Command "& '$TC_Q' -Path 'buildTypes/id:模板ID/steps/步骤ID' -Method DELETE"

# 整体替换所有步骤（危险：会删除未包含的步骤，且决定执行顺序）
powershell -ExecutionPolicy Bypass -Command "& '$TC_Q' -Path 'buildTypes/id:模板ID/steps' -Method PUT -Body '{\"step\":[...]}'"
```

> **提示**：修改步骤脚本时，先 GET 当前步骤拿到完整 JSON，修改 `script.content` 后整体 PUT 回去。
> 常用步骤类型：`simpleRunner`（命令行）、`gradle-runner`、`Maven2`、`jetbrains_powershell`。

### 特性 / 触发器 / 设置 CRUD

操作方式与步骤相同，将路径中 `steps` 替换为 `features`、`triggers` 或 `settings`：

```bash
# 查看
powershell -ExecutionPolicy Bypass -Command "& '$TC_Q' -Path 'buildTypes/id:模板ID/features'"
powershell -ExecutionPolicy Bypass -Command "& '$TC_Q' -Path 'buildTypes/id:模板ID/triggers'"
powershell -ExecutionPolicy Bypass -Command "& '$TC_Q' -Path 'buildTypes/id:模板ID/settings'"

# 新增（POST）/ 修改（PUT）/ 删除（DELETE）— 同步骤模式
# 设置修改使用 text/plain：
powershell -ExecutionPolicy Bypass -Command "& '$TC_Q' -Path 'buildTypes/id:模板ID/settings/设置名' -Method PUT -Body '新值' -ContentType 'text/plain'"
```

---

## Agent 管理

### 列出所有 Agent
```bash
powershell -ExecutionPolicy Bypass -Command "& '$TC_Q' -Path 'agents?fields=agent(id,name,connected,enabled,authorized)'"
```

### 查看 Agent 详情
```bash
powershell -ExecutionPolicy Bypass -Command "& '$TC_Q' -Path 'agents/id:AgentID?fields=id,name,connected,enabled,ip,properties(property(name,value))'"
```

---

## 用户相关查询

> 以下查询需要知道当前用户名，从 config.env 的 TC_USER 获取：
> `powershell -Command "(Get-Content ~/.claude/skill-config/teamcity/config.env | Select-String 'TC_USER=').Line -replace 'TC_USER=',''"`

### 我触发的最近构建
```bash
powershell -ExecutionPolicy Bypass -Command "& '$TC_Q' -Path 'builds?locator=user:(username:用户名),count:10&fields=build(id,buildTypeId,number,status,state,startDate,finishDate)'"
```

### 正在运行的构建
```bash
powershell -ExecutionPolicy Bypass -Command "& '$TC_Q' -Path 'builds?locator=state:running&fields=build(id,buildTypeId,status,state,percentageComplete,branchName)'"
```

### 最近失败的构建
```bash
powershell -ExecutionPolicy Bypass -Command "& '$TC_Q' -Path 'builds?locator=status:FAILURE,count:10&fields=build(id,buildTypeId,number,status,statusText,startDate)'"
```

