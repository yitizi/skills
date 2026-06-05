# TeamCity Skill

让 AI Agent 通过自然语言操作 TeamCity CI/CD 系统。

## 功能

- **查询**：搜索项目、构建配置、构建历史、构建日志
- **执行**：触发构建（支持指定分支和参数）、取消/停止构建
- **监控**：查看运行中的构建、构建队列、Agent 状态、失败构建
- **修改**：模板/构建配置参数、步骤、特性、触发器、设置的 CRUD
- **版本 diff**：查看配置版本差异，自动解码 base64 脚本
- **导出/导入**：导出当前或历史版本配置，导入到目标模板
- **交付物打包**：生成独立的导入交付物（含 Windows/Linux 脚本）
- **安全**：凭据通过 Windows GUI 弹窗管理，不经过终端或 AI 对话流

## 前置要求

- Windows 10/11（凭据管理脚本依赖 PowerShell + WinForms）
- Git Bash 中的 curl（需支持 `--netrc`）
- TeamCity 实例（已验证 2020.1.5+，REST API 需开启 Basic HTTP Auth）

## 目录结构

```
skills/teamcity/
├── SKILL.md                   # Skill 定义文件（AI 入口）
├── README.md                  # 本文件
└── scripts/
    ├── tc-credential.ps1      # 凭据管理脚本（Windows GUI 弹窗）
    ├── tc-query.ps1           # API 调用封装（处理认证/UTF-8/HTTP 状态）
    ├── tc-search.py           # 搜索工具（项目/模板/构建配置/审计）
    ├── tc-diff.py             # 配置版本 diff 工具
    ├── tc-export.py           # 模板导出工具（当前版本/历史版本）
    ├── tc-import.py           # 模板导入工具
    ├── tc-package.py          # 导入交付物打包工具
    └── deliverable/
        ├── import.sh          # 交付物 Linux 导入脚本模板
        └── import.ps1         # 交付物 Windows 导入脚本模板
```

## 安装

将 `skills/teamcity` 复制到目标 AI Agent 的 skills 目录：

```bash
# Claude Code（项目级）
cp -r skills/teamcity .claude/skills/teamcity

# Claude Code（全局）
cp -r skills/teamcity ~/.claude/skills/teamcity

# Codex
cp -r skills/teamcity ~/.codex/skills/teamcity
```

安装后 AI Agent 自动发现 `SKILL.md`，无需额外配置。
首次使用时会弹出 GUI 窗口引导配置凭据。

> 沙箱环境（如 Codex）可能无法弹出 GUI 窗口，需先在本地完成凭据配置：
> `powershell -ExecutionPolicy Bypass -File scripts/tc-credential.ps1 -Action setup`

### 独立使用（不依赖 Agent 基础设施）

Python 脚本支持 `--tc-url`/`--username`/`--password` 参数，可直接执行：

```bash
python scripts/tc-export.py <模板ID> --tc-url https://teamcity.example.com --username user --password pass -o export.json
python scripts/tc-import.py <目标ID> export.json --tc-url https://teamcity.example.com --username user --password pass --dry-run
```

### 验证

```powershell
# 检查配置状态
powershell -ExecutionPolicy Bypass -File scripts/tc-credential.ps1 -Action check
# 期望输出: CONFIGURED|http://your-server:8111
```

## 使用示例

| 你说 | AI 做 |
|------|------|
| "现在有什么构建在跑？" | 查询 running builds |
| "帮我搜一下河南会计相关的项目" | 按关键词搜索项目 |
| "触发 hnkj7 的生产 war 打包" | 触发指定构建 |
| "刚才那个构建失败了，看看日志" | 拉取构建日志并分析 |
| "取消队列里排队的构建" | 取消排队构建 |
| "看看所有 Agent 的状态" | 列出 Agent 连接/启用状态 |
| "更新一下 TeamCity 的登录密码" | 弹出 GUI 窗口更新凭据 |

## 凭据管理

| 操作 | 命令 |
|------|------|
| 检查状态 | `tc-credential.ps1 -Action check` |
| 首次配置 | `tc-credential.ps1 -Action setup` |
| 更新配置 | `tc-credential.ps1 -Action update` |
| 删除配置 | `tc-credential.ps1 -Action delete` |

所有操作都通过 Windows GUI 弹窗进行，密码不会出现在终端输出或 AI 对话中。

## 配置存储

```
~/.claude/skill-config/teamcity/
└── config.env                   # TC_URL, TC_USER（非敏感，AI 可读）

~/.netrc                         # 凭据（敏感，仅 curl --netrc 读取）
                                 # 支持多条 machine 记录和多行格式
```

> 配置目录路径可能因 Agent 实现不同而异，脚本通过 `$USERPROFILE/.claude/skill-config/teamcity/` 查找。

## 安全设计

```
用户输入 ──▶ Windows GUI 弹窗 ──▶ 写入两个位置
               (不经过终端)          │
                          ┌─────────┴──────────┐
                          ▼                    ▼
               ~/.claude/skill-config/     ~/.netrc
               teamcity/config.env         (密码)
               (URL, 用户名)
                          │                    │
AI 读取 config.env ◀──────┘                    │
得到 TC_URL                                    │
                                               │
AI 执行 curl --netrc "$TC_URL/..." ◀──────────┘
         ↑                            curl 自动读取
    命令中无密码，AI 只看到 API 响应
```
