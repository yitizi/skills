#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""TeamCity 模板/构建配置导入工具

从 tc-export.py 导出的 JSON 文件导入到目标模板/构建配置。
通过 REST API 逐组件 PUT（参数、步骤、特性、触发器、设置）。

用法:
  # Skill 模式（通过 tc-query.ps1）
  python tc-import.py <目标ID> <export.json>
  python tc-import.py <目标ID> <export.json> --dry-run
  python tc-import.py <目标ID> <export.json> --only parameters,steps

  # 独立模式（直接指定账密）
  python tc-import.py <目标ID> <export.json> --tc-url http://tc:8111 --username admin --password pass

参数:
  目标ID          目标模板或构建配置的外部 ID
  export.json     tc-export.py 导出的 JSON 文件

选项:
  --dry-run       只预览，不执行写操作
  --only COMPS    只导入指定组件（逗号分隔: parameters,steps,features,triggers,settings）
  --tc-query PATH tc-query.ps1 路径
  --tc-url URL    TeamCity 服务器地址（独立模式）
  --username USER 用户名（独立模式）
  --password PASS 密码（独立模式）

注意:
  - 导入会 PUT 整个组件（整体替换），目标模板中未包含在 JSON 中的参数/步骤会被删除
  - VCS root entries 和 agent requirements 不自动导入（跨环境时 VCS root ID 可能不同）
  - 建议先用 --dry-run 预览，确认后再执行
"""

import sys
import os
import json
import argparse
import subprocess


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
    """转义 PowerShell 单引号字符串中的单引号（' → ''）"""
    return s.replace("'", "''")


# 敏感参数名关键词，预览时掩码值
_SENSITIVE_KEYWORDS = {"password", "token", "secret", "key", "credential", "apikey", "api_key"}


def _is_sensitive(name):
    name_lower = name.lower()
    return any(k in name_lower for k in _SENSITIVE_KEYWORDS)


