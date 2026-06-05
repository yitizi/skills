# Skills — AI Agent 研发工具链技能集

> 一组面向 **Claude Code / Codex** 的 `SKILL.md` 技能，让 AI Agent 用**自然语言**操作企业内网研发工具链：
> **Atlassian 协作** · **TeamCity 持续集成** · **JVM 故障诊断**。
> 专为 **Windows + 中文环境**打磨，凭据全程隔离、富格式不丢、中文不乱码。

每个技能都是独立的 `SKILL.md`，复制到 Agent 的 skills 目录即可用，首次使用弹出 GUI 引导配置凭据，无需常驻服务。

---

## 📦 技能一览

| 技能 | 一句话 | 解决什么 | 详细文档 |
|------|--------|----------|----------|
| [**atlassian**](atlassian/) | Jira + Confluence + Bitbucket（Server/DC） | 读写 Confluence 富格式、跑 Jira 全流程、看 Bitbucket PR/diff | [README](atlassian/README.md) |
| [**teamcity**](teamcity/) | TeamCity CI/CD 操作 | 触发/监控构建、改构建配置、配置版本 diff、导出导入 | [README](teamcity/README.md) |
| [**jvmdump-analysis**](jvmdump-analysis/) | JVM heap dump 双工具分析 | OOM / 内存泄漏 / garbage 累积诊断，带证据等级 | [README](jvmdump-analysis/README.md) |

---

## 🧩 atlassian — Jira + Confluence + Bitbucket

让 AI 操作 Atlassian Server / Data Center 全家桶。是 [mcp-atlassian](https://github.com/sooperset/mcp-atlassian) Tier 1+2 核心能力的精简复刻，并补上了 mcp-atlassian 没有的 **Bitbucket Server 直连**。

- **Confluence 富格式保真**：storage XHTML 直传，不走 markdown 转换，`<ac:macro>` / `<ac:expand>` / `<ac:code>` 等元素不丢失
- **本地缓存 + 版本管理**：`pull/push` 走 `.atlassian-cache/`，多轮编辑 **0 token**；push 前再次 GET 远程版本，**未变才允许覆盖**，防止冲掉别人的改动
- **Jira 全流程**：issue 查/改/流转/评论/工时/链接、JQL 搜索、development panel 反查关联 PR
- **Bitbucket Server**：PR 列表/diff/评论、branch/commit、读 repo 文件（13 个命令）

```text
"拉一下 Confluence 页面 12345 改一下" → pull → Edit 草稿 → diff → push（v20→v21）
"把 PROJ-123 流转到 Done"            → 查 transitions → transition --id N
"PROJ-123 关联了哪些 PR？"           → get-dev-info
```

## 🏗️ teamcity — CI/CD 操作

用自然语言驱动 TeamCity 的查询、执行、监控与配置变更。

- **查询/监控**：搜项目与构建配置、看构建历史/日志、running 构建、队列、Agent 状态、失败构建
- **执行**：触发构建（可指定分支/参数）、取消或停止构建
- **配置 CRUD**：模板/构建配置的参数、步骤、特性、触发器增删改
- **版本与迁移**：配置版本 diff（自动解码 base64 脚本）、导出/导入模板、打包独立**导入交付物**（含 Win/Linux 脚本）

```text
"现在有什么构建在跑？"          → 查 running builds
"触发 hnkj7 的生产 war 打包"    → 触发指定构建
"刚才那个构建失败了，看看日志"  → 拉日志并分析
```

## 🔬 jvmdump-analysis — JVM 内存诊断

用 **Eclipse MAT + jhat 双工具交叉对账**分析 heap dump。

- **核心理念：单工具结论不可信，必须对账。** MAT 默认丢 unreachable garbage，jhat 没有 retained heap——两个工具看到的不是同一份现实
- **三段式**：MAT 主分析（leak suspects / dominator tree）→ jhat 对账 → 交叉锚定，`reconcile.py` 自动生成差异表
- **内置高风险类 self-check OQL**（OkHttp / fabric8 / Finalizer / Socket / DirectBuffer）
- **区分真相**：把"真泄漏（reachable，GC 救不了）"和"garbage 累积（GC 跟不上）"分开
- **强制证据等级**：报告里每条结论标 `[事实]` / `[推断]` / `[猜测]` / `[待验证]`

```text
"分析这个 JVM dump 为什么 OOM"  → find_mat → self-check OQL → MAT suspects → reconcile → 三段式报告
"这些 WCM 是不是泄漏？"         → 双工具对账，判定真泄漏 vs garbage
"MAT 和 jhat 数字对不上"        → reconcile.py 出表 + 解释数据模型差异
```

---

## 🛡️ 共同设计（三个技能的"家规"）

- **凭据隔离，AI 不碰密码**
  - URL / 用户名 → `~/.claude/skill-config/<skill>/config.env`（非敏感，AI 可读）
  - 密码 / PAT → `~/.netrc`（仅 `curl --netrc` 读取，**命令里禁止出现明文**）
  - 录入走 **Windows GUI 弹窗**（中文界面），密码不进终端、不进对话流
- **Windows 中文安全**
  - `.ps1` 脚本源码**纯 ASCII**——避开 PowerShell 5.1 按 GBK 解析无 BOM 源码、导致中文字符串乱码甚至**破坏脚本语法**的坑
  - 文档统一 **UTF-8 无 BOM**；中文搜索走 **temp file 二步法**绕开 PowerShell pipe 编码问题
- **自然语言驱动**：你说人话，AI 选对应脚本/子命令执行，结果落文件、不污染上下文
- **无常驻服务**：纯 shell / Python 脚本，不像 MCP server 那样起独立进程；同时兼容 Claude Code（项目级 / 全局）与 Codex

---

## 🚀 安装

把对应技能目录复制到 Agent 的 skills 目录即可（以 `atlassian` 为例）：

```bash
# Claude Code（项目级）
cp -r atlassian .claude/skills/atlassian

# Claude Code（全局）
cp -r atlassian ~/.claude/skills/atlassian

# Codex
cp -r atlassian ~/.codex/skills/atlassian
```

安装后 Agent 自动发现 `SKILL.md`；首次使用会弹出 GUI 引导配置凭据。各技能的命令清单、参考文档与踩坑记录见各自目录下的 `README.md` 与 `references/`。

## 🧰 环境要求

- **Windows 10/11**（凭据 GUI 依赖 PowerShell + WinForms）
- **PowerShell 5.1+** 或 **pwsh 7+**
- **Git Bash 的 curl**（需支持 `--netrc`）
- **Python 3.8+**
- 各技能的服务端：Atlassian Server/DC、TeamCity（2020.1.5+，开启 Basic HTTP Auth）、Eclipse MAT 1.15+ 与 JDK 8（jhat）

## 🗂️ 仓库结构

```text
skills/
├── atlassian/          # Jira + Confluence + Bitbucket 技能
├── teamcity/           # TeamCity CI/CD 技能
├── jvmdump-analysis/   # JVM heap dump 分析技能
├── gstack/             # 第三方工具集（独立 git 仓库，已被 gitignore，不属于本技能集）
├── CLAUDE.md           # 给 Claude Code 的工作区说明（含 git 边界）
└── README.md           # 本文件
```

> **关于 `gstack/`**：它是第三方仓库（`github.com/garrytan/gstack`），有自己独立的 git 历史，被本仓库 `.gitignore` 排除，**不是本技能集的一部分**。它的介绍见 [`gstack/README.md`](gstack/README.md)。
