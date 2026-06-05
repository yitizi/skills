#!/usr/bin/env python3
"""atl-search: JQL / CQL search with Chinese-safe handling.

Background: PowerShell 5.1 mangles UTF-8 in pipe → Python. Search results
often contain Chinese (issue summaries, page titles). This wrapper uses a
temp-file round-trip so the API response never goes through the PowerShell pipe.

子命令：
  jql 'JQL' [--fields ...] [--limit N]      Jira JQL search
  cql 'CQL' [--limit N]                     Confluence CQL search

Output formats:
  --format table  人读表格（默认）
  --format json   完整 JSON
  --format keys   仅 KEY 列表（脚本管道用）
  --format ids    仅 page id 列表（CQL 模式）
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


def _find_atl_query() -> str:
    here = Path(__file__).resolve().parent
    p = here / "atl-query.ps1"
    if not p.exists():
        raise SystemExit(f"atl-query.ps1 not found next to {__file__}")
    return str(p)


def _ps_escape(s: str) -> str:
    return s.replace("'", "''")


def call_get_json(service: str, path: str) -> dict | None:
    """GET via atl-query.ps1 + parse UTF-8 JSON.

    atl-query.ps1 uses `cmd /c type` for raw byte stdout, so subprocess capture
    preserves UTF-8 unchanged — Chinese in summaries / titles arrives intact.
    """
    atl_query = _find_atl_query()
    cmd_str = f"& '{_ps_escape(atl_query)}' -Service {service} -Path '{_ps_escape(path)}' -Method GET"
    proc = subprocess.run(
        ["powershell", "-ExecutionPolicy", "Bypass", "-NoProfile", "-Command", cmd_str],
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        text=True,
    )
    if proc.returncode != 0:
        raise SystemExit(f"API GET failed (exit {proc.returncode}): {proc.stderr}")
    text = (proc.stdout or "").strip()
    if text.startswith("﻿"):
        text = text[1:]
    if not text:
        return None
    return json.loads(text)


def post_json_to_temp(service: str, path: str, payload: dict) -> dict | None:
    """POST with JSON body via temp body-file to avoid stdin encoding issues."""
    atl_query = _find_atl_query()
    body_tmp = tempfile.NamedTemporaryFile(suffix=".json", mode="w", encoding="utf-8", delete=False)
    try:
        json.dump(payload, body_tmp, ensure_ascii=False)
        body_tmp.close()
        cmd_str = (
            f"& '{_ps_escape(atl_query)}' -Service {service} "
            f"-Path '{_ps_escape(path)}' -Method POST "
            f"-BodyFile '{_ps_escape(body_tmp.name)}'"
        )
        proc = subprocess.run(
            ["powershell", "-ExecutionPolicy", "Bypass", "-NoProfile", "-Command", cmd_str],
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            text=True,
        )
        if proc.returncode != 0:
            raise SystemExit(f"POST {path} failed: {proc.stderr}\n{proc.stdout}")
        text = (proc.stdout or "").strip()
        if text.startswith("﻿"):
            text = text[1:]
        return json.loads(text) if text else None
    finally:
        os.unlink(body_tmp.name)


# ====== Subcommands ======


def cmd_jql(args: argparse.Namespace) -> int:
    fields = (args.fields or "summary,status,assignee,priority,issuetype,updated").split(",")
    payload = {
        "jql": args.jql,
        "fields": fields,
        "maxResults": args.limit,
        "startAt": args.start,
    }
    data = post_json_to_temp("jira", "rest/api/2/search", payload)
    if not data:
        print("(empty)", file=sys.stderr)
        return 0

    if args.format == "json":
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0

    issues = data.get("issues", [])
    if args.format == "keys":
        for iss in issues:
            print(iss.get("key", ""))
        return 0

    # table
    print(f"{'KEY':<15} {'STATUS':<15} {'PRIORITY':<10} {'ASSIGNEE':<20} SUMMARY")
    print("-" * 130)
    for iss in issues:
        f = iss.get("fields", {})
        a = (f.get("assignee") or {}).get("displayName", "-")
        print(f"{iss.get('key', '?'):<15} "
              f"{(f.get('status') or {}).get('name', '?')[:13]:<15} "
              f"{(f.get('priority') or {}).get('name', '?')[:8]:<10} "
              f"{(a or '-')[:18]:<20} "
              f"{(f.get('summary') or '')[:60]}")
    print(f"\nTotal: {data.get('total', '?')} (showing {len(issues)}, start={args.start})")
    return 0


def cmd_cql(args: argparse.Namespace) -> int:
    from urllib.parse import quote
    path = (
        "rest/api/content/search"
        f"?cql={quote(args.cql)}&limit={args.limit}&start={args.start}&expand=version,space"
    )
    data = call_get_json("confluence", path)
    if not data:
        print("(empty)", file=sys.stderr)
        return 0

    if args.format == "json":
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0

    results = data.get("results", [])
    if args.format == "ids":
        for r in results:
            print(r.get("id", ""))
        return 0

    print(f"{'PAGE-ID':<15} {'SPACE':<15} {'TYPE':<8} {'VER':<5} TITLE")
    print("-" * 100)
    for r in results:
        print(f"{r.get('id', '?'):<15} "
              f"{(r.get('space') or {}).get('key', '?')[:13]:<15} "
              f"{r.get('type', '?'):<8} "
              f"v{(r.get('version') or {}).get('number', '?'):<4} "
              f"{r.get('title', '?')}")
    print(f"\nTotal: {data.get('size', '?')} (showing {len(results)}, start={args.start})")
    return 0


# ====== argparse ======


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="atl-search: JQL/CQL search with Chinese-safe handling"
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("jql", help="Jira JQL search")
    sp.add_argument("jql", help="JQL expression (quote it)")
    sp.add_argument("--fields", help="comma-separated fields (default: common)")
    sp.add_argument("--limit", type=int, default=50)
    sp.add_argument("--start", type=int, default=0)
    sp.add_argument("--format", choices=("table", "json", "keys"), default="table")
    sp.set_defaults(func=cmd_jql)

    sp = sub.add_parser("cql", help="Confluence CQL search")
    sp.add_argument("cql", help="CQL expression (quote it)")
    sp.add_argument("--limit", type=int, default=25)
    sp.add_argument("--start", type=int, default=0)
    sp.add_argument("--format", choices=("table", "json", "ids"), default="table")
    sp.set_defaults(func=cmd_cql)

    return p


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
