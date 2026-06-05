#!/usr/bin/env python3
"""atl-bitbucket: Bitbucket Server / Data Center CLI (REST API v1.0).

Bitbucket Server (formerly Stash) uses path /rest/api/1.0/... — different from
Bitbucket Cloud. Cloud users should NOT use this script (endpoints differ).

Repo notation:
  All repo-scoped commands take a single positional <PROJECT/REPO> argument
  (slash-separated), e.g.  RDC/auth-service.

子命令（v1 主要功能）:
  list-projects [--limit N]                                 列项目
  list-repos PROJECT [--limit N]                            项目下 repo
  list-prs PROJECT/REPO [--state OPEN|MERGED|DECLINED|ALL]  PR 列表
  get-pr PROJECT/REPO PR_ID                                 PR 详情
  get-pr-diff PROJECT/REPO PR_ID [--out FILE]               PR diff
  get-pr-changes PROJECT/REPO PR_ID                         PR 文件变更列表
  get-pr-activities PROJECT/REPO PR_ID                      PR 评论 + 活动
  add-pr-comment PROJECT/REPO PR_ID --text TEXT             加 PR 评论
  list-branches PROJECT/REPO [--filter STR] [--limit N]     branch 列表
  list-commits PROJECT/REPO [--branch B] [--limit N]        commit 列表
  get-commit PROJECT/REPO SHA                               commit 详情
  browse PROJECT/REPO [--path P] [--at REF]                 列目录
  get-file PROJECT/REPO --path P [--at REF] [--out FILE]    读文件内容

凭据/配置走 atl-query.ps1（service=bitbucket）。
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
from urllib.parse import quote


# ====== atl-query.ps1 wrapper ======


def _find_atl_query() -> str:
    here = Path(__file__).resolve().parent
    p = here / "atl-query.ps1"
    if not p.exists():
        raise SystemExit(f"atl-query.ps1 not found next to {__file__}")
    return str(p)


def _ps_escape(s: str) -> str:
    return s.replace("'", "''")


def call_api(
    path: str,
    *,
    method: str = "GET",
    body: str | None = None,
    body_file: str | None = None,
    content_type: str = "application/json",
) -> tuple[int, str, str]:
    atl_query = _find_atl_query()
    cleanup_path: str | None = None
    if body and not body_file:
        tmp = tempfile.NamedTemporaryFile(suffix=".json", mode="w", encoding="utf-8", delete=False)
        try:
            tmp.write(body)
            tmp.close()
            body_file = tmp.name
            cleanup_path = tmp.name
        except Exception:
            tmp.close()
            os.unlink(tmp.name)
            raise

    cmd = (
        f"& '{_ps_escape(atl_query)}' -Service bitbucket -Path '{_ps_escape(path)}' -Method {method}"
        + (f" -ContentType '{_ps_escape(content_type)}'" if content_type != "application/json" else "")
        + (f" -BodyFile '{_ps_escape(body_file)}'" if body_file else "")
    )
    try:
        proc = subprocess.run(
            ["powershell", "-ExecutionPolicy", "Bypass", "-NoProfile", "-Command", cmd],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        return proc.returncode, proc.stdout or "", proc.stderr or ""
    finally:
        if cleanup_path:
            try:
                os.unlink(cleanup_path)
            except OSError:
                pass


def call_api_json(path: str, **kw) -> Any:
    rc, stdout, stderr = call_api(path, **kw)
    if rc != 0:
        raise SystemExit(f"API call failed (exit {rc}): {stderr}\n{stdout}")
    text = stdout.strip()
    if text.startswith("﻿"):
        text = text[1:]
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise SystemExit(f"Failed to parse JSON: {e}\nRaw: {text[:500]}")


def call_api_text(path: str, *, accept: str = "text/plain") -> str:
    """Call API expecting non-JSON text response (e.g. diff, raw file).
    Uses curl directly for streaming + correct Accept header."""
    config = _read_config()
    base = config.get("BITBUCKET_URL", "")
    if not base:
        raise SystemExit("BITBUCKET_URL not configured. Run atl-credential.ps1 -Action setup.")
    url = f"{base.rstrip('/')}/{path.lstrip('/')}"
    cmd = ["curl", "-s", "-S", "--netrc", "-H", f"Accept: {accept}", "-w", "\n%{http_code}", url]
    proc = subprocess.run(cmd, capture_output=True)  # bytes
    if proc.returncode != 0:
        raise SystemExit(f"curl failed (exit {proc.returncode}): "
                         f"{proc.stderr.decode('utf-8', errors='replace')}")
    body = proc.stdout
    # Last line is HTTP code (we appended \n%{http_code})
    nl_idx = body.rfind(b"\n")
    if nl_idx >= 0:
        http_code = body[nl_idx + 1:].decode("ascii", errors="replace").strip()
        body = body[:nl_idx]
    else:
        http_code = "?"
    if http_code.startswith(("4", "5")):
        snippet = body[:500].decode("utf-8", errors="replace")
        raise SystemExit(f"HTTP {http_code}: {snippet}")
    return body.decode("utf-8", errors="replace")


def call_api_binary_to_file(path: str, out_path: Path) -> int:
    """Stream binary response directly to file via curl -o. Returns size in bytes."""
    config = _read_config()
    base = config.get("BITBUCKET_URL", "")
    if not base:
        raise SystemExit("BITBUCKET_URL not configured.")
    url = f"{base.rstrip('/')}/{path.lstrip('/')}"
    cmd = ["curl", "-s", "-S", "--netrc", "-L", "-o", str(out_path), "-w", "%{http_code}", url]
    proc = subprocess.run(cmd, capture_output=True)
    if proc.returncode != 0:
        raise SystemExit(f"curl failed (exit {proc.returncode}): "
                         f"{proc.stderr.decode('utf-8', errors='replace')}")
    http_code = proc.stdout.decode("ascii", errors="replace").strip()
    if http_code.startswith(("4", "5")):
        snippet = ""
        if out_path.exists():
            try:
                snippet = out_path.read_bytes()[:500].decode("utf-8", errors="replace")
            except Exception:
                pass
        raise SystemExit(f"HTTP {http_code}: {snippet}")
    return out_path.stat().st_size if out_path.exists() else 0


def _read_config() -> dict:
    cfg = Path.home() / ".claude" / "skill-config" / "atlassian" / "config.env"
    out: dict[str, str] = {}
    if not cfg.exists():
        return out
    import re
    for line in cfg.read_text(encoding="utf-8", errors="replace").splitlines():
        m = re.match(r"^([A-Z_]+)=(.+)$", line.strip())
        if m:
            out[m.group(1)] = m.group(2).strip()
    return out


def _split_repo(spec: str) -> tuple[str, str]:
    """Parse 'PROJECT/REPO' positional argument."""
    if "/" not in spec:
        raise SystemExit(f"Expected PROJECT/REPO, got '{spec}'")
    parts = spec.split("/", 1)
    if not parts[0] or not parts[1]:
        raise SystemExit(f"Expected non-empty PROJECT/REPO, got '{spec}'")
    return parts[0], parts[1]


# ====== Subcommands ======


def cmd_list_projects(args: argparse.Namespace) -> int:
    data = call_api_json(f"rest/api/1.0/projects?limit={args.limit}")
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0
    values = (data or {}).get("values", [])
    print(f"{'KEY':<15} {'ID':<8} {'TYPE':<10} NAME")
    print("-" * 80)
    for p in values:
        print(f"{p.get('key', '?'):<15} {p.get('id', '?'):<8} "
              f"{p.get('type', '?'):<10} {p.get('name', '?')}")
    print(f"\nTotal: {data.get('size', '?') if data else 0}  "
          f"isLastPage: {data.get('isLastPage') if data else '?'}")
    return 0


def cmd_list_repos(args: argparse.Namespace) -> int:
    data = call_api_json(f"rest/api/1.0/projects/{args.project}/repos?limit={args.limit}")
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0
    values = (data or {}).get("values", [])
    print(f"{'SLUG':<30} {'STATE':<12} NAME")
    print("-" * 80)
    for r in values:
        print(f"{r.get('slug', '?'):<30} {r.get('state', '?'):<12} {r.get('name', '?')}")
    print(f"\nTotal: {(data or {}).get('size', 0)}")
    return 0


def cmd_list_prs(args: argparse.Namespace) -> int:
    project, repo = _split_repo(args.repo)
    state_filter = ""
    if args.state and args.state != "ALL":
        state_filter = f"&state={args.state}"
    data = call_api_json(
        f"rest/api/1.0/projects/{project}/repos/{repo}/pull-requests"
        f"?limit={args.limit}{state_filter}"
    )
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0
    values = (data or {}).get("values", [])
    print(f"{'ID':<6} {'STATE':<10} {'AUTHOR':<20} {'BR.SRC':<25} -> {'BR.DST':<25}  TITLE")
    print("-" * 130)
    for pr in values:
        author = ((pr.get("author") or {}).get("user") or {}).get("displayName", "?")
        from_ref = (pr.get("fromRef") or {}).get("displayId", "?")
        to_ref = (pr.get("toRef") or {}).get("displayId", "?")
        print(f"{pr.get('id', '?'):<6} {pr.get('state', '?'):<10} "
              f"{author[:18]:<20} {from_ref[:23]:<25} -> {to_ref[:23]:<25}  "
              f"{(pr.get('title') or '')[:60]}")
    print(f"\nTotal: {(data or {}).get('size', 0)}")
    return 0


def cmd_get_pr(args: argparse.Namespace) -> int:
    project, repo = _split_repo(args.repo)
    data = call_api_json(f"rest/api/1.0/projects/{project}/repos/{repo}/pull-requests/{args.pr_id}")
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0
    if not data:
        raise SystemExit("Empty response")
    print(f"=== PR #{data.get('id')} ({data.get('state')}) ===")
    print(f"  Title:    {data.get('title')}")
    print(f"  Author:   {((data.get('author') or {}).get('user') or {}).get('displayName', '?')}")
    print(f"  From:     {(data.get('fromRef') or {}).get('displayId', '?')} "
          f"@ {(data.get('fromRef') or {}).get('latestCommit', '?')[:8]}")
    print(f"  To:       {(data.get('toRef') or {}).get('displayId', '?')} "
          f"@ {(data.get('toRef') or {}).get('latestCommit', '?')[:8]}")
    print(f"  Created:  {data.get('createdDate')}")
    print(f"  Updated:  {data.get('updatedDate')}")
    reviewers = data.get("reviewers", [])
    if reviewers:
        print("  Reviewers:")
        for r in reviewers:
            user = (r.get("user") or {}).get("displayName", "?")
            status = r.get("status", "?")
            approved = r.get("approved", False)
            print(f"    - {user}  status={status}  approved={approved}")
    desc = data.get("description", "")
    if desc:
        print(f"\nDescription:\n{desc}")
    print(f"\nWeb URL: {(data.get('links') or {}).get('self', [{}])[0].get('href', '')}")
    return 0


def cmd_get_pr_diff(args: argparse.Namespace) -> int:
    project, repo = _split_repo(args.repo)
    # Bitbucket Server returns unified diff as text/plain when Accept matches.
    text = call_api_text(
        f"rest/api/1.0/projects/{project}/repos/{repo}/pull-requests/{args.pr_id}/diff",
        accept="text/plain",
    )
    if args.out:
        out = Path(args.out)
        out.write_text(text, encoding="utf-8")
        print(f"OK wrote diff -> {out} ({len(text)} chars)")
    else:
        print(text)
    return 0


def cmd_get_pr_changes(args: argparse.Namespace) -> int:
    project, repo = _split_repo(args.repo)
    data = call_api_json(
        f"rest/api/1.0/projects/{project}/repos/{repo}/pull-requests/{args.pr_id}/changes?limit={args.limit}"
    )
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0
    values = (data or {}).get("values", [])
    print(f"{'TYPE':<10} {'PATH'}")
    print("-" * 80)
    for c in values:
        path = ((c.get("path") or {}).get("toString")) or "?"
        print(f"{c.get('type', '?'):<10} {path}")
    print(f"\nTotal: {(data or {}).get('size', 0)}")
    return 0


def cmd_get_pr_activities(args: argparse.Namespace) -> int:
    project, repo = _split_repo(args.repo)
    data = call_api_json(
        f"rest/api/1.0/projects/{project}/repos/{repo}/pull-requests/{args.pr_id}/activities?limit={args.limit}"
    )
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0
    values = (data or {}).get("values", [])
    for act in values:
        action = act.get("action", "?")
        user = (act.get("user") or {}).get("displayName", "?")
        when = act.get("createdDate", "")
        comment = act.get("comment", {}) or {}
        text = comment.get("text", "")
        print(f"--- {action}  by {user}  ({when})")
        if text:
            # show first 300 chars
            print(f"    {text[:300]}")
            if len(text) > 300:
                print(f"    ... ({len(text)} chars total)")
        print()
    print(f"Total: {(data or {}).get('size', 0)}")
    return 0


def cmd_add_pr_comment(args: argparse.Namespace) -> int:
    project, repo = _split_repo(args.repo)
    if args.file:
        text = Path(args.file).read_text(encoding="utf-8")
    elif args.text:
        text = args.text
    else:
        raise SystemExit("provide --text or --file")
    payload = {"text": text}
    rc, stdout, stderr = call_api(
        f"rest/api/1.0/projects/{project}/repos/{repo}/pull-requests/{args.pr_id}/comments",
        method="POST",
        body=json.dumps(payload, ensure_ascii=False),
    )
    if rc != 0:
        print(f"ERROR: {stderr}\n{stdout}", file=sys.stderr)
        return 1
    text_out = stdout.strip()
    if text_out.startswith("﻿"):
        text_out = text_out[1:]
    data = json.loads(text_out) if text_out else {}
    print(f"OK comment id={data.get('id')} added to PR #{args.pr_id}")
    return 0


def cmd_list_branches(args: argparse.Namespace) -> int:
    project, repo = _split_repo(args.repo)
    filter_q = f"&filterText={quote(args.filter)}" if args.filter else ""
    data = call_api_json(
        f"rest/api/1.0/projects/{project}/repos/{repo}/branches?limit={args.limit}{filter_q}"
    )
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0
    values = (data or {}).get("values", [])
    print(f"{'DEFAULT':<8} {'TYPE':<8} {'COMMIT':<10} BRANCH")
    print("-" * 80)
    for b in values:
        is_default = "*" if b.get("isDefault") else ""
        print(f"{is_default:<8} {b.get('type', '?'):<8} "
              f"{(b.get('latestCommit') or '?')[:8]:<10} {b.get('displayId', '?')}")
    print(f"\nTotal: {(data or {}).get('size', 0)}")
    return 0


def cmd_list_commits(args: argparse.Namespace) -> int:
    project, repo = _split_repo(args.repo)
    until = f"&until={quote(args.branch)}" if args.branch else ""
    data = call_api_json(
        f"rest/api/1.0/projects/{project}/repos/{repo}/commits?limit={args.limit}{until}"
    )
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0
    values = (data or {}).get("values", [])
    print(f"{'SHA':<10} {'AUTHOR':<25} {'DATE':<22} MESSAGE")
    print("-" * 130)
    for c in values:
        sha = (c.get("id") or "")[:8]
        author = (c.get("author") or {}).get("name", "?")
        ts = c.get("authorTimestamp", 0)
        from datetime import datetime, timezone
        dt = datetime.fromtimestamp(ts / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if ts else "?"
        msg = (c.get("message") or "").splitlines()[0] if c.get("message") else ""
        print(f"{sha:<10} {author[:23]:<25} {dt:<22} {msg[:60]}")
    print(f"\nTotal: {(data or {}).get('size', 0)}")
    return 0


def cmd_get_commit(args: argparse.Namespace) -> int:
    project, repo = _split_repo(args.repo)
    data = call_api_json(f"rest/api/1.0/projects/{project}/repos/{repo}/commits/{args.sha}")
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0
    if not data:
        raise SystemExit("Empty response")
    from datetime import datetime, timezone
    ts = data.get("authorTimestamp", 0)
    dt = datetime.fromtimestamp(ts / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if ts else "?"
    print(f"=== Commit {data.get('id', '?')[:8]} ===")
    print(f"  Author:    {(data.get('author') or {}).get('name', '?')}")
    print(f"  Date:      {dt}")
    parents = data.get("parents", [])
    if parents:
        print(f"  Parents:   {', '.join(p.get('id', '')[:8] for p in parents)}")
    print(f"\n{data.get('message', '')}")
    return 0


def cmd_browse(args: argparse.Namespace) -> int:
    project, repo = _split_repo(args.repo)
    path_segment = args.path.strip("/") if args.path else ""
    at_q = f"?at={quote(args.at)}" if args.at else ""
    data = call_api_json(
        f"rest/api/1.0/projects/{project}/repos/{repo}/browse/{path_segment}{at_q}"
    )
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0
    if not data:
        raise SystemExit("Empty response")
    children = (data.get("children") or {}).get("values", [])
    if children:
        print(f"{'TYPE':<8} {'SIZE':<10} PATH")
        print("-" * 80)
        for c in children:
            t = c.get("type", "?")
            size = c.get("size") or "-"
            cpath = ((c.get("path") or {}).get("toString")) or "?"
            print(f"{t:<8} {str(size):<10} {cpath}")
        print(f"\nTotal: {(data.get('children') or {}).get('size', 0)}")
    else:
        # File content (lines array)
        lines_obj = (data.get("lines") or [])
        for line_obj in lines_obj:
            print(line_obj.get("text", ""))
    return 0


def cmd_get_file(args: argparse.Namespace) -> int:
    project, repo = _split_repo(args.repo)
    path_segment = args.path.strip("/")
    at_q = f"?at={quote(args.at)}" if args.at else ""
    # Bitbucket Server raw endpoint
    url_path = f"projects/{project}/repos/{repo}/raw/{path_segment}{at_q}"
    if args.out:
        out = Path(args.out)
        size = call_api_binary_to_file(url_path, out)
        print(f"OK wrote -> {out} ({size} bytes)")
    else:
        text = call_api_text(url_path, accept="text/plain")
        print(text)
    return 0


# ====== argparse ======


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="atl-bitbucket: Bitbucket Server CLI (REST v1.0). "
                    "Repo args are PROJECT/REPO, e.g. RDC/auth-service."
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("list-projects", help="list all projects")
    sp.add_argument("--limit", type=int, default=100)
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_list_projects)

    sp = sub.add_parser("list-repos", help="list repos in a project")
    sp.add_argument("project", help="project key, e.g. RDC")
    sp.add_argument("--limit", type=int, default=100)
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_list_repos)

    sp = sub.add_parser("list-prs", help="list pull requests")
    sp.add_argument("repo", help="PROJECT/REPO, e.g. RDC/auth-service")
    sp.add_argument("--state", choices=("OPEN", "MERGED", "DECLINED", "ALL"), default="OPEN")
    sp.add_argument("--limit", type=int, default=50)
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_list_prs)

    sp = sub.add_parser("get-pr", help="PR detail")
    sp.add_argument("repo")
    sp.add_argument("pr_id", type=int)
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_get_pr)

    sp = sub.add_parser("get-pr-diff", help="PR unified diff")
    sp.add_argument("repo")
    sp.add_argument("pr_id", type=int)
    sp.add_argument("--out", help="write to file (recommended for large diffs)")
    sp.set_defaults(func=cmd_get_pr_diff)

    sp = sub.add_parser("get-pr-changes", help="PR file change list")
    sp.add_argument("repo")
    sp.add_argument("pr_id", type=int)
    sp.add_argument("--limit", type=int, default=200)
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_get_pr_changes)

    sp = sub.add_parser("get-pr-activities", help="PR comments + activity")
    sp.add_argument("repo")
    sp.add_argument("pr_id", type=int)
    sp.add_argument("--limit", type=int, default=50)
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_get_pr_activities)

    sp = sub.add_parser("add-pr-comment", help="add comment to PR")
    sp.add_argument("repo")
    sp.add_argument("pr_id", type=int)
    sp.add_argument("--text", help="comment text")
    sp.add_argument("--file", help="read text from file")
    sp.set_defaults(func=cmd_add_pr_comment)

    sp = sub.add_parser("list-branches", help="list branches")
    sp.add_argument("repo")
    sp.add_argument("--filter", help="filter substring")
    sp.add_argument("--limit", type=int, default=100)
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_list_branches)

    sp = sub.add_parser("list-commits", help="list commits")
    sp.add_argument("repo")
    sp.add_argument("--branch", help="branch name (default: default branch)")
    sp.add_argument("--limit", type=int, default=50)
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_list_commits)

    sp = sub.add_parser("get-commit", help="commit detail")
    sp.add_argument("repo")
    sp.add_argument("sha", help="commit SHA (full or short)")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_get_commit)

    sp = sub.add_parser("browse", help="browse directory tree")
    sp.add_argument("repo")
    sp.add_argument("--path", default="", help="path within repo (default: root)")
    sp.add_argument("--at", help="ref / branch / commit (default: HEAD of default branch)")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_browse)

    sp = sub.add_parser("get-file", help="read file content (raw)")
    sp.add_argument("repo")
    sp.add_argument("--path", required=True, help="file path within repo")
    sp.add_argument("--at", help="ref / branch / commit (default: HEAD)")
    sp.add_argument("--out", help="write to file (recommended for large/binary files)")
    sp.set_defaults(func=cmd_get_file)

    return p


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
