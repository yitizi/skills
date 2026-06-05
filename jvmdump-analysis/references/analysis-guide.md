# JVM Heap Dump 分析参考

Eclipse MAT + jhat 双工具对照手册。先按三段式工作流建立证据，再按技术栈选择查询模板。

## 目录

- 工具链（MAT + jhat）
- 命令 / OQL 对照表
- jhat OQL 查询模板
- jhat OQL 踩坑
- MAT 踩坑
- Flink / fabric8 watch 泄漏判断
- 真实案例：fabric8 #3186
- 报告模板

---

## 工具链

### Eclipse MAT

下载安装：https://eclipse.dev/mat/downloads.php（需 JDK 17+）

**首次使用先发现路径**（PATH 通常没有，常见安装位置散乱）：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/find_mat.ps1 -DumpPath <dump路径>
```

脚本输出 `MAT_HOME`，并扫描 dump 目录已有的 `.index` / `_Leak_Suspects.zip` / 报告 HTML——**已有的优先复用，不要重 parse**（大 dump 重 parse 要十几分钟）。

```bash
# 命令行跑 Leak Suspects 报告
ParseHeapDump.bat dump.hprof org.eclipse.mat.api:suspects

# 命令行跑 System Overview
ParseHeapDump.bat dump.hprof org.eclipse.mat.api:overview

# 自定义 XML 报告
ParseHeapDump.bat dump.hprof custom_report.xml
```

输出 ZIP 在 dump 同目录。

MAT 内存：dump 大小 × 1.5 ~ 2。在 `MemoryAnalyzer.ini` 中设置 `-Xmx`。

保留 unreachable 对象（让 MAT 也看 garbage）：

```
# 方法一：MAT 配置文件加
-Dorg.eclipse.mat.parser.keep_unreachable_objects=true

# 方法二：Preferences → Memory Analyzer → Keep Unreachable Objects

# 重要：改配置后必须删除 dump 旁边的 .index 文件，重新 parse
```

> 不同 MAT 版本/安装方式行为不一致。验证方法：开启后重 parse，跑 OQL count 对比 jhat 是否一致。

### jhat

JDK 8 自带，JDK 9+ 已移除。需保留一个 JDK 8 环境。

```bash
jhat -J-Xmx8g -port 7401 dump.hprof
```

Windows 也可用 tools.jar 直接启动：

```powershell
& 'C:\path\to\jdk8\bin\java.exe' -Xmx8g -cp 'C:\path\to\jdk8\lib\tools.jar' com.sun.tools.hat.Main -port 7401 'D:\path\heap.dump'
```

jhat 内存经验：

| Dump 大小 | 建议 `-J-Xmx` | 说明 |
|-----------|---------------|------|
| < 200MB | 2g | 一般足够 |
| 200MB - 500MB | 4g | 常见中等 dump |
| 500MB - 1GB | 8g | OQL 可能需要数分钟 |
| > 1GB | 优先 MAT | jhat 性能和稳定性差 |

同一 PowerShell 会话管理 jhat 生命周期：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/run_jhat_session.ps1 `
  -JdkHome 'C:\path\to\jdk8' `
  -DumpPath 'D:\path\heap.dump' `
  -QueryFile '.\queries\count.oql','.\queries\wcm.oql' `
  -Format rows -OutputDir '.\out'
```

常用端点：

| URL | 用途 |
|-----|------|
| `http://localhost:7401/` | 类列表 |
| `http://localhost:7401/oql/` | OQL 控制台 |
| `http://localhost:7401/oql/?query=...` | 程序化 OQL |

关闭 jhat：`taskkill //F //PID <PID>`（Windows）/ `kill <PID>`（Linux），不要 ctrl-c。

---

## 命令 / OQL 对照表

### 计数

| 任务 | MAT OQL | jhat OQL |
|------|---------|----------|
| 类实例数 | `SELECT * FROM <fqn>` 看 Total | `select count(heap.objects("<fqn>"))` |
| histogram | histogram 面板 `.*pattern.*` | 网页 → All Classes |
| 含 garbage 总数 | 需 `keep_unreachable=true` | 默认就含 |
| 仅 reachable | 默认就是 | 需 `livepaths(o).hasMoreElements()` 过滤 |

### 字段访问

| 任务 | MAT OQL | jhat OQL |
|------|---------|----------|
| 取字段 | `o.field.value`（基本类型需 `.value`） | `o.field`（直接） |
| 字符串拼接 | 不支持 `+`（只做数字加）；用多列 `SELECT a AS x, b AS y` | `"a=" + a + ", b=" + b` |
| 布尔判断 | `WHERE o.flag = true` | `if (o.flag == true)` |
| 字符串模糊 | `WHERE toString(o.s) like ".*foo.*"` | `if (o.s.toString().indexOf("foo") >= 0)` |
| 遍历 | 不能直接 var/while；用 `FROM OBJECTS (...)` 包一层 | 直接 var/while |

