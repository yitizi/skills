---
name: jvmdump-analysis
description: >
  JVM heap dump analysis with Eclipse MAT + jhat dual-tool cross-validation.
  OOM diagnosis, memory leak tracing, garbage accumulation detection,
  retained heap, dominator tree, OQL queries, and evidence-ranked reports.
  Use when analyzing HPROF files, writing OQL, diagnosing Kubernetes/Flink/fabric8
  memory leaks, or producing fact/inference/guess classified reports.
---

# JVM Heap Dump 分析

Eclipse MAT + jhat 双工具协同分析。**单工具结论不可信，必须对账。**

## ⚠ Windows 编码必读

### 文档（.md / .oql）

UTF-8 无 BOM。Windows PowerShell 5.1 默认按 GBK 读取，手动查看时需显式指定：

```powershell
Get-Content -LiteralPath '<file>' -Encoding UTF8
# 或临时切换控制台编码：
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
```

PowerShell 7（pwsh）默认 UTF-8，无需处理。AI Agent 自己读文件不受影响。

### PowerShell 脚本（.ps1）

**本 skill 所有 `.ps1` 脚本源码纯 ASCII**（输出也是英文）。

原因：PowerShell 5.1 执行无 BOM `.ps1` 时按系统 ANSI（中文 Windows = GBK）解析源码。若脚本含 UTF-8 中文：
- 中文字符串输出乱码
- **甚至可能破坏脚本语法**（中文 + 邻近 `` ` `` `(` 等特殊字符时，GBK 误解码会让 PowerShell 解析出错，变量赋值丢失）

这是 `powershell -File` 执行阶段的问题，`Get-Content -Encoding UTF8` 救不了。解决方案选了**脚本纯 ASCII**，避开整个坑。

## 核心立场

- 只用 MAT → 漏掉"GC 跟不上回收速率的累积 garbage"
- 只用 jhat → 被 garbage 噪音淹没，且无 retained heap / dominator tree / leak suspects
- 两个工具看到的不是同一份现实：hprof 不区分 reachable 和 garbage，这个判断由工具自己算

## 数据模型差异（一切的根源）

| 维度 | jhat | MAT 默认 |
|------|------|----------|
| 对象范围 | 全部（含 garbage） | 仅 reachable（从 GC root 走图） |
| 设计哲学 | Raw view，不擅自过滤 | 工程化视图，优化分析效率 |
| Retained Heap | 无 | 有（dominator tree 算法） |
| 大堆性能 | 差（>2GB 痛苦） | 好（索引化并行） |
| JDK 要求 | JDK 8（9+ 已移除） | JDK 17+（独立安装） |

> 实测同一份 1GB hprof：jhat 13.59M 对象 vs MAT 3.60M 对象。差出的 ~10M 是已断 GC root 但 GC 还没收的 garbage。

## 三段式工作流

```
阶段 1：MAT 主分析（工程化能力）
  1.1 ParseHeapDump 跑 leak suspects + System Overview
  1.2 Histogram 看目标类（reachable 口径）
  1.3 OQL 查 retained heap、字段值、关系
  1.4 Dominator tree 找"GC 收掉能释放最多内存"的对象

阶段 2：jhat 对账（看 garbage）
  2.1 启动 jhat，先跑 self-check 高风险类计数（轻量）
  2.2 对比 MAT 数字：差大的 → 该类有 garbage 累积，深入分析
  2.3 数字一致 → 稳态对象，按 MAT 结论走

阶段 3：交叉锚定 + 写报告
  3.1 用 reconcile.py 自动生成对账表
  3.2 区分"真泄漏（reachable，GC 救不了）" vs "garbage 累积（GC 能救但跟不上）"
  3.3 修复方向不同：真泄漏改代码/升级；garbage 累积可调 GC
```

## 必须双工具对账的类

单工具结论不可信，凡涉及以下类别必须双跑：

| 类别 | 典型类 | 原因 |
|------|--------|------|
| WebSocket / 连接池 | OkHttp RealWebSocket, OkHttpClient, Netty Channel | reconnect 产生大量短命对象 |
| HTTP/RPC client | fabric8 WatchConnectionManager, gRPC channel | watch 重建留 garbage |
| Finalizer 队列 | java.lang.ref.Finalizer, SocksSocketImpl | finalize 慢，队列堆积 |
| ByteBuffer | DirectByteBuffer | finalize 才释放 |

安全列表（通常两边数字一致，单工具足够）：主线程对象、静态单例、Spring Bean、MyBatis cache。

> 内置 self-check OQL：`$SKILL_DIR/queries/selfcheck_high_risk_counts.oql`，秒级返回上述高风险类的 jhat 计数。

## 证据等级

所有报告强制标注：

- `[事实]`：dump 查询结果直接支撑（数值、字段状态、引用关系）
- `[推断]`：由事实推出但 dump 无法直接记录
- `[猜测]`：需要 dump 之外的信息验证
- `[待验证]`：建议涉及外部 issue/版本，但当前无法核验（如离线环境）

> dump 是快照，能证明对象当前状态，不能单独证明何时、为何进入该状态。

## 工具与脚本

### 脚本路径约定

本 Skill 的脚本位于 `SKILL.md` 同级目录下。首次使用时定位 `$SKILL_DIR`：

```
# 按优先级检查：
# 1. 项目级: .claude/skills/jvmdump-analysis/
# 2. 全局 Claude: ~/.claude/skills/jvmdump-analysis/
# 3. Codex: ~/.codex/skills/jvmdump-analysis/
# 4. 源码: skills/jvmdump-analysis/
```

脚本清单：
- `$SKILL_DIR/scripts/find_mat.ps1` — MAT 安装路径发现 + 已有报告复用检查
- `$SKILL_DIR/scripts/run_oql.py` — jhat OQL 执行（URL 编码、结果抽取）
- `$SKILL_DIR/scripts/run_jhat_session.ps1` — jhat 生命周期管理（启动/查询/清理）
- `$SKILL_DIR/scripts/reconcile.py` — MAT histogram + jhat 计数 → Markdown 对账表

内置 OQL 查询：
- `$SKILL_DIR/queries/selfcheck_high_risk_counts.oql` — 高风险类计数（轻量，秒级）
- `$SKILL_DIR/queries/finalizer_socket_counts.oql` — Finalizer 队列 + Socket 类
- `$SKILL_DIR/queries/directbuffer_summary.oql` — 堆外内存统计

### MAT 命令行

**首次使用先发现 MAT 路径**（PATH 通常没有）：

```powershell
powershell -ExecutionPolicy Bypass -File $SKILL_DIR/scripts/find_mat.ps1 -DumpPath D:\dump\heap.hprof
```

输出 `MAT_HOME` 和 dump 目录已有的 MAT 报告/index（**优先复用，避免重 parse**）。

```bash
# Leak Suspects 报告
& "$MAT_HOME\ParseHeapDump.bat" dump.hprof org.eclipse.mat.api:suspects

# 自定义 XML 报告
& "$MAT_HOME\ParseHeapDump.bat" dump.hprof custom_report.xml

# 保留 unreachable 对象（需删 .index 重 parse）
# 在 MemoryAnalyzer.ini 中加: -Dorg.eclipse.mat.parser.keep_unreachable_objects=true
```

### jhat 命令行

```bash
jhat -J-Xmx8g -port 7401 dump.hprof
```

**`-Xmx` 按 dump 大小估算**：

| Dump 大小 | 建议 `-J-Xmx` |
|-----------|---------------|
| < 200MB | 2g |
| 200-500MB | 4g |
| 500MB-1GB | 8g |
| > 1GB | 12g+ 或换 MAT |

**批量执行 OQL（推荐）**：

**推荐用 `-QueryDir`**（最可靠，不受 PowerShell `-File` 参数解析坑影响）：

```powershell
powershell -ExecutionPolicy Bypass -File $SKILL_DIR/scripts/run_jhat_session.ps1 `
  -JdkHome 'C:\Java\jdk8' `
  -DumpPath 'D:\dump\heap.hprof' `
  -QueryDir "$SKILL_DIR/queries" `
  -Xmx 8g `
  -OutputDir './out' `
  -ContinueOnError
```

或用 `-QueryFile` 传逗号分隔字符串（脚本会自动拆分）：

```powershell
powershell -ExecutionPolicy Bypass -File $SKILL_DIR/scripts/run_jhat_session.ps1 `
  ... `
  -QueryFile "$SKILL_DIR/queries/selfcheck_high_risk_counts.oql,$SKILL_DIR/queries/finalizer_socket_counts.oql" `
  ...
```

> **`-ContinueOnError` 必须显式开启**，否则一个慢查询超时会让整个批次报失败（即使前面查询已落盘）。

参数说明：
- `-JdkHome`：**JDK 8 根目录**（不是 jhat.exe 路径），需含 `bin\java.exe` 和 `lib\tools.jar`
- `-QueryDir`：**推荐**，目录内所有 `*.oql` 都加载
- `-QueryFile`：单个 .oql 路径，或多个用**逗号合并的字符串**（不是 PS 数组）。原因：`powershell -File` 不解析数组字面量，逗号会被吞进字符串
- `-OutputDir`：输出 `<查询名>.{txt|json|html}`
- `-PidFile`：写 jhat PID 到文件（外部清理用，脚本异常退出时备用）

脚本的 `finally` 块会强制 kill jhat 进程，并输出**成功/失败查询汇总**。

### MAT vs jhat 对账

```bash
# 1. 从 MAT 导出 histogram CSV/HTML（GUI: Histogram → File → Export）
# 2. 跑 jhat self-check
python $SKILL_DIR/scripts/run_oql.py \
    --query-file $SKILL_DIR/queries/selfcheck_high_risk_counts.oql \
    --format rows > jhat_counts.txt

# 3. 生成对账表
python $SKILL_DIR/scripts/reconcile.py \
    --mat mat_histogram.csv \
    --jhat jhat_counts.txt \
    --threshold-pct 10 \
    --output reconcile.md
```

输出 Markdown 表，含 MAT/jhat 计数、差值、Shallow/Retained、自动标签（差异 ≥ 10% 加 ⚠）。

## OQL 查询成本分级

按成本三级，建议**自下而上**执行：

| 级别 | 耗时 | 类型 | 默认行为 |
|------|------|------|----------|
| 轻量 | 秒级 | 类计数、字段状态 | 默认先跑（self-check OQL） |
| 中等 | 分钟级 | 字段分桶、分组统计 | 按需跑 |
| **高成本** | 10 分钟+ | `heap.livepaths()`、深度 `referrers()` | **只对样本对象 ID 跑**，不要全量 |

> **真实教训**：1GB dump 上 `heap.livepaths()` 全量样本可能 900s 仍超时。先跑 count 定位类 → 取单个对象 ID → 再跑路径查询。

## jhat OQL 注意事项

- `classof(obj).name` 获取类名，不要用 `obj.clazz.name`
- AtomicBoolean/AtomicReference 需读内部字段：`w.forceClosed.value`
- HTTP 调用必须对 query 做 URL 编码，不要拼 `&submit=Execute`
- `referrers()` 用 JS 块遍历，不要用 `select ... from referrers(...)`
- `heap.livepaths()` 大 dump 极慢，只对单个样本跑，`includeWeak=false`
- PowerShell 中含双引号的 OQL 用 stdin 或 `--query-file`

## 输出要求

报告必须包含：

1. **Dump 背景**：文件、大小、工具版本
2. **双工具对账表**（核心，用 `reconcile.py` 生成）
3. **归因链路**：异常对象 → 持有者 → 业务组件 → GC root
4. **结论分级**：每条根因标 `[事实]`/`[推断]`/`[猜测]`/`[待验证]`
5. **区分泄漏类型**：真泄漏 vs garbage 累积，修复方向不同

> 差值 ≠ 0 时必须解释（garbage 累积还是工具配置差异）。
> JIRA/GitHub issue 修复路径必须用官方来源核验，无网络环境下标 `[待验证]`。

## 自动 self-check（推荐流程）

```bash
# 1. 发现 MAT
powershell -File $SKILL_DIR/scripts/find_mat.ps1 -DumpPath <dump>

# 2. 跑 jhat 高风险类轻量计数（秒级）
powershell -File $SKILL_DIR/scripts/run_jhat_session.ps1 \
    -JdkHome <jdk8> -DumpPath <dump> \
    -QueryFile $SKILL_DIR/queries/selfcheck_high_risk_counts.oql \
    -OutputDir ./out -ContinueOnError

# 3. 跑 MAT histogram（如已有 .index 直接 GUI 加载导出）
& "$MAT_HOME\ParseHeapDump.bat" <dump> org.eclipse.mat.api:suspects

# 4. 对账
python $SKILL_DIR/scripts/reconcile.py \
    --mat <mat_histogram.csv> --jhat ./out/selfcheck_high_risk_counts.txt
```

差异 > 10% 的类强制人工 review，深入跑中等/高成本 OQL。
