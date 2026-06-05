#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""TeamCity 模板导入交付物打包工具

从 tc-export.py 导出的 JSON 生成独立的交付物目录，包含：
- template.json（模板配置数据）
- import.sh（Linux 导入脚本）
- import.ps1（Windows 导入脚本）
- README.md（使用说明）

用法:
  python tc-package.py <export.json> [-o <输出目录>]
  python tc-package.py template_v65.json
  python tc-package.py template_v65.json -o artifact/

交付物目录命名: <模板ID>-v<版本>-<日期>
"""

import sys
import os
import json
import shutil
import argparse
from datetime import datetime


def sanitize_name(name):
    """清理文件名中的特殊字符"""
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in name)


def generate_readme(meta, components_summary):
    """生成 README.md"""
    name = meta.get("name", "Unknown")
    mid = meta.get("id", "Unknown")
    version = meta.get("version", "?")
    exported = meta.get("exportedAt", "?")
    source_type = meta.get("type", "template")

    return f"""# TeamCity 模板导入交付物

## 模板信息

| 字段 | 值 |
|------|-----|
| 名称 | {name} |
| ID | {mid} |
| 类型 | {source_type} |
| 版本 | {version} |
| 导出时间 | {exported} |

## 内容

{components_summary}

## 前置要求

- TeamCity 服务器访问权限（需要 Project Admin 以上）
- 目标模板/构建配置已存在（脚本只替换配置，不创建新模板）
- `curl` 命令可用
- `python3`（Linux）或 `python`（Windows）可用

## 使用方法

### Linux

```bash
chmod +x import.sh
./import.sh -u <TC_URL> -U <用户名> -p <密码> -t <目标模板ID>

# 示例
./import.sh -u https://teamcity.example.com -U your_user -p your_password -t {mid}

# 预览（不执行）
./import.sh -u https://teamcity.example.com -U your_user -p your_password -t {mid} --dry-run

# 只导入步骤
./import.sh -u https://teamcity.example.com -U your_user -p your_password -t {mid} --only steps
```

### Windows (PowerShell)

```powershell
.\\import.ps1 -TcUrl <TC_URL> -Username <用户名> -Password <密码> -TargetId <目标模板ID>

# 示例
.\\import.ps1 -TcUrl https://teamcity.example.com -Username your_user -Password your_password -TargetId {mid}

# 预览（不执行）
.\\import.ps1 -TcUrl https://teamcity.example.com -Username your_user -Password your_password -TargetId {mid} -DryRun

# 只导入参数和步骤
.\\import.ps1 -TcUrl https://teamcity.example.com -Username your_user -Password your_password -TargetId {mid} -Only "parameters,steps"
```

## 注意事项

- 导入会**整体替换**目标模板中对应组件的所有内容
- VCS root entries 不包含在导入中（跨环境时 ID 可能不同，需手动配置）
- inherited 参数会被自动过滤，只导入模板自身定义的参数
- 建议先用 `--dry-run` 预览确认后再执行
- 导入前建议先导出目标模板当前配置作为备份
"""


def main():
    parser = argparse.ArgumentParser(description="TeamCity 模板导入交付物打包")
    parser.add_argument("input_file", help="tc-export.py 导出的 JSON 文件")
    parser.add_argument("-o", "--output-dir", default="artifact",
                        help="交付物输出根目录（默认 artifact/）")
    args = parser.parse_args()

    with open(args.input_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    meta = data.get("meta", {})
    mid = meta.get("id", "unknown")
    version = meta.get("version", "unknown")
    today = datetime.now().strftime("%Y%m%d")

    # 交付物目录名
    dir_name = f"{sanitize_name(mid)}-v{version}-{today}"
    out_dir = os.path.join(args.output_dir, dir_name)
    os.makedirs(out_dir, exist_ok=True)

    # 1. 写 template.json
    template_path = os.path.join(out_dir, "template.json")
    with open(template_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    # 2. 复制 import.sh 和 import.ps1
    script_dir = os.path.join(os.path.dirname(__file__), "deliverable")
    for script in ["import.sh", "import.ps1"]:
        src = os.path.join(script_dir, script)
        dst = os.path.join(out_dir, script)
        if os.path.isfile(src):
            if script.endswith(".ps1"):
                # PowerShell 5.1 的 here-string (@'...'@) 要求 CRLF 行尾才能正确识别终止符
                with open(src, "r", encoding="utf-8") as f:
                    content = f.read()
                content = content.replace("\r\n", "\n").replace("\n", "\r\n")
                with open(dst, "w", encoding="utf-8", newline="") as f:
                    f.write(content)
            else:
                shutil.copy2(src, dst)

    # 3. 组件摘要
    summary_lines = []
    comp_map = {
        "parameters": ("property", "参数"),
        "steps": ("step", "构建步骤"),
        "features": ("feature", "特性"),
        "triggers": ("trigger", "触发器"),
        "settings": ("property", "设置"),
    }
    for comp, (arr_key, label) in comp_map.items():
        items = data.get(comp, {}).get(arr_key, [])
        # 过滤 inherited
        if comp == "parameters":
            items = [p for p in items if not p.get("inherited")]
        count = len(items)
        summary_lines.append(f"- **{label}**: {count} 项")
        if comp == "steps":
            for s in items:
                summary_lines.append(f"  - `{s.get('id','')}` {s.get('name','')}")
    components_summary = "\n".join(summary_lines)

    # 4. 写 README.md
    readme_path = os.path.join(out_dir, "README.md")
    with open(readme_path, "w", encoding="utf-8") as f:
        f.write(generate_readme(meta, components_summary))

    # 输出结果
    print(f"交付物已生成: {out_dir}/")
    print(f"  template.json  - 模板配置")
    print(f"  import.sh      - Linux 导入脚本")
    print(f"  import.ps1     - Windows 导入脚本")
    print(f"  README.md      - 使用说明")


if __name__ == "__main__":
    main()
