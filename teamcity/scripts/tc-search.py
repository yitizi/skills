#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""TeamCity 搜索工具

封装 tc-query.ps1 调用 + 中文安全的 JSON 过滤，解决 PowerShell 管道编码问题。
所有 API 结果先写入临时文件，再用 Python 读取（UTF-8），避免管道中文丢失。

用法:
  python tc-search.py projects <关键词>
  python tc-search.py templates <关键词>
  python tc-search.py builds <关键词> [--project 项目ID]
  python tc-search.py audit <模板ID> [--version 版本号]

  # 独立模式
  python tc-search.py templates flink --tc-url http://tc:8111 --username user --password pass
"""

import sys
import os
import json
import argparse
import subprocess
import tempfile


def find_tc_query():
    candidates = [
        os.path.join(os.path.dirname(__file__), "tc-query.ps1"),
        ".claude/skills/teamcity/scripts/tc-query.ps1",
        "skills/teamcity/scripts/tc-query.ps1",
    ]
    for p in candidates:
        if os.path.isfile(p):
            return p
    return None


def _ps_escape(s):
    return s.replace("'", "''")


def _find_curl():
    import shutil
    if sys.platform == "win32":
        p = shutil.which("curl.exe")
        if p:
            return p
    return shutil.which("curl") or "curl"


def _build_auth_header(username, password):
    import base64
    cred = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
    return f"Basic {cred}"


def tc_get(tc_query, path, *, auth=None):
    """调用 API 并返回 JSON，通过临时文件避免管道编码问题"""
    tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
    tmp.close()
    try:
        if auth:
            url = f"{auth['url'].rstrip('/')}/httpAuth/app/rest/{path}"
            header = _build_auth_header(auth["username"], auth["password"])
            curl = _find_curl()
            cmd = [curl, "-s", "-H", f"Authorization: {header}",
                   "-H", "Accept: application/json", "-o", tmp.name,
                   "-w", "%{http_code}", url]
            result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
            http_code = result.stdout.strip()
            if result.returncode != 0:
                print(f"ERROR: curl failed (exit {result.returncode})", file=sys.stderr)
                sys.exit(1)
            if http_code and http_code[0] in ("4", "5"):
                with open(tmp.name, "r", encoding="utf-8") as f:
                    print(f"ERROR: HTTP {http_code}: {f.read()[:300]}", file=sys.stderr)
                sys.exit(1)
        else:
            cmd = [
                "powershell", "-ExecutionPolicy", "Bypass", "-Command",
                f"& '{_ps_escape(tc_query)}' -Path '{_ps_escape(path)}'"
            ]
            result = subprocess.run(cmd, capture_output=True, encoding="utf-8")
            # tc-query.ps1 输出通过 cmd /c type 直接写 stdout（原始 UTF-8 字节）
            # 但 subprocess capture 可能经过 Python 编码层，所以改为让 tc-query 写文件
            # 退而求其次：直接把 capture 的 stdout 写到临时文件（已经是 UTF-8 字符串）
            if result.returncode != 0:
                print(f"ERROR: {result.stderr}", file=sys.stderr)
                sys.exit(1)
            with open(tmp.name, "w", encoding="utf-8") as f:
                f.write(result.stdout)

        with open(tmp.name, "r", encoding="utf-8") as f:
            content = f.read().strip()
        # 处理可能的 UTF-8 BOM
        if content.startswith("\ufeff"):
            content = content[1:]
        return json.loads(content)
    finally:
        os.unlink(tmp.name)


def search_projects(tc_query, keyword, *, auth=None):
    """搜索项目（按名称关键词）"""
    data = tc_get(tc_query,
                  "projects?locator=count:500&fields=project(id,name,parentProjectId,description)",
                  auth=auth)
    kw = keyword.lower()
    results = []
    for p in data.get("project", []):
        name = p.get("name", "")
        pid = p.get("id", "")
        if kw in name.lower() or kw in pid.lower():
            results.append(p)
    if not results:
        print(f"No projects matching '{keyword}'")
        return
    print(f"Found {len(results)} project(s) matching '{keyword}':")
    for p in results:
        desc = p.get("description", "") or ""
        if desc:
            desc = f" - {desc[:60]}"
        print(f"  {p['id']}: {p['name']}{desc}")


def search_templates(tc_query, keyword, *, auth=None):
    """搜索模板（按名称或 ID 关键词）"""
    data = tc_get(tc_query,
                  "buildTypes?locator=templateFlag:true,count:500&fields=buildType(id,name,projectName,projectId)",
                  auth=auth)
    kw = keyword.lower()
    results = []
    for bt in data.get("buildType", []):
        name = bt.get("name", "")
        bid = bt.get("id", "")
        if kw in name.lower() or kw in bid.lower():
            results.append(bt)
    if not results:
        print(f"No templates matching '{keyword}'")
        return
    print(f"Found {len(results)} template(s) matching '{keyword}':")
    for bt in results:
        print(f"  {bt['id']}: {bt['name']} [{bt.get('projectName', '')}]")


def search_builds(tc_query, keyword, *, project=None, auth=None):
    """搜索构建配置（按名称或 ID 关键词）"""
    if project:
        path = f"buildTypes?locator=project:(id:{project}),count:500&fields=buildType(id,name,projectName)"
    else:
        path = "buildTypes?locator=count:500&fields=buildType(id,name,projectName)"
    data = tc_get(tc_query, path, auth=auth)
    kw = keyword.lower()
    results = []
    for bt in data.get("buildType", []):
        name = bt.get("name", "")
        bid = bt.get("id", "")
        if kw in name.lower() or kw in bid.lower():
            results.append(bt)
    if not results:
        print(f"No build configs matching '{keyword}'")
        return
    print(f"Found {len(results)} build config(s) matching '{keyword}':")
    for bt in results:
        print(f"  {bt['id']}: {bt['name']} [{bt.get('projectName', '')}]")


def search_audit(tc_query, template_id, *, version=None, auth=None):
    """搜索审计事件"""
    path = f"audit?locator=buildType:(id:{template_id}),action:build_type_template_edit_settings,count:30,start:0"
    data = tc_get(tc_query, path, auth=auth)
    events = data.get("auditEvent", [])
    if not events:
        print(f"No audit events for {template_id}")
        return
    for e in events:
        bt_id = ""
        ver_from = ver_to = ""
        for ent in e.get("relatedEntities", {}).get("entity", []):
            if ent.get("type") == "buildType":
                bt_id = ent.get("buildType", {}).get("id", "")
            if ent.get("type") == "settingsChange":
                iid = ent.get("internalId", "")
                parts = iid.split("|")
                if len(parts) == 3:
                    ver_from, ver_to = parts[1], parts[2]
        if version and ver_to != str(version) and ver_from != str(version):
            continue
        user = e.get("user", {}).get("username", "?")
        comment = e.get("comment", "")[:50]
        print(f"  audit={e['id']}  {bt_id}  v{ver_from}->v{ver_to}  @{user}  {comment}")


def main():
    parser = argparse.ArgumentParser(description="TeamCity 搜索工具")
    parser.add_argument("type", choices=["projects", "templates", "builds", "audit"],
                        help="搜索类型")
    parser.add_argument("keyword", help="搜索关键词（或模板 ID，audit 模式）")
    parser.add_argument("--project", help="限定项目 ID（builds 模式）")
    parser.add_argument("--version", help="过滤版本号（audit 模式）")
    parser.add_argument("--tc-query", dest="tc_query", help="tc-query.ps1 路径")
    parser.add_argument("--tc-url", dest="tc_url", help="TeamCity 服务器地址（独立模式）")
    parser.add_argument("--username", help="用户名（独立模式）")
    parser.add_argument("--password", help="密码（独立模式）")
    args = parser.parse_args()

    auth = None
    tc_query = None
    if args.username and args.password:
        if not args.tc_url:
            print("ERROR: --tc-url required with --username/--password", file=sys.stderr)
            sys.exit(1)
        auth = {"url": args.tc_url, "username": args.username, "password": args.password}
    else:
        tc_query = args.tc_query or find_tc_query()
        if not tc_query or not os.path.isfile(tc_query):
            print("ERROR: tc-query.ps1 not found. "
                  "Use --tc-url/--username/--password for standalone mode.", file=sys.stderr)
            sys.exit(1)

    if args.type == "projects":
        search_projects(tc_query, args.keyword, auth=auth)
    elif args.type == "templates":
        search_templates(tc_query, args.keyword, auth=auth)
    elif args.type == "builds":
        search_builds(tc_query, args.keyword, project=args.project, auth=auth)
    elif args.type == "audit":
        search_audit(tc_query, args.keyword, version=args.version, auth=auth)


if __name__ == "__main__":
    main()
