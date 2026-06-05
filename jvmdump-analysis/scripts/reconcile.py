#!/usr/bin/env python3
"""MAT histogram + jhat OQL count 对账表生成器。

输入：
  - MAT 导出的 histogram CSV/HTML（class_name, num_instances, shallow_size, retained_size）
  - jhat selfcheck_high_risk_counts.oql 的 rows 输出（每行 "fqn = N"）

输出：
  Markdown 对账表，列：类名、MAT 数、jhat 数、差值、差异比例、解读
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from html.parser import HTMLParser
from pathlib import Path


def parse_jhat_rows(path: Path) -> dict[str, int]:
    """解析 jhat OQL 输出，支持多种格式：

    1. 逐行：每行 'fqn = N'（如 OQL 用 print 或循环输出 td）
    2. 单行数组：'[ fqn1 = N1, fqn2 = N2, ... ]'（OQL 直接返回 JS 数组时常见）
    3. tab 分隔：run_oql.py --format rows 多列输出
    4. 混合：以上任意组合

    策略：用全局正则扫所有 'fqn = (number|N/A)' 模式，不依赖行结构。
    FQN 必须含至少一个点（避免误匹配 JS 字面量如 'count = 5'）。
    """
    result: dict[str, int] = {}
    text = path.read_text(encoding="utf-8")
    # FQN: 字母开头 + [字母数字下划线点$/] + 至少一个点 + 后续标识符段，
    # 末尾可选 0+ 个 [] 表示数组类型（如 java.lang.String[]）
    pattern = re.compile(
        r"([A-Za-z_][\w$/]*(?:\.[A-Za-z_][\w$/]*)+(?:\[\])*)\s*=\s*(\d+|N/A)\b"
    )
    for m in pattern.finditer(text):
        cls = m.group(1)
        val = m.group(2)
        if val == "N/A":
            result[cls] = -1
        else:
            # 后出现的覆盖前面（一般 OQL 不会重复输出同一类，覆盖也无害）
            result[cls] = int(val)
    return result


# MAT 数字格式前缀：approximate/minimum 标记，需剥掉
# - ">=" 出现在 Retained Heap 列，表示"至少 N 字节"（dominator 未精确计算）
# - "~" / "≈" 表示估算
# - ">" / "<" / "≥" / "≤" 是一般比较符号
_MAT_NUM_PREFIX_RE = re.compile(r"^\s*(?:>=|<=|[>≥<≤~≈])\s*")


def _parse_mat_number(text):
    """解析 MAT 数字单元格，返回 int 或 None。

    支持：
      - "5,482"        -> 5482
      - ">= 24,156,592" -> 24156592
      - "~100,000"     -> 100000
      - "3322867"      -> 3322867
      - ""/"-"/"N/A"/None -> None
    """
    if text is None:
        return None
    s = text.strip() if isinstance(text, str) else str(text).strip()
    if not s or s in ("-", "N/A", "n/a"):
        return None
    # 剥掉前缀（>=, <=, ~, ≈, >, <, ≥, ≤）
    s = _MAT_NUM_PREFIX_RE.sub("", s).strip()
    # 去千分位逗号和空格
    s = s.replace(",", "").replace(" ", "").replace("\xa0", "")  # \xa0 = nbsp
    if not s:
        return None
    try:
        return int(s)
    except ValueError:
        # 可能是浮点（某些 MAT 视图带单位时会有 1.5 等），尝试 float->int
        try:
            return int(float(s))
        except ValueError:
            return None


def parse_mat_csv(path: Path) -> dict[str, dict]:
    """MAT 导出 CSV histogram，必须含 'Class Name' 和 'Objects' 列。
    可选: 'Shallow Heap', 'Retained Heap'。"""
    result: dict[str, dict] = {}
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        # 容错：列名匹配
        cls_key = obj_key = shallow_key = retained_key = None
        for k in reader.fieldnames or []:
            kn = k.strip().lower()
            if "class" in kn and "name" in kn:
                cls_key = k
            elif kn in ("objects", "num_instances", "instances"):
                obj_key = k
            elif "shallow" in kn:
                shallow_key = k
            elif "retained" in kn:
                retained_key = k
        if not cls_key or not obj_key:
            raise SystemExit(f"MAT CSV 缺少 Class Name / Objects 列。已知列: {reader.fieldnames}")

        for row in reader:
            cls = row[cls_key].strip()
            cnt = _parse_mat_number(row.get(obj_key))
            if cnt is None:
                continue
            entry = {"count": cnt}
            shallow = _parse_mat_number(row.get(shallow_key)) if shallow_key else None
            retained = _parse_mat_number(row.get(retained_key)) if retained_key else None
            if shallow is not None:
                entry["shallow"] = shallow
            if retained is not None:
                entry["retained"] = retained
            result[cls] = entry
    return result


class MatHtmlParser(HTMLParser):
    """从 MAT HTML histogram 报告抽取 class_name -> {count, shallow, retained}。

    每个 <td> 收集两份文本：
      - full_text: <td> 内所有文本拼接（向后兼容）
      - first_link_text: <td> 内第一个 <a> 的文本（用于类名抽取，
        避免 MAT 把 "All objects" / "with outgoing references" 等导航链接拼到 FQN 后面）
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[dict]] = []  # 每个 cell 是 {full, first_link}
        self._in_tr = False
        self._in_td = False
        self._in_a = False
        self._cell_seen_link = False
        self._row: list[dict] = []
        self._cell_full: list[str] = []
        self._cell_first_link: list[str] = []

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag == "tr":
            self._in_tr = True
            self._row = []
        elif self._in_tr and tag in ("td", "th"):
            self._in_td = True
            self._cell_full = []
            self._cell_first_link = []
            self._cell_seen_link = False
            self._in_a = False
        elif self._in_td and tag == "a" and not self._cell_seen_link:
            self._in_a = True

    def handle_data(self, data):
        if self._in_td:
            self._cell_full.append(data)
            if self._in_a:
                self._cell_first_link.append(data)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag == "a" and self._in_a:
            self._in_a = False
            self._cell_seen_link = True
        elif tag in ("td", "th") and self._in_td:
            full = " ".join("".join(self._cell_full).split())
            first_link = " ".join("".join(self._cell_first_link).split())
            self._row.append({"full": full, "first_link": first_link})
            self._in_td = False
        elif tag == "tr" and self._in_tr:
            if self._row:
                self.rows.append(self._row)
            self._in_tr = False


