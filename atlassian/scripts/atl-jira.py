#!/usr/bin/env python3
"""atl-jira: Jira CLI (Server / DC, REST API v2).

子命令（Tier 1+2）：
  get-issue <KEY> [--fields ...]                  读单个 issue
  search --jql 'JQL' [--fields ...]               JQL 搜索
  add-comment <KEY> --text TEXT                   加评论
  transitions <KEY>                               列可用流转
  transition <KEY> --id ID [--comment TEXT]       执行流转
  update <KEY> --field NAME=VALUE ...             更新字段
  create-issue --project P --type T --summary S [...]   新建 issue
  delete-issue <KEY> --yes                        删 issue
  get-projects                                    列项目
  get-project-issues --key K                      项目下 issue
  add-worklog <KEY> --time-spent '1h' [--comment]  加工时
  get-worklog <KEY>                               读工时
  create-link <FROM> <TO> --type 'Relates'        建 issue 关系
  get-dev-info <KEY>                              读关联 PR / branch / commit（Bitbucket 唯一入口）

凭据/配置走 atl-query.ps1。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


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
    # Always materialize body to a UTF-8 temp file. PowerShell -Command does not proxy
    # subprocess stdin into the script's pipeline, so passing body via stdin would silently
    # send empty body to curl. Writing to a file + -BodyFile is the only reliable path.
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
        f"& '{_ps_escape(atl_query)}' -Service jira -Path '{_ps_escape(path)}' -Method {method}"
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


def post_json(path: str, payload: dict) -> Any:
    tmp = tempfile.NamedTemporaryFile(suffix=".json", mode="w", encoding="utf-8", delete=False)
    try:
        json.dump(payload, tmp, ensure_ascii=False)
        tmp.close()
        rc, stdout, stderr = call_api(path, method="POST", body_file=tmp.name)
        if rc != 0:
            raise SystemExit(f"POST {path} failed: {stderr}\n{stdout}")
        text = stdout.strip()
        if text.startswith("﻿"):
            text = text[1:]
        return json.loads(text) if text else None
    finally:
        os.unlink(tmp.name)


def put_json(path: str, payload: dict) -> tuple[int, str, str]:
    tmp = tempfile.NamedTemporaryFile(suffix=".json", mode="w", encoding="utf-8", delete=False)
    try:
        json.dump(payload, tmp, ensure_ascii=False)
        tmp.close()
        return call_api(path, method="PUT", body_file=tmp.name)
    finally:
        os.unlink(tmp.name)


# ====== Subcommands ======


def cmd_get_issue(args: argparse.Namespace) -> int:
    # Default fields include subtasks + timetracking so users see at a glance whether
    # this issue has subtasks (and thus whether worklog needs aggregation).
    fields = args.fields or (
        "summary,status,assignee,reporter,priority,issuetype,labels,"
        "fixVersions,components,description,created,updated,parent,"
        "subtasks,timetracking"
    )
    data = call_api_json(f"rest/api/2/issue/{args.key}?fields={fields}")
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0
    f = data.get("fields", {})
    print(f"=== {data.get('key')} ===")
    print(f"  Summary:  {f.get('summary', '?')}")
    print(f"  Status:   {(f.get('status') or {}).get('name', '?')}")
    print(f"  Type:     {(f.get('issuetype') or {}).get('name', '?')}")
    print(f"  Priority: {(f.get('priority') or {}).get('name', '?')}")
    assignee = f.get("assignee") or {}
    reporter = f.get("reporter") or {}
    print(f"  Assignee: {assignee.get('displayName') or assignee.get('name') or '-'}")
    print(f"  Reporter: {reporter.get('displayName') or reporter.get('name') or '-'}")
    print(f"  Created:  {f.get('created', '?')[:19]}")
    print(f"  Updated:  {f.get('updated', '?')[:19]}")
    labels = f.get("labels", [])
    if labels:
        print(f"  Labels:   {', '.join(labels)}")

    # Parent (if this is a subtask)
    parent = f.get("parent")
    if parent:
        print(f"  Parent:   {parent.get('key')} ({((parent.get('fields') or {}).get('summary') or '')[:50]})")

    # Subtasks summary -- critical hint that worklog needs aggregation
    subtasks = f.get("subtasks") or []
    if subtasks:
        print(f"  Subtasks ({len(subtasks)}):")
        for st in subtasks[:10]:
            sf = st.get("fields") or {}
            st_status = (sf.get("status") or {}).get("name", "?")
            print(f"    - {st.get('key'):<15} [{st_status}] {(sf.get('summary') or '')[:50]}")
        if len(subtasks) > 10:
            print(f"    ... and {len(subtasks) - 10} more")

    # Time tracking - show clearly that this is THIS issue only
    tt = f.get("timetracking") or {}
    if tt and (tt.get("originalEstimate") or tt.get("timeSpent") or tt.get("remainingEstimate")):
        print(f"  TimeTracking (THIS issue's worklog only -- excludes subtasks):")
        if tt.get("originalEstimate"):
            print(f"    Original:  {tt['originalEstimate']}")
        if tt.get("timeSpent"):
            print(f"    Spent:     {tt['timeSpent']}")
        if tt.get("remainingEstimate"):
            print(f"    Remaining: {tt['remainingEstimate']}")
        if subtasks:
            print(f"    NOTE: this issue has {len(subtasks)} subtasks. For total spent across "
                  f"parent+subtasks, run:")
            print(f"      atl-jira get-worklog {data.get('key')} --include-subtasks")

    desc = f.get("description") or ""
    if desc:
        print(f"\nDescription:\n{desc}")
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    fields = args.fields or "summary,status,assignee,priority,issuetype,updated"
    payload = {"jql": args.jql, "fields": fields.split(","), "maxResults": args.limit, "startAt": args.start}
    data = post_json("rest/api/2/search", payload)
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0
    issues = data.get("issues", []) if data else []
    total = data.get("total", 0) if data else 0
    print(f"{'KEY':<15} {'STATUS':<15} {'TYPE':<12} {'PRIORITY':<10} {'ASSIGNEE':<20} SUMMARY")
    print("-" * 130)
    for iss in issues:
        f = iss.get("fields", {})
        a = (f.get("assignee") or {}).get("displayName", "-")
        print(f"{iss.get('key', '?'):<15} "
              f"{(f.get('status') or {}).get('name', '?')[:13]:<15} "
              f"{(f.get('issuetype') or {}).get('name', '?')[:10]:<12} "
              f"{(f.get('priority') or {}).get('name', '?')[:8]:<10} "
              f"{(a or '-')[:18]:<20} "
              f"{(f.get('summary') or '')[:60]}")
    print(f"\nShowing {len(issues)} of {total} (start={args.start}, limit={args.limit})")
    return 0


def cmd_add_comment(args: argparse.Namespace) -> int:
    if args.file:
        body = Path(args.file).read_text(encoding="utf-8")
    elif args.text:
        body = args.text
    else:
        raise SystemExit("provide --text or --file")
    data = post_json(f"rest/api/2/issue/{args.key}/comment", {"body": body})
    print(f"OK comment id={data.get('id')} added to {args.key}")
    return 0


def cmd_transitions(args: argparse.Namespace) -> int:
    data = call_api_json(f"rest/api/2/issue/{args.key}/transitions")
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0
    print(f"{'ID':<8} {'NAME':<30} -> {'TARGET STATUS'}")
    print("-" * 70)
    for t in (data or {}).get("transitions", []):
        print(f"{t.get('id', '?'):<8} {t.get('name', '?'):<30} -> {(t.get('to') or {}).get('name', '?')}")
    return 0


def cmd_transition(args: argparse.Namespace) -> int:
    payload: dict[str, Any] = {"transition": {"id": args.id}}
    if args.comment:
        payload["update"] = {"comment": [{"add": {"body": args.comment}}]}
    rc, stdout, stderr = call_api(
        f"rest/api/2/issue/{args.key}/transitions",
        method="POST",
        body=json.dumps(payload, ensure_ascii=False),
    )
    if rc != 0:
        print(f"ERROR: {stderr}\n{stdout}", file=sys.stderr)
        return 1
    print(f"OK transition id={args.id} executed on {args.key}")
    return 0


def cmd_update(args: argparse.Namespace) -> int:
    """--field name=value can be repeated. Special handling for labels (csv -> list)."""
    fields: dict[str, Any] = {}
    for kv in args.field or []:
        if "=" not in kv:
            raise SystemExit(f"invalid --field '{kv}', expected name=value")
        name, value = kv.split("=", 1)
        # Heuristics for common types
        if name in ("labels", "components", "fixVersions"):
            fields[name] = [{"name": v.strip()} if name in ("components", "fixVersions") else v.strip()
                            for v in value.split(",")]
        elif name in ("assignee", "reporter"):
            fields[name] = {"name": value}
        elif name in ("priority", "issuetype", "status"):
            fields[name] = {"name": value}
        else:
            fields[name] = value
    if not fields:
        raise SystemExit("at least one --field required")

    rc, stdout, stderr = put_json(
        f"rest/api/2/issue/{args.key}",
        {"fields": fields},
    )
    if rc != 0:
        print(f"ERROR: {stderr}\n{stdout}", file=sys.stderr)
        return 1
    print(f"OK updated {args.key}: {list(fields.keys())}")
    return 0


def cmd_create_issue(args: argparse.Namespace) -> int:
    fields: dict[str, Any] = {
        "project": {"key": args.project},
        "summary": args.summary,
        "issuetype": {"name": args.type},
    }
    if args.description:
        fields["description"] = args.description
    if args.assignee:
        fields["assignee"] = {"name": args.assignee}
    if args.priority:
        fields["priority"] = {"name": args.priority}
    if args.labels:
        fields["labels"] = args.labels.split(",")
    if args.parent:
        fields["parent"] = {"key": args.parent}

    data = post_json("rest/api/2/issue", {"fields": fields})
    print(f"OK created {data.get('key')} (id={data.get('id')})")
    return 0


def cmd_delete_issue(args: argparse.Namespace) -> int:
    if not args.yes:
        print(f"Refusing to delete {args.key} without --yes", file=sys.stderr)
        return 1
    rc, stdout, stderr = call_api(f"rest/api/2/issue/{args.key}", method="DELETE")
    if rc != 0:
        print(f"ERROR: {stderr}\n{stdout}", file=sys.stderr)
        return 1
    print(f"OK deleted {args.key}")
    return 0


def cmd_get_projects(args: argparse.Namespace) -> int:
    data = call_api_json("rest/api/2/project")
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0
    if not data:
        print("(empty)")
        return 0
    print(f"{'KEY':<15} {'ID':<10} NAME")
    print("-" * 70)
    for p in data:
        print(f"{p.get('key', '?'):<15} {p.get('id', '?'):<10} {p.get('name', '?')}")
    print(f"\nTotal: {len(data)}")
    return 0


def cmd_get_project_issues(args: argparse.Namespace) -> int:
    # Reuse search with JQL `project = X`
    payload = {
        "jql": f"project = {args.key} ORDER BY updated DESC",
        "fields": ["summary", "status", "assignee", "priority", "updated"],
        "maxResults": args.limit,
    }
    data = post_json("rest/api/2/search", payload)
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0
    if not data:
        print("(empty response)")
        return 0
    issues = data.get("issues", []) or []
    if not issues:
        print(f"(no issues in project {args.key})")
        return 0
    print(f"{'KEY':<15} {'STATUS':<15} {'PRIORITY':<10} {'ASSIGNEE':<20} SUMMARY")
    print("-" * 110)
    for iss in issues:
        f = iss.get("fields", {})
        a = (f.get("assignee") or {}).get("displayName", "-")
        print(f"{iss.get('key', '?'):<15} "
              f"{(f.get('status') or {}).get('name', '?')[:13]:<15} "
              f"{(f.get('priority') or {}).get('name', '?')[:8]:<10} "
              f"{(a or '-')[:18]:<20} "
              f"{(f.get('summary') or '')[:50]}")
    print(f"\nTotal: {data.get('total', len(issues))}")
    return 0


def cmd_add_worklog(args: argparse.Namespace) -> int:
    payload: dict[str, Any] = {"timeSpent": args.time_spent}
    if args.comment:
        payload["comment"] = args.comment
    if args.started:
        payload["started"] = args.started
    data = post_json(f"rest/api/2/issue/{args.key}/worklog", payload)
    print(f"OK worklog id={data.get('id')} added ({args.time_spent})")
    return 0


def _format_seconds(secs):
    """Format seconds as Jira-style 'Nw Nd Nh Nm' (8h workday, 5d week)."""
    if not secs:
        return "0m"
    secs = int(secs)
    weeks, secs = divmod(secs, 5 * 8 * 3600)
    days, secs = divmod(secs, 8 * 3600)
    hours, secs = divmod(secs, 3600)
    mins, _ = divmod(secs, 60)
    parts = []
    if weeks: parts.append(f"{weeks}w")
    if days:  parts.append(f"{days}d")
    if hours: parts.append(f"{hours}h")
    if mins:  parts.append(f"{mins}m")
    return " ".join(parts) if parts else "0m"


def _fetch_worklog_for_issue(key: str) -> tuple[list[dict], int]:
    """Return (worklog_entries, sum_of_timeSpentSeconds) for one issue."""
    data = call_api_json(f"rest/api/2/issue/{key}/worklog") or {}
    entries = data.get("worklogs", []) or []
    total_secs = sum(int(w.get("timeSpentSeconds") or 0) for w in entries)
    return entries, total_secs


def cmd_get_worklog(args: argparse.Namespace) -> int:
    """Read worklog detail for an issue.

    By default reads ONLY the given issue's worklog. With --include-subtasks,
    also fetches each subtask and aggregates the grand total.

    Important Jira semantics: parent issue's `timetracking.timeSpent` field is
    aggregated from THIS issue's worklog only -- it does NOT include subtasks.
    Use --include-subtasks to get parent+subtasks total.
    """
    if args.include_subtasks:
        # Fetch parent issue meta to enumerate subtasks
        meta = call_api_json(f"rest/api/2/issue/{args.key}?fields=subtasks,summary")
        subtask_keys = [s.get("key") for s in (meta.get("fields", {}).get("subtasks") or []) if s.get("key")]
        rows = []
        # Parent first
        parent_entries, parent_secs = _fetch_worklog_for_issue(args.key)
        rows.append({
            "key": args.key,
            "is_parent": True,
            "summary": (meta.get("fields", {}).get("summary") or "")[:50],
            "entries": parent_entries,
            "total_secs": parent_secs,
        })
        for sk in subtask_keys:
            sk_meta = call_api_json(f"rest/api/2/issue/{sk}?fields=summary") or {}
            entries, secs = _fetch_worklog_for_issue(sk)
            rows.append({
                "key": sk,
                "is_parent": False,
                "summary": (sk_meta.get("fields", {}).get("summary") or "")[:50],
                "entries": entries,
                "total_secs": secs,
            })

        if args.json:
            grand = sum(r["total_secs"] for r in rows)
            print(json.dumps({
                "parent": args.key,
                "grand_total_seconds": grand,
                "grand_total_formatted": _format_seconds(grand),
                "issues": rows,
            }, ensure_ascii=False, indent=2, default=str))
            return 0

        grand_secs = 0
        for r in rows:
            tag = "[PARENT]" if r["is_parent"] else "[SUB]   "
            print(f"\n=== {tag} {r['key']}  {_format_seconds(r['total_secs'])}  ({r['summary']}) ===")
            if not r["entries"]:
                print("  (no worklog entries)")
                continue
            print(f"  {'AUTHOR':<20} {'TIME':<10} {'STARTED':<22} COMMENT")
            for w in r["entries"]:
                author = (w.get("author") or {}).get("displayName", "?")
                print(f"  {author[:18]:<20} {w.get('timeSpent', '?'):<10} "
                      f"{w.get('started', '?')[:22]:<22} {(w.get('comment') or '')[:40]}")
            grand_secs += r["total_secs"]

        print()
        print("=" * 70)
        print(f"GRAND TOTAL ({len(rows)} issues, parent + {len(subtask_keys)} subtasks):  "
              f"{_format_seconds(grand_secs)}  ({grand_secs}s)")
        return 0

    # Single-issue mode
    entries, total_secs = _fetch_worklog_for_issue(args.key)
    if args.json:
        print(json.dumps({
            "key": args.key,
            "total_seconds": total_secs,
            "total_formatted": _format_seconds(total_secs),
            "worklogs": entries,
        }, ensure_ascii=False, indent=2, default=str))
        return 0
    print(f"{'ID':<10} {'AUTHOR':<20} {'TIME':<10} {'STARTED':<22} COMMENT")
    print("-" * 100)
    for w in entries:
        author = (w.get("author") or {}).get("displayName", "?")
        print(f"{w.get('id', '?'):<10} {author[:18]:<20} "
              f"{w.get('timeSpent', '?'):<10} {w.get('started', '?')[:22]:<22} "
              f"{(w.get('comment') or '')[:40]}")
    print()
    print(f"Entries: {len(entries)}   "
          f"Total for {args.key} (THIS issue only): {_format_seconds(total_secs)}  ({total_secs}s)")
    print("Note: this excludes any subtasks. Use --include-subtasks to aggregate parent + subtasks.")
    return 0


def cmd_move(args: argparse.Namespace) -> int:
    """Reparent a subtask, including cross-project (via web action automation).

    Jira Server REST API has no direct endpoint for cross-project subtask move
    (JRA-13763, JRASERVER-15259), but the same wizards Web UI uses can be
    driven via curl + Basic Auth + form POSTs. This command automates the
    9-step flow when needed:

      same-project / parent-on-Edit-screen:  PUT fields.parent + verify
      cross-project subtask -> subtask:      ConvertSubTask (3 steps)
                                             + MoveIssue    (3 steps)
                                             + ConvertIssue (3 steps)

    fixVersions on the moved issue inherit from the new parent (handles the
    "version mapping" wizard step automatically).
    """
    # Fetch both issues for context (extra fields needed for wizard automation)
    src = call_api_json(
        f"rest/api/2/issue/{args.key}"
        f"?fields=summary,parent,issuetype,project,status,fixVersions"
    )
    if not src:
        raise SystemExit(f"Source issue {args.key} not found")
    dst = call_api_json(
        f"rest/api/2/issue/{args.parent}"
        f"?fields=summary,issuetype,project,fixVersions"
    )
    if not dst:
        raise SystemExit(f"Target parent {args.parent} not found")

    src_id = src.get("id")
    src_f = src.get("fields", {})
    dst_f = dst.get("fields", {})
    src_proj = (src_f.get("project") or {}).get("key", "?")
    dst_proj = (dst_f.get("project") or {}).get("key", "?")
    src_type = (src_f.get("issuetype") or {}).get("name", "?")
    src_type_id = (src_f.get("issuetype") or {}).get("id", "")
    src_is_subtask = (src_f.get("issuetype") or {}).get("subtask", False)
    cur_parent_key = (src_f.get("parent") or {}).get("key", "(none)")
    cross_project = src_proj != dst_proj

    # Inherit fixVersions from new parent
    parent_fixversions = dst_f.get("fixVersions") or []
    parent_fv_id = parent_fixversions[0].get("id") if parent_fixversions else None
    parent_fv_name = parent_fixversions[0].get("name") if parent_fixversions else None

    # Get target project numeric id (needed by MoveIssue wizard's pid field)
    dst_proj_id = (dst_f.get("project") or {}).get("id", "")

    print(f"=== Move plan ===")
    print(f"  Source:         {args.key}  [{src_type}]  {src_f.get('summary', '')[:50]}")
    print(f"  Current parent: {cur_parent_key}")
    print(f"  New parent:     {args.parent}  [{(dst_f.get('issuetype') or {}).get('name', '?')}]  "
          f"{dst_f.get('summary', '')[:50]}")
    print(f"  Source project: {src_proj}")
    print(f"  Target project: {dst_proj} (id={dst_proj_id})"
          f"{'  CROSS-PROJECT' if cross_project else ''}")
    if parent_fv_name:
        print(f"  Will inherit fixVersion from new parent: {parent_fv_name} (id={parent_fv_id})")
    print()

    if cross_project:
        if not src_is_subtask:
            print("ERROR: source is not a subtask. Cross-project move of standard issues is")
            print("       supported by Jira's MoveIssue wizard but not yet by this command.")
            print("       Use Web UI:")
            _print_webui_move_url(args.key)
            return 2

        if not args.yes:
            print("DRY-RUN. Cross-project subtask move via 9-step web wizard:")
            print("  Phase 1: ConvertSubTask  (3 steps) -- subtask -> standard issue")
            print("  Phase 2: MoveIssue       (3 steps) -- cross-project move")
            print("  Phase 3: ConvertIssue    (3 steps) -- back to subtask under new parent")
            print()
            print(f"  Issue ID stays {src_id}, but key will change (e.g. {args.key} -> {dst_proj}-NNN)")
            print(f"  All comments, worklog, attachments preserved by Jira.")
            print()
            print("Re-run with --yes to execute.")
            return 0

        # Execute the 9-step wizard
        cookie_file = os.path.join(tempfile.gettempdir(), f"atl-move-{src_id}-cookies.txt")
        try:
            new_key = _move_subtask_cross_project(
                args, src_id, src_proj, src_type_id, src_f.get("fixVersions") or [],
                args.parent, dst_proj_id, parent_fv_id, cookie_file,
            )
        finally:
            try:
                os.unlink(cookie_file)
            except OSError:
                pass

        print()
        print(f"OK moved {args.key} -> {new_key}  (parent: {cur_parent_key} -> {args.parent})")
        print(f"   project: {src_proj} -> {dst_proj}")
        return 0

    # SAME-PROJECT: try PUT (might work if admin added parent to Edit screen)
    if not args.yes:
        print("DRY-RUN. Same-project reparent. Re-run with --yes to attempt.")
        print(f"  This requires 'parent' to be on the Edit screen for {src_type} in {src_proj}.")
        print(f"  If not: PUT will return 200 but silently no-op; the command verifies and reports.")
        return 0

    print("Attempting PUT /rest/api/2/issue/{key}  body={\"fields\":{\"parent\":...}}")
    sys.stdout.flush()
    payload = {"fields": {"parent": {"key": args.parent}}}
    rc, stdout_, stderr_ = call_api(
        f"rest/api/2/issue/{args.key}",
        method="PUT",
        body=json.dumps(payload, ensure_ascii=False),
    )
    api_error_summary = ""
    if rc != 0:
        api_error_summary = (stderr_ or stdout_ or "")[:300]
        print(f"  -> rejected (rc={rc}): {api_error_summary}")
    else:
        print("  -> PUT returned success. Verifying via re-GET...")
    sys.stdout.flush()

    verify = call_api_json(f"rest/api/2/issue/{args.key}?fields=parent")
    new_parent = (verify.get("fields", {}).get("parent") or {}).get("key", "(none)")

    if new_parent == args.parent:
        print(f"\nOK moved {args.key}: parent {cur_parent_key} -> {args.parent}")
        return 0

    # Same-project failed too (parent field still locked)
    print(f"\nFAILED: parent unchanged. Still: {new_parent} (expected {args.parent}).")
    if api_error_summary:
        print(f"  API error: {api_error_summary}")
    else:
        print(f"  API returned 200 but silently no-op'd.")
    print(f"  Cause: 'parent' field is not on Edit screen for {src_type} in {src_proj}.")
    print(f"  Fix: ask Jira admin to add 'parent' to the Edit screen, OR use Web UI:")
    _print_webui_move_url(args.key)
    return 2


def _print_webui_move_url(key: str) -> None:
    """Print the Jira web UI Move Wizard URL for one issue."""
    config = _read_config()
    base = config.get("JIRA_URL", "").rstrip("/")
    if not base:
        print("(JIRA_URL not configured; cannot build web URL)")
        return
    print(f"  {base}/secure/MoveIssue!default.jspa?key={key}")
    print(f"  (or open {base}/browse/{key} -> More -> Move)")


# ============================================================
# Web action wizard automation (curl + form POSTs through
# Jira's HTML wizards that have no REST equivalent)
# ============================================================

def _curl(args_list: list[str], cookie_file: str) -> tuple[int, bytes]:
    """Run curl with --netrc + cookie jar. Returns (returncode, stdout_bytes)."""
    cmd = ["curl", "-s", "-S", "--netrc", "-L",
           "-c", cookie_file, "-b", cookie_file] + args_list
    proc = subprocess.run(cmd, capture_output=True)
    return proc.returncode, proc.stdout


def _wizard_get(url: str, cookie_file: str) -> str:
    """GET wizard page, return HTML text."""
    rc, body = _curl([url], cookie_file)
    if rc != 0:
        raise SystemExit(f"GET {url} failed (curl rc={rc})")
    return body.decode("utf-8", errors="replace")


def _wizard_post(url: str, fields: dict, cookie_file: str) -> str:
    """POST form, return resulting HTML."""
    args_list = [
        "-X", "POST", url,
        "-H", "X-Atlassian-Token: no-check",
        "-H", "Content-Type: application/x-www-form-urlencoded",
    ]
    for k, v in fields.items():
        args_list.extend(["--data-urlencode", f"{k}={v}"])
    rc, body = _curl(args_list, cookie_file)
    if rc != 0:
        raise SystemExit(f"POST {url} failed (curl rc={rc})")
    return body.decode("utf-8", errors="replace")


def _extract_atl_token(html: str) -> str:
    """Extract atl_token from wizard HTML (it's in hidden inputs of every form)."""
    m = re.search(r'name=["\']atl_token["\']\s+value=["\']([^"\']+)', html)
    if not m:
        raise SystemExit("atl_token not found in wizard page (auth issue?)")
    return m.group(1)


def _extract_guid(html: str) -> str:
    """Extract wizard guid (session identifier across multi-step wizards)."""
    m = re.search(r'name=["\']guid["\']\s+value=["\']([^"\']+)', html)
    return m.group(1) if m else "1"


def _extract_form_action(html: str, expected_action_substring: str) -> str:
    """Find form action containing the expected substring (e.g. 'Convert', 'Move')."""
    for m in re.finditer(r'<form[^>]*?action=["\']([^"\']+\.jspa[^"\']*)', html):
        if expected_action_substring in m.group(1):
            return m.group(1)
    raise SystemExit(f"No form with action containing '{expected_action_substring}' found")


def _extract_errors(html: str) -> list[str]:
    """Extract user-visible error messages from wizard HTML."""
    errs = []
    for m in re.finditer(
        r'class=["\'][^"\']*(?:error|aui-message-error)[^"\']*["\'][^>]*>([^<]{5,300})',
        html,
    ):
        t = m.group(1).strip()
        if t and t not in errs:
            errs.append(t[:300])
    return errs


def _wizard_step(label: str, response_html: str, expected_next_action: str) -> None:
    """Sanity-check that wizard advanced to expected next step. Raises on error."""
    errs = _extract_errors(response_html)
    if errs:
        msg = f"\nWizard step '{label}' returned errors:\n  - " + "\n  - ".join(errs)
        raise SystemExit(msg)
    # Verify expected next step
    try:
        action = _extract_form_action(response_html, expected_next_action)
        print(f"  -> advanced to: {action}")
    except SystemExit:
        # Could be the "issue page" (after final commit) which has no Convert/Move form
        if expected_next_action in ("(final)", "(none)"):
            return
        raise SystemExit(
            f"\nWizard step '{label}' did not advance to '{expected_next_action}' "
            f"(no matching form). HTML snippet may help debug; saved to atl-cache."
        )


def _move_subtask_cross_project(args: argparse.Namespace, src_id: int,
                                src_proj: str, src_issuetype_id: str,
                                src_fixversions: list,
                                target_parent_key: str,
                                target_proj_id: str,
                                target_fixversion_id: str | None,
                                cookie_file: str) -> str:
    """Run the 9-step web wizard automation. Returns new issue key."""
    config = _read_config()
    base = config.get("JIRA_URL", "").rstrip("/")
    if not base:
        raise SystemExit("JIRA_URL not configured.")

    # ========== Phase 1: ConvertSubTask (subtask -> standard issue) ==========
    print("Phase 1/3: ConvertSubTask (subtask -> standard issue)...")
    sys.stdout.flush()

    # Pick a non-subtask issuetype in source project. Default to '任务' (10131) if
    # available. Future: query project's issuetypes and pick the most generic.
    target_issuetype_for_convert = "10131"  # 任务

    # Step 1a: GET wizard
    html = _wizard_get(f"{base}/secure/ConvertSubTask.jspa?id={src_id}", cookie_file)
    token = _extract_atl_token(html)
    guid = _extract_guid(html)
    print(f"  GET ConvertSubTask  guid={guid}")

    # Step 1b: POST set issuetype
    html = _wizard_post(
        f"{base}/secure/ConvertSubTaskSetIssueType.jspa",
        {"id": str(src_id), "guid": guid, "atl_token": token,
         "issuetype": target_issuetype_for_convert},
        cookie_file,
    )
    _wizard_step("ConvertSubTask SetIssueType", html, "ConvertSubTaskUpdateFields")

    # Step 1c: POST update fields (no extra fields needed)
    html = _wizard_post(
        f"{base}/secure/ConvertSubTaskUpdateFields.jspa",
        {"id": str(src_id), "guid": guid, "atl_token": token},
        cookie_file,
    )
    _wizard_step("ConvertSubTask UpdateFields", html, "ConvertSubTaskConvert")

    # Step 1d: POST commit
    html = _wizard_post(
        f"{base}/secure/ConvertSubTaskConvert.jspa",
        {"id": str(src_id), "guid": guid, "atl_token": token},
        cookie_file,
    )
    print(f"  COMMITTED: now standard issue (still in {src_proj})")

    # ========== Phase 2: MoveIssue (cross-project) ==========
    print("Phase 2/3: MoveIssue (cross-project move)...")
    sys.stdout.flush()

    # Step 2a: GET wizard (fresh atl_token since session moved on)
    html = _wizard_get(f"{base}/secure/MoveIssue!default.jspa?id={src_id}", cookie_file)
    token = _extract_atl_token(html)

    # Step 2b: POST select target project + issuetype
    # We keep the 任务 issuetype (10131); both projects share scheme on this instance
    html = _wizard_post(
        f"{base}/secure/MoveIssue.jspa",
        {"id": str(src_id), "atl_token": token,
         "pid": target_proj_id, "issuetype": target_issuetype_for_convert},
        cookie_file,
    )
    _wizard_step("MoveIssue SelectProject", html, "MoveIssueUpdateFields")

    # Step 2c: POST update fields - inherit fixVersion from new parent
    update_fields = {"id": str(src_id), "atl_token": token,
                     "customfield_10273": ""}  # External issue ID kept empty
    if target_fixversion_id:
        update_fields["fixVersions"] = target_fixversion_id
    html = _wizard_post(
        f"{base}/secure/MoveIssueUpdateFields.jspa",
        update_fields,
        cookie_file,
    )
    _wizard_step("MoveIssue UpdateFields", html, "MoveIssueConfirm")

    # Step 2d: POST commit
    html = _wizard_post(
        f"{base}/secure/MoveIssueConfirm.jspa",
        {"id": str(src_id), "atl_token": token, "confirm": "true"},
        cookie_file,
    )
    print(f"  COMMITTED: moved to target project (key changed)")

    # ========== Phase 3: ConvertIssue (standard issue -> subtask) ==========
    print("Phase 3/3: ConvertIssue (standard issue -> subtask of new parent)...")
    sys.stdout.flush()

    # Step 3a: GET wizard (fresh atl_token + new wizard session)
    html = _wizard_get(f"{base}/secure/ConvertIssue.jspa?id={src_id}", cookie_file)
    token = _extract_atl_token(html)
    guid = _extract_guid(html)

    # Step 3b: POST set parent + subtask issuetype (10105 = 子任务)
    html = _wizard_post(
        f"{base}/secure/ConvertIssueSetIssueType.jspa",
        {"id": str(src_id), "guid": guid, "atl_token": token,
         "parentIssueKey": target_parent_key,
         "issuetype": str(src_issuetype_id)},  # use original subtask type
        cookie_file,
    )
    _wizard_step("ConvertIssue SetIssueType", html, "ConvertIssueUpdateFields")

    # Step 3c: POST update fields
    html = _wizard_post(
        f"{base}/secure/ConvertIssueUpdateFields.jspa",
        {"id": str(src_id), "guid": guid, "atl_token": token},
        cookie_file,
    )
    _wizard_step("ConvertIssue UpdateFields", html, "ConvertIssueConvert")

    # Step 3d: POST commit
    html = _wizard_post(
        f"{base}/secure/ConvertIssueConvert.jspa",
        {"id": str(src_id), "guid": guid, "atl_token": token},
        cookie_file,
    )
    print(f"  COMMITTED: converted back to subtask")

    # Verify final state
    final = call_api_json(f"rest/api/2/issue/{src_id}?fields=project,parent,issuetype")
    new_key = final.get("key", "?")
    new_parent_actual = (final.get("fields", {}).get("parent") or {}).get("key", "(none)")
    if new_parent_actual != target_parent_key:
        raise SystemExit(
            f"\nWizard reported success but verify shows parent={new_parent_actual}, "
            f"expected {target_parent_key}. New key: {new_key}"
        )
    return new_key


def cmd_move_helper(args: argparse.Namespace) -> int:
    """Generate pre-filled Web UI URLs for bulk cross-project subtask move.

    Workflow:
      1. Lists all subtasks of <PARENT_KEY>
      2. Generates Issue Navigator JQL URL with all subtask keys
      3. User opens URL -> Tools -> Bulk Change all -> Move Issues
      4. Wizard moves all N subtasks in ONE pass (5-step wizard, ~3 minutes)

    This is the fastest path on Jira Server for cross-project subtask migration
    when REST API doesn't work.
    """
    config = _read_config()
    base = config.get("JIRA_URL", "").rstrip("/")
    if not base:
        raise SystemExit("JIRA_URL not configured. Run atl-credential.ps1 -Action setup.")

    # Find subtasks of the parent
    parent = call_api_json(f"rest/api/2/issue/{args.parent}?fields=summary,subtasks,project")
    if not parent:
        raise SystemExit(f"Parent issue {args.parent} not found")
    subtasks = parent.get("fields", {}).get("subtasks") or []
    if not subtasks:
        print(f"{args.parent} has no subtasks. Nothing to move.")
        return 0

    parent_summary = parent.get("fields", {}).get("summary", "")
    src_proj = (parent.get("fields", {}).get("project") or {}).get("key", "?")

    # Validate target parent exists
    new_parent_info = ""
    new_proj = ""
    if args.new_parent:
        np = call_api_json(f"rest/api/2/issue/{args.new_parent}?fields=summary,project")
        if not np:
            raise SystemExit(f"Target parent {args.new_parent} not found")
        new_parent_info = np.get("fields", {}).get("summary", "")
        new_proj = (np.get("fields", {}).get("project") or {}).get("key", "?")

    keys = [st.get("key") for st in subtasks if st.get("key")]

    print(f"=== Bulk move helper ===")
    print(f"  Source parent:  {args.parent}  ({parent_summary[:50]})")
    print(f"  Source project: {src_proj}")
    if args.new_parent:
        print(f"  Target parent:  {args.new_parent}  ({new_parent_info[:50]})")
        print(f"  Target project: {new_proj}")
    print(f"  Subtasks ({len(keys)}):")
    for st in subtasks[:20]:
        sf = st.get("fields") or {}
        s_status = (sf.get("status") or {}).get("name", "?")
        print(f"    - {st.get('key'):<15} [{s_status}]  {(sf.get('summary') or '')[:50]}")
    if len(subtasks) > 20:
        print(f"    ... and {len(subtasks) - 20} more")
    print()

    # Build Issue Navigator JQL URL
    from urllib.parse import quote
    jql = f"key in ({', '.join(keys)})"
    nav_url = f"{base}/issues/?jql={quote(jql)}"

    print("=== Step-by-step (Web UI Bulk Change) ===")
    print(f"  1. Open in browser:")
    print(f"     {nav_url}")
    print(f"")
    print(f"  2. In Issue Navigator: top-right -> Tools (gear icon) -> Bulk Change all {len(keys)} issues")
    print(f"     (or: ... -> Bulk Edit -> step 1: Choose Issues -> All -> Next)")
    print(f"")
    print(f"  3. Step 2 'Choose Operation': select 'Move Issues' -> Next")
    print(f"")
    if args.new_parent:
        print(f"  4. Step 3 'Choose Project and Issue Type':")
        print(f"     - Target project: select project of {args.new_parent} (key: {new_proj})")
        print(f"     - Issue type: keep as Sub-task (or matching type in target project)")
        print(f"     - Click Next")
    else:
        print(f"  4. Step 3: select target project + issue type (Sub-task)")
    print(f"")
    print(f"  5. Step 4 'Update Fields' (if statuses/fields differ between projects):")
    print(f"     - Map status if workflow differs")
    print(f"     - Map any required custom fields (Jira will auto-fill defaults)")
    print(f"")
    if args.new_parent:
        print(f"  6. Step 5 'Set new parent': enter {args.new_parent}")
    else:
        print(f"  6. Step 5: enter the new parent issue key")
    print(f"")
    print(f"  7. Step 6 'Confirm': review the changes -> Confirm -> done")
    print(f"")
    print(f"NOTE: subtask keys WILL change (e.g. {keys[0]} -> NEW_PROJECT-NNN).")
    print(f"      All comments, worklog, attachments, links are preserved.")
    return 0


def _read_config() -> dict:
    """Read config.env into a dict (used by cmd_move for web URL)."""
    cfg = Path.home() / ".claude" / "skill-config" / "atlassian" / "config.env"
    out: dict[str, str] = {}
    if not cfg.exists():
        return out
    for line in cfg.read_text(encoding="utf-8", errors="replace").splitlines():
        m = re.match(r"^([A-Z_]+)=(.+)$", line.strip())
        if m:
            out[m.group(1)] = m.group(2).strip()
    return out


def cmd_create_link(args: argparse.Namespace) -> int:
    payload = {
        "type": {"name": args.type},
        "inwardIssue": {"key": args.from_key},
        "outwardIssue": {"key": args.to_key},
    }
    rc, stdout, stderr = call_api(
        "rest/api/2/issueLink", method="POST",
        body=json.dumps(payload, ensure_ascii=False),
    )
    if rc != 0:
        print(f"ERROR: {stderr}\n{stdout}", file=sys.stderr)
        return 1
    print(f"OK linked {args.from_key} -[{args.type}]-> {args.to_key}")
    return 0


def cmd_get_dev_info(args: argparse.Namespace) -> int:
    """Bitbucket / GitHub / GitLab linked PR / branch / commit info via Jira dev panel."""
    # First fetch issue to get internal id
    issue = call_api_json(f"rest/api/2/issue/{args.key}?fields=summary")
    issue_id = issue.get("id")
    if not issue_id:
        raise SystemExit(f"Cannot resolve issue id for {args.key}")

    # The dev-status API requires applicationType + dataType
    app_types = [args.app_type] if args.app_type else ["stash", "bitbucket", "github", "gitlab"]
    data_types = [args.data_type] if args.data_type else ["pullrequest", "branch", "repository"]

    out: dict[str, Any] = {"issue": args.key, "issue_id": issue_id, "results": {}}
    for app in app_types:
        for dt in data_types:
            path = (
                "rest/dev-status/1.0/issue/detail"
                f"?issueId={issue_id}&applicationType={app}&dataType={dt}"
            )
            rc, stdout, stderr = call_api(path)
            if rc != 0:
                continue
            text = stdout.strip()
            if text.startswith("﻿"):
                text = text[1:]
            if not text:
                continue
            try:
                d = json.loads(text)
            except json.JSONDecodeError:
                continue
            details = d.get("detail", [])
            if details:
                out["results"][f"{app}/{dt}"] = details

    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0

    if not out["results"]:
        print(f"No development info found for {args.key}")
        print(f"(checked: {app_types} x {data_types})")
        return 0

    print(f"=== Development info for {args.key} ===\n")
    for key, details in out["results"].items():
        print(f"-- {key} --")
        for entry in details:
            for prs in entry.get("pullRequests", []) or []:
                print(f"  PR  #{prs.get('id')}  {prs.get('status', '?'):<10}  "
                      f"{prs.get('name', '?')[:50]}")
                print(f"      url: {prs.get('url', '')}")
            for br in entry.get("branches", []) or []:
                print(f"  BR  {br.get('name', '?')[:50]}  url: {br.get('url', '')}")
            for c in entry.get("commits", []) or [] or []:
                print(f"  CO  {c.get('id', '')[:8]}  {c.get('message', '?')[:60]}")
            for r in entry.get("repositories", []) or []:
                print(f"  RE  {r.get('name', '?')}  url: {r.get('url', '')}")
        print()
    return 0


# ====== argparse ======


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="atl-jira: Jira CLI (REST v2)")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("get-issue", help="read single issue")
    sp.add_argument("key", help="e.g. PROJ-123")
    sp.add_argument("--fields", help="comma-separated field list (default: common fields)")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_get_issue)

    sp = sub.add_parser("search", help="JQL search")
    sp.add_argument("--jql", required=True)
    sp.add_argument("--fields", help="comma-separated fields (default: common)")
    sp.add_argument("--limit", type=int, default=50)
    sp.add_argument("--start", type=int, default=0)
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_search)

    sp = sub.add_parser("add-comment", help="add comment")
    sp.add_argument("key")
    sp.add_argument("--text", help="plain text comment")
    sp.add_argument("--file", help="read body from file")
    sp.set_defaults(func=cmd_add_comment)

    sp = sub.add_parser("transitions", help="list available transitions")
    sp.add_argument("key")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_transitions)

    sp = sub.add_parser("transition", help="execute transition")
    sp.add_argument("key")
    sp.add_argument("--id", required=True, help="transition id (from `transitions` cmd)")
    sp.add_argument("--comment", help="optional comment")
    sp.set_defaults(func=cmd_transition)

    sp = sub.add_parser("update", help="update fields")
    sp.add_argument("key")
    sp.add_argument("--field", action="append", help="name=value (repeatable)")
    sp.set_defaults(func=cmd_update)

    sp = sub.add_parser("create-issue", help="create new issue")
    sp.add_argument("--project", required=True, help="project key")
    sp.add_argument("--type", required=True, help="issue type name (Bug/Task/Story...)")
    sp.add_argument("--summary", required=True)
    sp.add_argument("--description")
    sp.add_argument("--assignee", help="username")
    sp.add_argument("--priority", help="priority name")
    sp.add_argument("--labels", help="comma-separated")
    sp.add_argument("--parent", help="parent issue key (for subtasks/epic-link)")
    sp.set_defaults(func=cmd_create_issue)

    sp = sub.add_parser("delete-issue", help="delete issue (--yes required)")
    sp.add_argument("key")
    sp.add_argument("--yes", action="store_true")
    sp.set_defaults(func=cmd_delete_issue)

    sp = sub.add_parser("get-projects", help="list all projects")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_get_projects)

    sp = sub.add_parser("get-project-issues", help="list issues in project")
    sp.add_argument("--key", required=True)
    sp.add_argument("--limit", type=int, default=50)
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_get_project_issues)

    sp = sub.add_parser("add-worklog", help="add worklog")
    sp.add_argument("key")
    sp.add_argument("--time-spent", required=True, help="e.g. 1h, 30m, 2d")
    sp.add_argument("--comment")
    sp.add_argument("--started", help="ISO datetime e.g. 2026-04-27T09:00:00.000+0800")
    sp.set_defaults(func=cmd_add_worklog)

    sp = sub.add_parser("get-worklog", help="list worklog entries (with totals; --include-subtasks aggregates parent+subtasks)")
    sp.add_argument("key")
    sp.add_argument("--include-subtasks", action="store_true",
                    help="also fetch all subtasks of <key> and show grand total")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_get_worklog)

    sp = sub.add_parser("create-link", help="create issue link")
    sp.add_argument("from_key", help="inward (from) issue key")
    sp.add_argument("to_key", help="outward (to) issue key")
    sp.add_argument("--type", required=True, help="link type name (e.g. 'Relates', 'Blocks')")
    sp.set_defaults(func=cmd_create_link)

    sp = sub.add_parser("move", help="reparent a subtask (same-project only via REST; cross-project refused)")
    sp.add_argument("key", help="subtask issue key to move")
    sp.add_argument("--parent", required=True, help="new parent issue key")
    sp.add_argument("--yes", action="store_true",
                    help="actually attempt the move (default: dry-run + show plan)")
    sp.set_defaults(func=cmd_move)

    sp = sub.add_parser("move-helper",
                        help="generate Web UI Bulk Change URL to move all subtasks of a parent (cross-project)")
    sp.add_argument("parent", help="current parent issue key (whose subtasks need moving)")
    sp.add_argument("--new-parent", help="target parent issue key (used in instructions)")
    sp.set_defaults(func=cmd_move_helper)

    sp = sub.add_parser("get-dev-info", help="Bitbucket/GitHub/GitLab linked PRs/branches/commits")
    sp.add_argument("key")
    sp.add_argument("--app-type", help="filter: stash/bitbucket/github/gitlab")
    sp.add_argument("--data-type", help="filter: pullrequest/branch/repository")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_get_dev_info)

    return p


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
