#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""TeamCity 模板/构建配置导出工具

导出当前版本（REST API JSON）或历史版本（settingsDiffView XML → JSON 转换），
输出统一的 JSON 格式文件，可直接用于 tc-import.py 导入。

用法:
  # Skill 模式（通过 tc-query.ps1，使用 .netrc + config.env）
  python tc-export.py <ID> -o output.json
  python tc-export.py <ID> --version 65 -o output.json

  # 独立模式（直接指定账密，不依赖 skill 基础设施）
  python tc-export.py <ID> --tc-url http://tc:8111 --username admin --password pass -o output.json
  python tc-export.py <ID> --tc-url http://tc:8111 --username admin --password pass --version 65 -o output.json

参数:
  ID                模板或构建配置外部 ID
  -o, --output      输出文件路径（默认 stdout）
  --version N       导出历史版本号（不指定则导出当前版本）
  --type TYPE       template（默认）或 buildType
  --tc-query PATH   tc-query.ps1 路径
  --tc-url URL      TeamCity 服务器地址（独立模式必填）
  --username USER   用户名（独立模式必填）
  --password PASS   密码（独立模式必填）
"""

import sys
import os
import json
import re
import html
import argparse
import subprocess
import xml.etree.ElementTree as ET
from datetime import datetime


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


def _build_auth_header(username, password):
    """构建 Basic 认证头"""
    import base64
    cred = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
    return f"Basic {cred}"


def _find_curl():
    """找到可用的 curl 可执行文件"""
    import shutil
    # Windows 优先 curl.exe（避免 PowerShell alias 干扰）
    if sys.platform == "win32":
        p = shutil.which("curl.exe")
        if p:
            return p
    return shutil.which("curl") or "curl"


def _ps_escape(s):
    """转义 PowerShell 单引号字符串中的单引号（' → ''）"""
    return s.replace("'", "''")


