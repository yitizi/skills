#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""TeamCity 配置版本 diff 工具

从 settingsDiffView.html 提取两个版本的 XML 配置，输出可读的 unified diff。
自动检测并解码嵌入的 base64 脚本（如 PRE_DEPLOY_B64、APOLLO_B64），
用解码后的内容替换原始 base64 字符串，使 diff 可读。

用法:
  python tc-diff.py <ID> <fromVersion> <toVersion> [选项]

参数:
  ID             模板或构建配置的外部 ID（如 FlinkDeployK8SImageGradleTemplate）
  fromVersion    起始版本号
  toVersion      目标版本号

选项:
  --type TYPE      template（默认）或 buildType
  --raw            不解码 base64，输出原始 diff
  --context N      diff 上下文行数（默认 3）
  --tc-query PATH  tc-query.ps1 路径（默认 auto-detect）
  --tc-url URL     TeamCity 服务器地址（独立模式）
  --username USER  用户名（独立模式）
  --password PASS  密码（独立模式）

示例:
  # Skill 模式
  python tc-diff.py FlinkDeployK8SImageGradleTemplate 64 65
  python tc-diff.py FlinkDeployK8SImageGradleTemplate 64 65 --raw
  python tc-diff.py SomeBuildConfig 10 11 --type buildType

  # 独立模式
  python tc-diff.py FlinkDeployK8SImageGradleTemplate 64 65 --tc-url http://tc:8111 --username admin --password pass
"""

import sys
import os
import re
import html
import base64
import difflib
import argparse
import subprocess


def find_tc_query():
    """自动查找 tc-query.ps1"""
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


def fetch_diff_html(tc_query, prefix, ext_id, ver_from, ver_to, *, auth=None):
    """获取 settingsDiffView HTML"""
    raw_path = f"admin/settingsDiffView.html?id={prefix}:{ext_id}&versionBefore={ver_from}&versionAfter={ver_to}"
    if auth:
        import base64 as b64mod
        import shutil
        url = f"{auth['url'].rstrip('/')}/{raw_path}"
        cred = b64mod.b64encode(
            f"{auth['username']}:{auth['password']}".encode("utf-8")
        ).decode("ascii")
        curl = shutil.which("curl.exe") or shutil.which("curl") or "curl"
        cmd = [curl, "-s", "-H", f"Authorization: Basic {cred}", url]
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
            print(f"ERROR: tc-query.ps1 failed: {result.stderr}", file=sys.stderr)
            sys.exit(1)
        return result.stdout


def extract_textarea(html_content, textarea_id):
    """从 HTML 中提取指定 textarea 的内容"""
    pattern = r'<textarea[^>]*id="' + textarea_id + r'"[^>]*>(.*?)</textarea>'
    m = re.search(pattern, html_content, re.DOTALL)
    if not m:
        return ""
    return html.unescape(m.group(1))


def decode_b64_in_text(text):
    """检测并解码文本中的 *_B64='...' 模式，返回替换后的文本"""
    def replace_b64(match):
        var_name = match.group(1)
        b64_val = match.group(2)
        try:
            decoded = base64.b64decode(b64_val).decode("utf-8")
            lines = decoded.splitlines()
            # 用注释标记 + 解码内容替换
            header = f"{var_name}='<BASE64_DECODED lines={len(lines)}>'"
            body = "\n".join(f"# |{var_name}| {line}" for line in lines)
            footer = f"# |{var_name}| </BASE64_DECODED>"
            return f"{header}\n{body}\n{footer}"
        except Exception:
            return match.group(0)  # 解码失败，保留原始

    return re.sub(r"([A-Z_]+_B64)='([A-Za-z0-9+/=]{64,})'", replace_b64, text)


def main():
    parser = argparse.ArgumentParser(description="TeamCity 配置版本 diff 工具")
    parser.add_argument("id", help="模板或构建配置外部 ID")
    parser.add_argument("from_version", help="起始版本号")
    parser.add_argument("to_version", help="目标版本号")
    parser.add_argument("--type", default="template", choices=["template", "buildType"],
                        help="ID 类型：template（默认）或 buildType")
    parser.add_argument("--raw", action="store_true", help="不解码 base64")
    parser.add_argument("--context", type=int, default=3, help="diff 上下文行数（默认 3）")
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

    # 获取 diff HTML
    html_content = fetch_diff_html(tc_query, args.type, args.id, args.from_version, args.to_version, auth=auth)

    # 提取 before/after XML
    before_text = extract_textarea(html_content, "tbeforePlain")
    after_text = extract_textarea(html_content, "tafterPlain")

    if not before_text and not after_text:
        print("ERROR: no diff data found in response. Check ID, prefix (--type), and version numbers.", file=sys.stderr)
        sys.exit(1)

    # 解码 base64（除非 --raw）
    if not args.raw:
        before_text = decode_b64_in_text(before_text)
        after_text = decode_b64_in_text(after_text)

    # 计算 diff
    before_lines = before_text.splitlines()
    after_lines = after_text.splitlines()

    label_before = f"v{args.from_version} ({args.type}:{args.id})"
    label_after = f"v{args.to_version} ({args.type}:{args.id})"

    diff = list(difflib.unified_diff(
        before_lines, after_lines,
        fromfile=label_before, tofile=label_after,
        lineterm="", n=args.context
    ))

    if not diff:
        print("No differences found.")
        return

    for line in diff:
        print(line)


if __name__ == "__main__":
    main()