# MAT 在类名单元格里通常会附加导航链接，常见的尾缀
_MAT_NAV_SUFFIXES = (
    "All objects",
    "with outgoing references",
    "with incoming references",
    "Show as Histogram",
    "Show in Dominator Tree",
    "Path To GC Roots",
)
# FQN 模式：用于从 cell 全文兜底提取（无 <a> 标签时）
# 支持：包名.类名、内部类（$）、数组（[]）、多维数组（[][]）
_FQN_RE = re.compile(r"[A-Za-z_$][\w$.]*(?:\.[A-Za-z_$][\w$.]*)+(?:\[\])*")
# 严格 FQN：完整匹配，用于校验"看起来像类名"
_FQN_FULL_RE = re.compile(r"^[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)+(?:\[\])*$")


def _looks_like_fqn(s: str) -> bool:
    """是否看起来像 Java FQN。用于过滤 MAT histogram 的 totals/footer 行
    （形如 'Total: 25 of 32,554 entries; 32,529 more'）。"""
    if not s:
        return False
    return bool(_FQN_FULL_RE.match(s))


def _extract_class_name(cell: dict) -> str:
    """从一个 MAT 类名单元格抽出干净的 FQN。

    优先级：
      1. 第一个 <a> 链接的文本（MAT 把 FQN 放在第一个链接里）
      2. 全文中第一个匹配 FQN 模式的子串
      3. 全文掐掉已知导航尾缀后剩余部分

    返回的字符串必须通过 _looks_like_fqn 校验；否则返回空串
    （由调用方跳过该行，避免把 "Total: ..." 这类汇总行当成类名）。
    """
    # 优先：第一个 <a> 文本（取第一个空格前 token，FQN 不含空格）
    first = cell.get("first_link", "").strip()
    if first:
        token = first.split()[0] if first.split() else first
        if _looks_like_fqn(token):
            return token

    full = cell.get("full", "").strip()
    if not full:
        return ""

    # 兜底 1：正则在全文里 search FQN 子串
    m = _FQN_RE.search(full)
    if m and _looks_like_fqn(m.group(0)):
        return m.group(0)

    # 兜底 2：掐已知导航尾缀后再校验
    cleaned = full
    for suffix in _MAT_NAV_SUFFIXES:
        idx = cleaned.find(suffix)
        if idx > 0:
            cleaned = cleaned[:idx].strip()
    if _looks_like_fqn(cleaned):
        return cleaned

    # 都不像 FQN：拒绝（汇总行、分页提示、空行等）
    return ""


