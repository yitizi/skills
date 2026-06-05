# JVM Dump Analysis Skill

让 AI Agent 使用 Eclipse MAT + jhat 双工具对 JVM heap dump 做 OOM、内存泄漏和 garbage 累积分析，输出带证据等级的报告。

## 核心理念

**单工具结论不可信，必须双工具对账。** MAT 默认丢 unreachable garbage，jhat 没有 retained heap——两个工具看到的不是同一份现实。

## 功能

- Eclipse MAT + jhat 三段式分析：MAT 主分析 → jhat 对账 → 交叉锚定
- 自动发现 MAT 安装路径和已有报告（`find_mat.ps1`）
- 内置高风险类 self-check OQL（OkHttp/fabric8/Finalizer/Socket/DirectBuffer）
- MAT histogram + jhat counts 自动对账（`reconcile.py`）
- jhat 批量执行支持 `-ContinueOnError` 和成功/失败汇总
- OQL 查询成本分级（轻量秒级 → 中等分钟级 → 高成本 10 分钟+）
- 区分"真泄漏"（reachable，GC 救不了）和"garbage 累积"（GC 能救但跟不上）
- 强制 `[事实]`/`[推断]`/`[猜测]`/`[待验证]` 证据等级标注

## ⚠ Windows 编码

本 skill 所有文档为 **UTF-8 无 BOM**。Windows PowerShell 5.1 默认按 GBK 读会乱码：

```powershell
Get-Content -LiteralPath '<file>' -Encoding UTF8
```

PowerShell 7（pwsh）默认 UTF-8，无需处理。AI Agent 自己读文件不受影响。

## 目录结构

```text
skills/jvmdump-analysis/
├── SKILL.md                          # Skill 入口（双工具方法论）
├── README.md                         # 本文件
├── agents/
│   └── openai.yaml
├── references/
│   └── analysis-guide.md             # 详细参考（OQL 模板、对照表、踩坑、案例）
├── queries/                          # 内置 OQL 查询
│   ├── README.md
│   ├── selfcheck_high_risk_counts.oql
│   ├── finalizer_socket_counts.oql
│   └── directbuffer_summary.oql
└── scripts/
    ├── find_mat.ps1                  # MAT 路径发现 + 已有报告复用
    ├── run_oql.py                    # jhat OQL 执行
    ├── run_jhat_session.ps1          # jhat 生命周期管理（带 -ContinueOnError）
    └── reconcile.py                  # MAT vs jhat 对账表生成
```

## 前置要求

- **Eclipse MAT**（1.15+）：用于 retained heap、dominator tree、leak suspects。需 JDK 17+
- **JDK 8**：用于运行 jhat（JDK 9+ 已移除）
- **Python 3**：用于 `run_oql.py` 和 `reconcile.py`
- JVM heap dump 文件（`.hprof` / `.dump`）

## 安装

```bash
# Claude Code（项目级）
cp -r skills/jvmdump-analysis .claude/skills/jvmdump-analysis

# Claude Code（全局）
cp -r skills/jvmdump-analysis ~/.claude/skills/jvmdump-analysis

# Codex
cp -r skills/jvmdump-analysis ~/.codex/skills/jvmdump-analysis
```

## 推荐使用流程

```bash
# 1. 发现 MAT 路径 + 检查 dump 目录已有报告
powershell -File scripts/find_mat.ps1 -DumpPath D:\dump\heap.hprof

# 2. jhat 高风险类轻量计数（秒级）
#    推荐用 -QueryDir 加载整个目录的所有 .oql，比 -QueryFile 更可靠
powershell -File scripts/run_jhat_session.ps1 `
    -JdkHome 'C:\Java\jdk8' -DumpPath 'D:\dump\heap.hprof' `
    -QueryDir queries `
    -Xmx 8g -OutputDir ./out -ContinueOnError

# 3. MAT 跑 leak suspects（如已有 .index 直接 GUI 加载）
& "$MAT_HOME\ParseHeapDump.bat" D:\dump\heap.hprof org.eclipse.mat.api:suspects

# 4. 对账
python scripts/reconcile.py --mat mat_histogram.csv --jhat ./out/selfcheck_high_risk_counts.txt
```

## 脚本参数速查

### run_jhat_session.ps1

| 参数 | 说明 |
|------|------|
| `-JdkHome` | **JDK 8 根目录**（不是 jhat.exe），需含 `bin\java.exe` 和 `lib\tools.jar` |
| `-DumpPath` | hprof / dump 文件 |
| `-QueryDir` | **推荐**。目录路径，加载目录内所有 `*.oql` |
| `-QueryFile` | 单个 .oql 路径，或逗号合并的字符串 `"a.oql,b.oql"`。注意：`powershell -File` 不识别 PS 数组字面量，必须用单字符串 |
| `-Xmx` | jhat 堆大小，按 dump 估算：2g(<200MB) / 4g(200-500MB) / 8g(500MB-1GB) / 12g+(>1GB) |
| `-OutputDir` | 结果保存目录，文件名 `<查询名>.{txt|json|html}` |
| `-Format` | `html` / `rows` / `json`（默认 rows） |
| `-QueryTimeoutSec` | 单查询超时（默认 300s） |
| `-ContinueOnError` | **必须显式开**，否则一个慢查询失败让全批次报错 |
| `-PidFile` | 写 jhat PID 到文件（外部清理用） |
| `-Help` | 完整帮助 |

`-Help` 看完整说明。脚本 `finally` 会强制 kill jhat 并输出成功/失败汇总。

### reconcile.py

```bash
python scripts/reconcile.py \
    --mat <histogram.csv|html> \
    --jhat <jhat_counts.txt> \
    [--threshold-pct 10] \
    [--only-jhat-classes] \
    [--output reconcile.md]
```

输出 Markdown 表（类名、MAT 数、jhat 数、差值、Shallow、Retained、解读），差异 ≥ 阈值的类标 ⚠。

### find_mat.ps1

```powershell
powershell -File scripts/find_mat.ps1 [-DumpPath <hprof>]
```

搜索 PATH + 常见安装路径，输出 `MAT_HOME`。带 `-DumpPath` 时检查 dump 目录已有 `.index` / `_Leak_Suspects.zip` / 报告 HTML，提示**优先复用，避免重 parse**。

## 自然语言示例

| 你说 | AI 做 |
|------|------|
| "分析这个 JVM dump 为什么 OOM" | find_mat → self-check OQL → MAT suspects → reconcile.py → 三段式报告 |
| "帮我写 OQL 查 RealWebSocket 分桶" | 读取参考模板，生成适配类名的 OQL |
| "这些 WCM 是不是泄漏" | 双工具对账，区分真泄漏 vs garbage 累积 |
| "MAT 和 jhat 数字对不上" | reconcile.py 自动表 + 数据模型差异解释 |
| "运行 jhat 慢查询超时" | 提示用 `-ContinueOnError`，分阶段：先 count 后路径 |
