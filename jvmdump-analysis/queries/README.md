# 内置 OQL 查询库

按"成本"分类，建议先跑轻量查询，再按需跑昂贵查询。

## 轻量（秒级，安全默认）

| 文件 | 用途 |
|------|------|
| `selfcheck_high_risk_counts.oql` | 高风险类计数 self-check（OkHttp/fabric8/Finalizer/Socket/DirectBuffer） |
| `finalizer_socket_counts.oql` | Finalizer 队列 + Socket 类计数 |
| `directbuffer_summary.oql` | DirectByteBuffer 堆外内存统计 |

## 中等（分钟级）

调用方在外部目录写入，例如：
- WebSocket URL 分桶 / 明细
- WatchConnectionManager 生命周期分类
- resourceVersion 分布

模板见 `references/analysis-guide.md`。

## 高成本（10 分钟+，可选，只对样本运行）

| 类型 | 注意事项 |
|------|----------|
| `heap.livepaths(obj, false)` | 必须先用 `findObject` 取单个对象，不要全量遍历 |
| `referrers(obj)` 深度遍历 | 大对象图慢且耗内存 |
| 跨类全量字段读取 | 先用 count 确认规模再决定 |

> **建议工作流**：先跑 self-check + lightweight → 看数字定位类 → 取样本对象 ID → 再跑昂贵查询。

## 使用

```bash
# 单个查询
python ../scripts/run_oql.py --query-file selfcheck_high_risk_counts.oql --format rows

# 批量（推荐用 -QueryDir 加载整个目录，避开 powershell -File 数组解析坑）
powershell -ExecutionPolicy Bypass -File ../scripts/run_jhat_session.ps1 `
  -JdkHome 'C:\Java\jdk8' `
  -DumpPath 'D:\dump\heap.hprof' `
  -QueryDir . `
  -Xmx 8g `
  -OutputDir ./out `
  -ContinueOnError
```