def _cell_full(cell: dict) -> str:
    """取 cell 全文（用于数字列）。"""
    return cell.get("full", "")


def parse_mat_html(path: Path) -> dict[str, dict]:
    """MAT HTML histogram。结构假设：第一列是类名，后续列含 Objects/Shallow/Retained。"""
    parser = MatHtmlParser()
    parser.feed(path.read_text(encoding="utf-8", errors="replace"))

    result: dict[str, dict] = {}
    if not parser.rows:
        return result

    # 推测列顺序：找第一行表头（用 full 文本）
    header = [_cell_full(c).lower() for c in parser.rows[0]]
    cls_idx = next((i for i, h in enumerate(header) if "class" in h), 0)
    obj_idx = next((i for i, h in enumerate(header) if "object" in h or "instance" in h), 1)
    shallow_idx = next((i for i, h in enumerate(header) if "shallow" in h), -1)
    retained_idx = next((i for i, h in enumerate(header) if "retained" in h), -1)

    for row in parser.rows[1:]:
        if len(row) <= max(cls_idx, obj_idx):
            continue
        cls = _extract_class_name(row[cls_idx])
        if not cls:
            continue
        cnt = _parse_mat_number(_cell_full(row[obj_idx]))
        if cnt is None:
            continue
        entry = {"count": cnt}
        if shallow_idx >= 0 and shallow_idx < len(row):
            shallow = _parse_mat_number(_cell_full(row[shallow_idx]))
            if shallow is not None:
                entry["shallow"] = shallow
        if retained_idx >= 0 and retained_idx < len(row):
            retained = _parse_mat_number(_cell_full(row[retained_idx]))
            if retained is not None:
                entry["retained"] = retained
        result[cls] = entry
    return result


def parse_mat(path: Path) -> dict[str, dict]:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return parse_mat_csv(path)
    if suffix in (".html", ".htm"):
        return parse_mat_html(path)
    raise SystemExit(f"MAT 文件必须是 .csv 或 .html: {path}")


def diff_label(mat_count: int, jhat_count: int) -> str:
    """根据差异比例给出解读标签。"""
    if mat_count < 0 or jhat_count < 0:
        return "数据缺失"
    diff = jhat_count - mat_count
    if mat_count == 0:
        if jhat_count == 0:
            return "一致（均为 0）"
        return f"全部为 garbage（MAT 0, jhat {jhat_count}）"
    pct = abs(diff) / mat_count * 100
    if abs(diff) <= 5 or pct < 2:
        return "一致"
    if pct < 10:
        return f"轻微差异 ({pct:.1f}%)"
    if diff > 0:
        return f"⚠ jhat 多 {diff} ({pct:.0f}%) — 疑似 garbage 累积"
    return f"⚠ MAT 多 {abs(diff)} ({pct:.0f}%) — 异常，检查 MAT 配置"


def fmt_int(n: int) -> str:
    """实例计数（永远 >= 0），-1 当作"数据缺失"显示 N/A。"""
    if n < 0:
        return "N/A"
    return f"{n:,}"


def fmt_diff(n) -> str:
    """差值（jhat - mat）可正可负，None 表示无法计算。
    正数加 + 号便于阅读，负数自带 - 号。"""
    if n is None:
        return "-"
    if n > 0:
        return f"+{n:,}"
    if n < 0:
        return f"{n:,}"  # 自带 - 号
    return "0"