### 引用追溯

| 任务 | MAT | jhat |
|------|-----|------|
| 谁引用我 | GUI → Path To GC Roots / Merge Shortest Paths | `referrers(obj)` |
| 我引用谁 | GUI → List Objects → with outgoing refs | `referees(obj)` |
| GC root 路径 | GUI 可视化探索 | `livepaths(obj)` |
| Retained Heap | 默认有，histogram 列 | 无 |

### 批处理

| 任务 | MAT | jhat |
|------|-----|------|
| 命令行跑查询 | 自定义 XML 报告 | `curl --data-urlencode 'query=...'` |
| 输出格式 | HTML / CSV / TXT | HTML（要剥 tag，用 `run_oql.py --format rows`） |
| 适合自动化 | 好 | 勉强 |

---

## jhat OQL 查询模板

### PowerShell 调用方式

PowerShell 中不要把含双引号的 OQL 直接写成 `--query "heap.objects(\"org.X\")"`。PowerShell 会剥掉引号，导致 `ClassNotFoundException`。

优先用 stdin 或 query file：

```powershell
@'
var cnt = 0;
var objs = heap.objects("org.example.SomeClass");
while (objs.hasMoreElements()) { cnt++; objs.nextElement(); }
cnt;
'@ | python scripts/run_oql.py --base-url http://127.0.0.1:7401 --format rows
```

`run_oql.py` 输出格式：

| 参数 | 用途 |
|------|------|
| `--format html` | 原样 HTML，人工调试 |
| `--format rows` | 抽取表行，管道后处理 |
| `--format json` | 二维数组，Python/jq 处理 |
| `--query-base64` | 避免 shell quoting |

### 对象计数

```javascript
var cnt = 0;
var objs = heap.objects("全.限.定.类.名");
while (objs.hasMoreElements()) { cnt++; objs.nextElement(); }
cnt;
```

### WebSocket URL 分桶

```javascript
var map = {};
var wss = heap.objects(
  "org.apache.flink.kubernetes.shaded.okhttp3.internal.ws.RealWebSocket"
);
while (wss.hasMoreElements()) {
    var ws = wss.nextElement();
    var url = "";
    try { url = ws.originalRequest.url.url.toString(); } catch(e) {}
    var key = url.indexOf("configmaps") >= 0 ? "ConfigMap" :
              url.indexOf("pods") >= 0 ? "Pod" : "Other";
    map[key] = (map[key] || 0) + 1;
}
map;
```

### WebSocket URL 明细

```javascript
var out = [];
var wss = heap.objects(
  "org.apache.flink.kubernetes.shaded.okhttp3.internal.ws.RealWebSocket"
);
while (wss.hasMoreElements()) {
    var ws = wss.nextElement();
    try { out.push(ws.originalRequest.url.url.toString()); }
    catch(e) { out.push("ERR|" + e); }
}
out;
```

PowerShell 后处理：

```powershell
$rows = Get-Content .\out\websocket-url.txt
$rows | Group-Object {
    if ($_ -like '*configmaps*') { 'ConfigMap' }
    elseif ($_ -like '*pods*') { 'Pod' }
    else { 'Other' }
} | Select-Object Name,Count
```

### WatchConnectionManager 生命周期分类

```javascript
var out = [];
var wcms = heap.objects(
  "io.fabric8.kubernetes.client.dsl.internal.WatchConnectionManager"
);
while (wcms.hasMoreElements()) {
    var w = wcms.nextElement();
    var deleg = "?";
    try {
        if (w.watcher && w.watcher.delegate)
            deleg = classof(w.watcher.delegate).name;
    } catch(e) { deleg = "err"; }
    var fc = "?", st = "?", rp = "?", baseop = "?";
    try { fc = w.forceClosed.value; } catch(e) {}
    try { st = w.started.value; } catch(e) {}
    try { rp = w.reconnectPending.value; } catch(e) {}
    try { baseop = classof(w.baseOperation).name; } catch(e) {}
    out.push(
      "deleg=" + deleg + "|baseop=" + baseop +
      "|forceClosed=" + fc + "|started=" + st +
      "|reconnPending=" + rp
    );
}
out;
```

### WebSocket 关闭状态

```javascript
var closed = 0, open = 0;
var wss = heap.objects(
  "org.apache.flink.kubernetes.shaded.okhttp3.internal.ws.RealWebSocket"
);
while (wss.hasMoreElements()) {
    var ws = wss.nextElement();
    try { if (ws.enqueuedClose) closed++; else open++; } catch(e) {}
}
"closed=" + closed + " open=" + open;
```

