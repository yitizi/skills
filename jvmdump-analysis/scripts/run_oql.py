#!/usr/bin/env python3
"""执行 jhat OQL API 的小工具。"""

from __future__ import annotations

import argparse
import base64
import json
import sys
from html.parser import HTMLParser
import urllib.parse
import urllib.request
from pathlib import Path


class JhatRowsParser(HTMLParser):
    """从 jhat OQL 结果表中抽取 td 行。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self._table_depth = 0
        self._result_table_depth: int | None = None
        self._in_tr = False
        self._in_td = False
        self._row: list[str] = []
        self._cell: list[str] = []

    def _in_result_table(self) -> bool:
        return self._result_table_depth is not None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag == "table":
            self._table_depth += 1
            attrs_map = {key.lower(): value for key, value in attrs if key}
            if self._result_table_depth is None and attrs_map.get("border") == "1":
                self._result_table_depth = self._table_depth
            return

        if not self._in_result_table():
            return

        if tag == "tr":
            self._in_tr = True
            self._row = []
        elif self._in_tr and tag == "td":
            self._in_td = True
            self._cell = []

    def handle_data(self, data: str) -> None:
        if self._in_td:
            self._cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "td" and self._in_td:
            text = "".join(self._cell).strip()
            self._row.append(" ".join(text.split()))
            self._in_td = False
            self._cell = []
        elif tag == "tr" and self._in_tr:
            if self._row:
                self.rows.append(self._row)
            self._in_tr = False
            self._row = []
        elif tag == "table":
            if self._result_table_depth == self._table_depth:
                self._result_table_depth = None
            self._table_depth = max(0, self._table_depth - 1)


def load_query(args: argparse.Namespace) -> str:
    choices = [bool(args.query), bool(args.query_file), bool(args.query_base64)]
    if sum(choices) > 1:
        raise SystemExit("只能指定 --query、--query-file、--query-base64 其中一个")
    if args.query:
        return args.query
    if args.query_file:
        return Path(args.query_file).read_text(encoding="utf-8")
    if args.query_base64:
        return base64.b64decode(args.query_base64).decode("utf-8")
    if not sys.stdin.isatty():
        return sys.stdin.read()
    raise SystemExit("请通过 --query、--query-file、--query-base64 或 stdin 提供 OQL")


def build_url(base_url: str, query: str) -> str:
    encoded = urllib.parse.quote(query, safe="")
    return base_url.rstrip("/") + "/oql/?query=" + encoded


def extract_rows(html_text: str) -> list[list[str]]:
    parser = JhatRowsParser()
    parser.feed(html_text)
    return [row for row in parser.rows if not is_navigation_row(row)]


def is_navigation_row(row: list[str]) -> bool:
    normalized = [" ".join(cell.split()) for cell in row]
    return normalized == ["All Classes (excluding platform)", "OQL Help"]


def format_payload(payload: bytes, charset: str, output_format: str) -> bytes:
    if output_format == "html":
        return payload

    html_text = payload.decode(charset, errors="replace")
    rows = extract_rows(html_text)
    if output_format == "json":
        return (json.dumps(rows, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    if output_format == "rows":
        lines = ["\t".join(row) for row in rows]
        return ("\n".join(lines) + ("\n" if lines else "")).encode("utf-8")

    raise SystemExit(f"不支持的输出格式: {output_format}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="对 jhat OQL 查询做 URL 编码并调用 /oql/?query=..."
    )
    parser.add_argument("--base-url", default="http://localhost:7401")
    parser.add_argument(
        "--query",
        help="直接传入 OQL 字符串。PowerShell 中含双引号的 OQL 优先用 stdin 或 --query-file",
    )
    parser.add_argument("--query-file", help="从 UTF-8 文件读取 OQL")
    parser.add_argument("--query-base64", help="从 UTF-8 base64 字符串读取 OQL")
    parser.add_argument("--output", help="保存输出内容；默认输出到 stdout")
    parser.add_argument(
        "--format",
        choices=("html", "rows", "json"),
        default="html",
        help="输出格式。rows/json 会抽取 jhat HTML table 的 td 行",
    )
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--print-url", action="store_true", help="仅打印编码后的 URL")
    args = parser.parse_args()

    query = load_query(args).strip()
    if not query:
        raise SystemExit("OQL 不能为空")

    url = build_url(args.base_url, query)
    if args.print_url:
        print(url)
        return 0

    request = urllib.request.Request(
        url,
        headers={"User-Agent": "jvmdump-analysis-skill/1.0"},
    )
    with urllib.request.urlopen(request, timeout=args.timeout) as response:
        payload = response.read()
        charset = response.headers.get_content_charset() or "utf-8"

    payload = format_payload(payload, charset, args.format)
    if args.output:
        Path(args.output).write_bytes(payload)
    else:
        sys.stdout.write(payload.decode("utf-8" if args.format != "html" else charset, errors="replace"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