def fmt_bytes(n: int | None) -> str:
    if n is None or n < 0:
        return "-"
    if n < 1024:
        return f"{n}B"
    if n < 1024 * 1024:
        return f"{n/1024:.1f}KB"
    if n < 1024 * 1024 * 1024:
        return f"{n/1024/1024:.1f}MB"
    return f"{n/1024/1024/1024:.2f}GB"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="MAT histogram + jhat OQL count 对账表生成器"
    )
    parser.add_argument("--mat", required=True, help="MAT histogram .csv 或 .html")
    parser.add_argument("--jhat", required=True, help="jhat run_oql.py rows 输出")
    parser.add_argument("--output", help="保存 Markdown 表（默认 stdout）")
    parser.add_argument("--threshold-pct", type=float, default=10.0,
                        help="差异比例阈值（默认 10%%），超过加 ⚠ 标签")
    parser.add_argument("--only-jhat-classes", action="store_true",
                        help="只输出 jhat 文件中出现的类（过滤 MAT 全量 histogram）")
    args = parser.parse_args()

    mat_data = parse_mat(Path(args.mat))
    jhat_data = parse_jhat_rows(Path(args.jhat))

    # 解析结果健康检查 - 静默生成空表是历史 bug，必须主动告警
    if not jhat_data:
        sys.stderr.write(
            f"WARNING: parse_jhat_rows({args.jhat}) returned 0 entries.\n"
            f"  Check that the jhat output contains 'fqn = N' patterns.\n"
            f"  Common causes: OQL returned empty array, or jhat output format changed.\n"
            f"  Preview of input file (first 500 chars):\n"
            f"  ---\n"
        )
        try:
            preview = Path(args.jhat).read_text(encoding="utf-8")[:500]
            sys.stderr.write("  " + preview.replace("\n", "\n  ") + "\n  ---\n")
        except Exception as e:
            sys.stderr.write(f"  (failed to read: {e})\n")

    if not mat_data:
        sys.stderr.write(
            f"WARNING: parse_mat({args.mat}) returned 0 entries.\n"
            f"  Check that MAT histogram has 'Class Name' and 'Objects' columns.\n"
        )

    if args.only_jhat_classes:
        target_classes = set(jhat_data.keys())
    else:
        target_classes = set(mat_data.keys()) | set(jhat_data.keys())

    if not target_classes:
        sys.stderr.write(
            "ERROR: no classes to compare. Both --mat and --jhat parsed empty.\n"
        )
        return 2

    rows = []
    for cls in sorted(target_classes):
        mat_entry = mat_data.get(cls, {})
        mat_cnt = mat_entry.get("count", -1)
        jhat_cnt = jhat_data.get(cls, -1)
        rows.append({
            "class": cls,
            "mat_count": mat_cnt,
            "jhat_count": jhat_cnt,
            "diff": jhat_cnt - mat_cnt if (mat_cnt >= 0 and jhat_cnt >= 0) else None,
            "shallow": mat_entry.get("shallow"),
            "retained": mat_entry.get("retained"),
            "label": diff_label(mat_cnt, jhat_cnt),
        })

    # 输出 Markdown
    lines = [
        "| 类名 | MAT 实例数 | jhat 实例数 | 差值 | Shallow | Retained | 解读 |",
        "|------|-----------|-------------|------|---------|----------|------|",
    ]
    for r in rows:
        diff_str = fmt_diff(r["diff"])
        lines.append(
            f"| `{r['class']}` | {fmt_int(r['mat_count'])} | {fmt_int(r['jhat_count'])} | "
            f"{diff_str} | {fmt_bytes(r['shallow'])} | {fmt_bytes(r['retained'])} | {r['label']} |"
        )

    # 高风险摘要
    risky = [r for r in rows if r["diff"] is not None and r["mat_count"] > 0
             and abs(r["diff"]) / r["mat_count"] * 100 >= args.threshold_pct]
    if risky:
        lines.append("")
        lines.append(f"## ⚠ 高风险（差异 ≥ {args.threshold_pct}%）")
        lines.append("")
        for r in risky:
            lines.append(f"- `{r['class']}`: {r['label']}")

    output_text = "\n".join(lines) + "\n"
    if args.output:
        Path(args.output).write_text(output_text, encoding="utf-8")
        print(f"Wrote {args.output}", file=sys.stderr)
    else:
        sys.stdout.write(output_text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