### 引用链追踪

```javascript
// 按类取第一个实例的 referrers
var obj = heap.objects("目标类名").nextElement();
var refs = referrers(obj);
var out = [];
while (refs.hasMoreElements()) { out.push(classof(refs.nextElement()).name); }
out;
```

按对象 ID 追踪（不要用 `select ... from referrers(...)`，jhat 不稳定）：

```javascript
var obj = heap.findObject("0x12345678");
var refs = referrers(obj);
var out = [];
while (refs.hasMoreElements()) { out.push(classof(refs.nextElement()).name); }
out;
```

### 强引用路径样本

`heap.livepaths()` 大 dump 极慢，只对样本跑，`includeWeak=false` 降噪：

```javascript
var obj = heap.findObject("0x12345678");
var paths = heap.livepaths(obj, false);
paths;
```

解释规则：
- 样本 `livepaths(obj, false)` 返回的强引用路径 → `[事实]`
- 推广到全部同类对象 → `[推断]`
- 全量 retained heap / dominator → 换 MAT

### resourceVersion 分析

```javascript
var rvMap = {};
var wcms = heap.objects(
  "io.fabric8.kubernetes.client.dsl.internal.WatchConnectionManager"
);
while (wcms.hasMoreElements()) {
    var w = wcms.nextElement();
    try { var rv = w.resourceVersion.value.toString(); rvMap[rv] = (rvMap[rv] || 0) + 1; }
    catch(e) {}
}
rvMap;
```

### 陌生类字段探查

```javascript
var obj = heap.objects("目标类名").nextElement();
var refs = referees(obj);
var out = [];
while (refs.hasMoreElements()) { out.push(classof(refs.nextElement()).name); }
out;
```

---

## jhat OQL 踩坑

| 错误写法 | 正确写法 | 原因 |
|----------|----------|------|
| `w.watcher.clazz.name` | `classof(w.watcher).name` | jhat 不支持反射式类名访问 |
| `w.forceClosed` | `w.forceClosed.value` | AtomicBoolean 对象本身 vs 内部值 |
| PowerShell `--query "heap.objects(\"org.X\")"` | stdin 或 `--query-file` | PowerShell 剥双引号 |
| `select ... from referrers(heap.findObject(...))` | JS 块 + while | jhat 对该写法支持不稳定 |
| 手写未编码 URL | `urllib.parse.quote(query, safe='')` | `+` `&` `=` 被 HTTP 误解析 |
| `&submit=Execute` | 不添加 | jhat API 不需要 |

---

## MAT 踩坑（按痛苦排序）

1. **默认丢 garbage**：分析 WebSocket/HTTP client 类问题时，单看 MAT 会得出"无累积"的错误结论。不确定时先用 jhat 数一遍对比。

2. **OQL 不能字符串拼接**：`+` 只做数字加法。要拼字符串得返回多列 `SELECT a AS x, b AS y`。

3. **boolean 字段的 `.value` 陷阱**：基本类型字段有时要加 `.value`，有时不要——取决于字段类型，试错最快。

4. **index 缓存不自动失效**：改了配置（如 `keep_unreachable_objects`）后必须删 dump 旁的 `.index` 文件重 parse。

5. **Leak Suspects 误导**：按 retained heap 排序，找的是"持有最多"的对象，不一定是"问题最严重"的。MyBatis cache 49MB 永远排前两位但完全无害。

6. **dump 文件大小 ≠ live heap**：1GB hprof 可能只有 200MB live heap。报告里两个口径要分清。

---

## Flink / fabric8 watch 泄漏判断

只在 dump 中出现以下类时使用本节：

| 类 | 用途 |
|----|------|
| `o.a.f.k.shaded.okhttp3.internal.ws.RealWebSocket` | OkHttp WebSocket |
| `o.a.f.k.shaded.okhttp3.OkHttpClient` | OkHttp Client |
| `io.fabric8.k.c.dsl.internal.WatchConnectionManager` | fabric8 watch 管理器 |
| `o.a.f.k.kubeclient.resources.KubernetesPodsWatcher` | Flink Pod watcher |
| `o.a.f.k.kubeclient.resources.KubernetesConfigMapWatcher` | Flink ConfigMap watcher |

判定要点：
- ConfigMap watch 路径：少量活跃 WCM 内部累积大量已关闭 WebSocket → reconnect 后旧 WS 未释放
- Pod watch 路径：大量已 `forceClosed=1` 的 WCM 仍在 heap → close 后引用链未释放
- 版本归因必须谨慎：确认 Flink/fabric8 版本 + 对象路径 + 字段状态 + 引用链都匹配后才能提 issue