def tc_put(tc_query, path, body_json, *, auth=None):
    """调用 PUT（通过临时文件传递 body，避免引号问题）"""
    import tempfile
    body_str = json.dumps(body_json, ensure_ascii=False)
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8")
    try:
        tmp.write(body_str)
        tmp.close()
        tmp_path = tmp.name.replace("\\", "/")
        if auth:
            # 独立模式：直接 curl，用 -w 检查 HTTP 状态码
            import base64
            import shutil
            cred = base64.b64encode(
                f"{auth['username']}:{auth['password']}".encode("utf-8")
            ).decode("ascii")
            url = f"{auth['url'].rstrip('/')}/httpAuth/app/rest/{path}"
            curl = shutil.which("curl.exe") or shutil.which("curl") or "curl"
            resp_file = tempfile.NamedTemporaryFile(suffix=".resp", delete=False)
            resp_file.close()
            cmd = [
                curl, "-s", "-X", "PUT",
                "-H", f"Authorization: Basic {cred}",
                "-H", "Content-Type: application/json; charset=utf-8",
                "-H", "Accept: application/json",
                "--data-binary", f"@{tmp.name}",
                "-o", resp_file.name,
                "-w", "%{http_code}",
                url,
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
            http_code = result.stdout.strip()
            with open(resp_file.name, "r", encoding="utf-8") as f:
                out = f.read()
            os.unlink(resp_file.name)
            if result.returncode != 0:
                return False, f"curl failed (exit {result.returncode}): {result.stderr}"
            if http_code and http_code[0] in ("4", "5"):
                return False, f"HTTP {http_code}: {out[:300]}"
        else:
            # Skill 模式：通过 tc-query.ps1（已内置 HTTP 状态检查）
            cmd = [
                "powershell", "-ExecutionPolicy", "Bypass", "-Command",
                f"$b = Get-Content '{_ps_escape(tmp_path)}' -Raw -Encoding UTF8; "
                f"& '{_ps_escape(tc_query)}' -Path '{_ps_escape(path)}' -Method PUT -Body $b"
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
            if result.returncode != 0:
                return False, result.stderr or result.stdout
            out = result.stdout
        # TC REST API 错误以固定前缀开头，不能用 "error" 子串判断（响应内容可能含脚本文本）
        stripped = out.lstrip()
        if (stripped.startswith("Error has occurred during request processing") or
                stripped.startswith("Responding with error, status code:")):
            return False, out
        return True, out
    finally:
        os.unlink(tmp.name)


def preview_component(name, data, label):
    """预览组件内容"""
    if not data:
        print(f"  {label}: (empty)")
        return

    # 根据组件类型确定数组字段名
    array_keys = {
        "parameters": "property",
        "steps": "step",
        "features": "feature",
        "triggers": "trigger",
        "settings": "property",
    }
    arr_key = array_keys.get(name, "property")
    items = data.get(arr_key, [])
    count = len(items) if isinstance(items, list) else 0
    print(f"  {label}: {count} items")

    if name == "parameters":
        for p in items[:5]:
            pname = p.get("name", "?")
            val = "***" if _is_sensitive(pname) else p.get("value", "")
            if len(val) > 60:
                val = val[:60] + "..."
            print(f"    - {pname} = {val}")
        if count > 5:
            print(f"    ... and {count - 5} more")

    elif name == "steps":
        for s in items:
            print(f"    - [{s.get('id','')}] {s.get('name','')} ({s.get('type','')})")

    elif name in ("features", "triggers"):
        for item in items:
            print(f"    - [{item.get('id','')}] {item.get('type','')}")

    elif name == "settings":
        for p in items:
            print(f"    - {p.get('name','')} = {p.get('value','')}")


def main():
    parser = argparse.ArgumentParser(description="TeamCity 模板/构建配置导入")
    parser.add_argument("target_id", help="目标模板或构建配置外部 ID")
    parser.add_argument("input_file", help="tc-export.py 导出的 JSON 文件")
    parser.add_argument("--dry-run", action="store_true", help="只预览不执行")
    parser.add_argument("--yes", "-y", action="store_true", help="跳过交互确认，直接执行导入")
    parser.add_argument("--only", help="只导入指定组件（逗号分隔）")
    parser.add_argument("--tc-query", dest="tc_query", help="tc-query.ps1 路径")
    # 独立模式
    parser.add_argument("--tc-url", dest="tc_url", help="TeamCity 服务器地址（独立模式）")
    parser.add_argument("--username", help="用户名（独立模式）")
    parser.add_argument("--password", help="密码（独立模式）")
    args = parser.parse_args()

    # 判断认证模式
    auth = None
    tc_query = None
    if args.username and args.password:
        if not args.tc_url:
            print("ERROR: --tc-url is required when using --username/--password", file=sys.stderr)
            sys.exit(1)
        auth = {"url": args.tc_url, "username": args.username, "password": args.password}
    else:
        tc_query = args.tc_query or find_tc_query()
        if not tc_query or not os.path.isfile(tc_query):
            print("ERROR: tc-query.ps1 not found. "
                  "Use --tc-url/--username/--password for standalone mode.", file=sys.stderr)
            sys.exit(1)

    with open(args.input_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    meta = data.get("meta", {})
    print(f"Source: {meta.get('name', '?')} ({meta.get('id', '?')})")
    print(f"Version: {meta.get('version', '?')} | Exported: {meta.get('exportedAt', '?')}")
    print(f"Target: {args.target_id}")
    print()

    # 确定要导入的组件
    all_components = ["parameters", "steps", "features", "triggers", "settings"]
    if args.only:
        components = [c.strip() for c in args.only.split(",")]
        invalid = [c for c in components if c not in all_components]
        if invalid:
            print(f"ERROR: unknown components: {invalid}", file=sys.stderr)
            print(f"Valid: {all_components}", file=sys.stderr)
            sys.exit(1)
    else:
        components = all_components

    # 组件 → REST API 路径
    api_paths = {
        "parameters": f"buildTypes/id:{args.target_id}/parameters",
        "steps": f"buildTypes/id:{args.target_id}/steps",
        "features": f"buildTypes/id:{args.target_id}/features",
        "triggers": f"buildTypes/id:{args.target_id}/triggers",
        "settings": f"buildTypes/id:{args.target_id}/settings",
    }

    labels = {
        "parameters": "Parameters",
        "steps": "Steps",
        "features": "Features",
        "triggers": "Triggers",
        "settings": "Settings",
    }

    # 过滤 inherited 参数（只导入模板自身定义的参数）
    if "parameters" in components and "parameters" in data:
        all_params = data["parameters"].get("property", [])
        own_params = [p for p in all_params if not p.get("inherited")]
        if len(own_params) < len(all_params):
            print(f"NOTE: filtered {len(all_params) - len(own_params)} inherited parameters, "
                  f"importing {len(own_params)} own parameters only.")
            data["parameters"]["property"] = own_params
            print()

    # 预览
    print("Components to import:")
    for comp in components:
        comp_data = data.get(comp, {})
        preview_component(comp, comp_data, labels[comp])
    print()

    # VCS / requirements 提醒
    vcs = data.get("vcs-root-entries", {})
    vcs_items = vcs.get("vcs-root-entry", [])
    if vcs_items:
        print(f"NOTE: VCS root entries ({len(vcs_items)}) not imported (IDs may differ across environments).")
        for v in vcs_items:
            print(f"  - {v.get('id', '?')}")
        print()

    if args.dry_run:
        print("DRY RUN: no changes made.")
        return

    # 确认
    if not args.yes:
        print("Proceed with import? This will REPLACE all items in each component. [y/N] ", end="")
        answer = input().strip().lower()
        if answer != "y":
            print("Cancelled.")
            return

    # 执行导入
    print()
    errors = []
    for comp in components:
        comp_data = data.get(comp, {})
        if not comp_data:
            print(f"  {labels[comp]}: skipped (empty)")
            continue

        path = api_paths[comp]
        ok, result = tc_put(tc_query, path, comp_data, auth=auth)
        if ok:
            print(f"  {labels[comp]}: OK")
        else:
            print(f"  {labels[comp]}: FAILED - {result[:200]}")
            errors.append(comp)

    print()
    if errors:
        print(f"DONE with errors: {errors}")
        sys.exit(1)
    else:
        print("DONE: all components imported successfully.")


if __name__ == "__main__":
    main()