def tc_get(tc_query, path, *, auth=None):
    """GET 请求，返回 JSON。auth 为 None 时走 tc-query.ps1，否则直接 curl"""
    if auth:
        url = f"{auth['url'].rstrip('/')}/httpAuth/app/rest/{path}"
        header = _build_auth_header(auth["username"], auth["password"])
        curl = _find_curl()
        cmd = [curl, "-s", "-H", f"Authorization: {header}",
               "-H", "Accept: application/json", url]
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
        if result.returncode != 0:
            print(f"ERROR: curl failed: {result.stderr}", file=sys.stderr)
            sys.exit(1)
        return json.loads(result.stdout)
    else:
        cmd = [
            "powershell", "-ExecutionPolicy", "Bypass", "-Command",
            f"& '{_ps_escape(tc_query)}' -Path '{_ps_escape(path)}'"
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
        if result.returncode != 0:
            print(f"ERROR: {result.stderr}", file=sys.stderr)
            sys.exit(1)
        return json.loads(result.stdout)


def tc_get_raw(tc_query, raw_path, *, auth=None):
    """GET 请求，返回原始文本。auth 为 None 时走 tc-query.ps1 -RawPath"""
    if auth:
        url = f"{auth['url'].rstrip('/')}/{raw_path}"
        header = _build_auth_header(auth["username"], auth["password"])
        curl = _find_curl()
        cmd = [curl, "-s", "-H", f"Authorization: {header}", url]
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
        if result.returncode != 0:
            print(f"ERROR: curl failed: {result.stderr}", file=sys.stderr)
            sys.exit(1)
        return result.stdout
    else:
        cmd = [
            "powershell", "-ExecutionPolicy", "Bypass", "-Command",
            f"& '{_ps_escape(tc_query)}' -Path '{_ps_escape(raw_path)}' -RawPath"
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
        if result.returncode != 0:
            print(f"ERROR: {result.stderr}", file=sys.stderr)
            sys.exit(1)
        return result.stdout


def export_current(tc_query, bt_id, *, auth=None):
    """通过 REST API 导出当前版本"""
    fields = (
        "id,name,projectName,projectId,templateFlag,"
        "parameters(property(name,value,inherited,type(rawValue))),"
        "steps(step(id,name,type,properties(property(name,value)))),"
        "features(feature(id,type,properties(property(name,value)))),"
        "triggers(trigger(id,type,properties(property(name,value)))),"
        "settings(property(name,value)),"
        "vcs-root-entries(vcs-root-entry(id,vcs-root(id,name),checkout-rules)),"
        "agent-requirements(agent-requirement(id,type,properties(property(name,value))))"
    )
    data = tc_get(tc_query, f"buildTypes/id:{bt_id}?fields={fields}", auth=auth)
    return {
        "meta": {
            "id": data.get("id", bt_id),
            "name": data.get("name", ""),
            "projectName": data.get("projectName", ""),
            "projectId": data.get("projectId", ""),
            "type": "template" if data.get("templateFlag") else "buildType",
            "version": "current",
            "exportedAt": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "source": "rest-api",
        },
        "parameters": data.get("parameters", {}),
        "steps": data.get("steps", {}),
        "features": data.get("features", {}),
        "triggers": data.get("triggers", {}),
        "settings": data.get("settings", {}),
        "vcs-root-entries": data.get("vcs-root-entries", {}),
        "agent-requirements": data.get("agent-requirements", {}),
    }


# ── XML → JSON 转换（历史版本） ──────────────────────────────


def _parse_param_elem(elem):
    """XML <param> → REST API JSON property"""
    name = elem.get("name", "")
    # value 可能在 attribute 或 text（CDATA）中
    value = elem.get("value")
    if value is None:
        value = elem.text or ""
    prop = {"name": name, "value": value}
    spec = elem.get("spec")
    if spec:
        prop["type"] = {"rawValue": spec}
    return prop


def _parse_conditions(runner_elem):
    """XML <conditions> → teamcity.step.conditions JSON 字符串"""
    cond_elem = runner_elem.find("conditions")
    if cond_elem is None:
        return None
    conds = []
    # 常见条件类型映射
    tag_map = {
        "matches": "MATCHES",
        "does-not-match": "DOES_NOT_MATCH",
        "contains": "CONTAINS",
        "does-not-contain": "DOES_NOT_CONTAIN",
        "starts-with": "STARTS_WITH",
        "ends-with": "ENDS_WITH",
        "equals": "EQUALS",
        "does-not-equal": "DOES_NOT_EQUAL",
    }
    for child in cond_elem:
        cond_type = tag_map.get(child.tag, child.tag.upper().replace("-", "_"))
        cond_name = child.get("name", "")
        cond_value = child.get("value", "")
        conds.append([cond_type, cond_name, cond_value])
    return json.dumps(conds, ensure_ascii=False)


def _parse_runner(runner_elem):
    """XML <runner> → REST API JSON step"""
    props = []
    params_elem = runner_elem.find("parameters")
    if params_elem is not None:
        for p in params_elem.findall("param"):
            props.append(_parse_param_elem(p))
    # 条件转为 property
    cond_str = _parse_conditions(runner_elem)
    if cond_str:
        props.append({"name": "teamcity.step.conditions", "value": cond_str})
    return {
        "id": runner_elem.get("id", ""),
        "name": runner_elem.get("name", ""),
        "type": runner_elem.get("type", ""),
        "properties": {"property": props},
    }


def _parse_trigger_or_feature(elem):
    """XML <build-trigger> / <build-extension> → JSON"""
    props = []
    params_elem = elem.find("parameters")
    if params_elem is not None:
        for p in params_elem.findall("param"):
            props.append(_parse_param_elem(p))
    result = {
        "type": elem.get("type", ""),
        "properties": {"property": props},
    }
    eid = elem.get("id")
    if eid:
        result["id"] = eid
    return result


def xml_to_export_json(xml_text, bt_id, bt_type, version):
    """将 settingsDiffView 的 XML 转换为 export JSON 格式"""
    root = ET.fromstring(xml_text)
    settings = root.find("settings")
    if settings is None:
        print("ERROR: <settings> not found in XML", file=sys.stderr)
        sys.exit(1)

    # 元信息
    meta = {
        "id": bt_id,
        "name": root.findtext("name", ""),
        "type": bt_type,
        "version": version,
        "exportedAt": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "source": "settingsDiffView-xml",
    }

    # 参数
    params = []
    params_elem = settings.find("parameters")
    if params_elem is not None:
        for p in params_elem.findall("param"):
            params.append(_parse_param_elem(p))

    # 步骤
    steps = []
    runners_elem = settings.find("build-runners")
    if runners_elem is not None:
        for r in runners_elem.findall("runner"):
            steps.append(_parse_runner(r))

    # 触发器
    triggers = []
    triggers_elem = settings.find("build-triggers")
    if triggers_elem is not None:
        for t in triggers_elem.findall("build-trigger"):
            triggers.append(_parse_trigger_or_feature(t))

    # 特性（build-extensions）
    features = []
    ext_elem = settings.find("build-extensions")
    if ext_elem is not None:
        for e in ext_elem.findall("extension"):
            features.append(_parse_trigger_or_feature(e))

    # 设置（options）
    opts = []
    opts_elem = settings.find("options")
    if opts_elem is not None:
        for o in opts_elem.findall("option"):
            opts.append({"name": o.get("name", ""), "value": o.get("value", "")})

    # VCS root entries
    vcs_entries = []
    vcs_elem = settings.find("vcs-settings")
    if vcs_elem is not None:
        for v in vcs_elem.findall("vcs-entry-ref"):
            vcs_entries.append({
                "id": v.get("root-id", ""),
                "vcs-root": {"id": v.get("root-id", "")},
                "checkout-rules": v.get("checkout-rules", ""),
            })

    # Agent requirements
    reqs = []
    reqs_elem = settings.find("requirements")
    if reqs_elem is not None:
        for r in reqs_elem:
            props = []
            rp = r.find("parameters")
            if rp is not None:
                for p in rp.findall("param"):
                    props.append(_parse_param_elem(p))
            reqs.append({
                "id": r.get("id", ""),
                "type": r.get("type", r.tag),
                "properties": {"property": props},
            })

    return {
        "meta": meta,
        "parameters": {"property": params},
        "steps": {"step": steps},
        "features": {"feature": features},
        "triggers": {"trigger": triggers},
        "settings": {"property": opts},
        "vcs-root-entries": {"vcs-root-entry": vcs_entries},
        "agent-requirements": {"agent-requirement": reqs},
    }


def export_historical(tc_query, bt_id, bt_type, version, *, auth=None):
    """通过 settingsDiffView 导出历史版本"""
    # 用 version 和 version+1 获取，version 对应 tbeforePlain
    # 但 version+1 可能不存在。更可靠的方式：
    # 用 version-1 和 version，version 对应 tafterPlain
    ver_before = int(version) - 1
    ver_after = int(version)

    raw_path = (
        f"admin/settingsDiffView.html?"
        f"id={bt_type}:{bt_id}&versionBefore={ver_before}&versionAfter={ver_after}"
    )
    html_content = tc_get_raw(tc_query, raw_path, auth=auth)

    # 提取 tafterPlain（目标版本）
    pattern = r'<textarea[^>]*id="tafterPlain"[^>]*>(.*?)</textarea>'
    m = re.search(pattern, html_content, re.DOTALL)

    if not m:
        # 如果 version-1 不存在（version=1 的情况），尝试 version 作为 before
        raw_path2 = (
            f"admin/settingsDiffView.html?"
            f"id={bt_type}:{bt_id}&versionBefore={ver_after}&versionAfter={ver_after + 1}"
        )
        html_content = tc_get_raw(tc_query, raw_path2, auth=auth)
        pattern_before = r'<textarea[^>]*id="tbeforePlain"[^>]*>(.*?)</textarea>'
        m = re.search(pattern_before, html_content, re.DOTALL)
        if not m:
            print(f"ERROR: cannot extract version {version} XML. "
                  f"Tried v{ver_before}→v{ver_after} and v{ver_after}→v{ver_after+1}.",
                  file=sys.stderr)
            sys.exit(1)

    xml_text = html.unescape(m.group(1)).strip()
    return xml_to_export_json(xml_text, bt_id, bt_type, version)


def main():
    parser = argparse.ArgumentParser(description="TeamCity 模板/构建配置导出")
    parser.add_argument("id", help="模板或构建配置外部 ID")
    parser.add_argument("-o", "--output", help="输出文件路径（默认 stdout）")
    parser.add_argument("--version", help="导出历史版本号（不指定则导出当前版本）")
    parser.add_argument("--type", default="template",
                        choices=["template", "buildType"], help="类型（默认 template）")
    parser.add_argument("--tc-query", dest="tc_query", help="tc-query.ps1 路径")
    # 独立模式：指定账密后直接 curl，不依赖 tc-query.ps1 和 skill 基础设施
    parser.add_argument("--tc-url", dest="tc_url", help="TeamCity 服务器地址（独立模式）")
    parser.add_argument("--username", help="用户名（独立模式）")
    parser.add_argument("--password", help="密码（独立模式）")
    args = parser.parse_args()

    # 判断认证模式
    auth = None
    tc_query = None
    if args.username and args.password:
        # 独立模式：直接 curl + Basic auth
        if not args.tc_url:
            print("ERROR: --tc-url is required when using --username/--password", file=sys.stderr)
            sys.exit(1)
        auth = {"url": args.tc_url, "username": args.username, "password": args.password}
    else:
        # Skill 模式：通过 tc-query.ps1
        tc_query = args.tc_query or find_tc_query()
        if not tc_query or not os.path.isfile(tc_query):
            print("ERROR: tc-query.ps1 not found. "
                  "Use --tc-url/--username/--password for standalone mode.", file=sys.stderr)
            sys.exit(1)

    if args.version:
        data = export_historical(tc_query, args.id, args.type, args.version, auth=auth)
    else:
        data = export_current(tc_query, args.id, auth=auth)

    output = json.dumps(data, indent=2, ensure_ascii=False)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output)
        name = data["meta"].get("name", args.id)
        ver = data["meta"].get("version", "current")
        print(f"OK: exported {name} v{ver} -> {args.output}", file=sys.stderr)
    else:
        print(output)


if __name__ == "__main__":
    main()