---

## 真实案例：fabric8 #3186 双工具差异

dump：Flink 1.13 JM，1GB hprof（同一份文件）

| 指标 | MAT 默认 | jhat | 差值 |
|------|----------|------|------|
| Total objects | 3,603,808 | 13,592,530 | 9.99M |
| RealWebSocket | 191 | 2,057 | 1,866 |
| OkHttpClient | 384 | 2,250 | 1,866 |
| WatchConnectionManager | 191 | 191 | 0 |
| KubernetesPodsWatcher | 183 | 183 | 0 |

**规律**：稳定持有的类（WCM、Watcher）两边一致；短生命周期 reconnect 对象（WebSocket、OkHttpClient）jhat 多很多——多出来的是"已 close 但 GC 还没扫到"的 garbage。

jhat 深入发现：ConfigMap WS 路径 1,675 个，平均每 ConfigMap WCM 背 209 个旧 WS——fabric8 #3186 reconnect 套娃明显。

- 单看 MAT → 漏掉 fabric8 #3186 这条线（路径 A "几乎消失"），**错**
- 单看 jhat → 没有 retained heap，看不出 stale WCM 才是稳态泄漏，**不全**
- 双工具对账 → 区分"真泄漏"（191 个 reachable WCM）和"garbage 累积"（1,866 个 GC 待收 WS）

---

## 报告模板

````markdown
## 背景

- Dump: [文件路径]
- 大小: [文件大小] / Live heap: [MAT 报告的 live used heap]
- 工具: MAT [版本] + jhat (JDK 8)
- 目标: [分析目标]

## 双工具对账

| 指标 | MAT 值 | jhat 值 | 差值 | 解读 |
|------|--------|---------|------|------|
| [类名] | [MAT-reachable] | [jhat-all] | N | [garbage / 一致 / 解释] |

> 差值 > 10% 的行需重点分析。

## 关键事实

| 证据 | 工具 | OQL/操作 | 结果 | 等级 |
|------|------|----------|------|------|
| ... | MAT/jhat | ... | ... | [事实] |

## 引用链

```text
异常对象
  -> 直接持有者
    -> 业务对象
      -> GC root 或仍需追踪
```

## 泄漏分类

- **真泄漏**（reachable，GC 救不了）：[列出] → 需改代码/升级
- **garbage 累积**（GC 能救但跟不上）：[列出] → 可调 GC / 降低分配速率

## 结论

- `[事实]` ...
- `[推断]` ...
- `[猜测]` ...

## 建议

- 继续查询: ...
- 临时缓解: ...
- 修复路径: ...（标 `[待验证]` 如未查官方 issue）
````

---

## OQL 查询成本分级

| 级别 | 耗时 | 类型 | 实际经验 |
|------|------|------|----------|
| 轻量 | 秒 ~ 10s | 类计数、基本字段读取 | 1GB dump 上仍秒级 |
| 中等 | 分钟 | 字段分桶、URL 分组、状态汇总 | 1GB dump 上 1-3 分钟 |
| **高成本** | 10 分钟+ 或超时 | `heap.livepaths()`、深度 `referrers`、跨类全量 | **1GB dump 上 900s 仍可能超时** |

**真实教训**：1GB dump 跑 `ref_samples.oql`（含 livepaths 全量样本）900 秒未完成。

**推荐执行顺序**：
1. 先跑内置 self-check OQL（轻量）→ 定位异常类
2. 跑该类的中等查询（字段分桶、状态分类）
3. 取异常对象的 ID（如 `0x12345678`）
4. **只对单个 ID** 跑 `heap.livepaths()` / 深度 `referrers()`

**批量执行风险**：使用 `run_jhat_session.ps1` 时务必加 `-ContinueOnError`，否则一个高成本查询超时会让整个批次报失败（即使前面查询已落盘）。

## 离线环境的版本/issue 标注

无法访问 JIRA/GitHub 时，所有外部修复路径建议必须标 `[待验证]`：

```markdown
- `[推断]` 行为与 fabric8 watch reconnect 套娃模式一致
- `[待验证]` 升级到 fabric8 5.5.0+（Flink 1.14+）可能解决，需查官方 release notes 核验
```

不要在离线环境给出"已知 bug XXX"的肯定结论。

## 工具边界

- jhat 不提供 retained heap / dominator tree；需 MAT 验证
- MAT 默认不含 garbage；需 jhat 或 `keep_unreachable_objects` 验证
- dump 只能证明快照状态，不能证明事件时序
- JIRA/GitHub issue 修复路径必须查官方来源核验，未核验标 `[待验证]`
