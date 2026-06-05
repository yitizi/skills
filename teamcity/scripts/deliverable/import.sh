#!/bin/bash
# TeamCity 模板导入脚本（Linux 独立版）
# 从 template.json 导入参数、步骤、特性、触发器、设置到目标模板/构建配置
#
# 依赖：curl, python3
#
# 用法:
#   ./import.sh -u <TC_URL> -U <用户名> -p <密码> -t <目标模板ID> [-f <json文件>]
#   ./import.sh -u http://tc.example.com:8111 -U admin -p pass -t MyTemplate
#   ./import.sh -u http://tc.example.com:8111 -U admin -p pass -t MyTemplate -f template.json --dry-run
#   ./import.sh -u http://tc.example.com:8111 -U admin -p pass -t MyTemplate --only parameters,steps

set -euo pipefail

# ── 参数解析 ─────────────────────────────────────────────

TC_URL=""
TC_USER=""
TC_PASS=""
TARGET_ID=""
JSON_FILE="template.json"
DRY_RUN=false
ONLY=""

usage() {
    cat <<'EOF'
用法: ./import.sh -u <TC_URL> -U <用户名> -p <密码> -t <目标ID> [选项]

必选:
  -u URL      TeamCity 服务器地址（如 http://tc.example.com:8111）
  -U USER     用户名
  -p PASS     密码
  -t ID       目标模板或构建配置的外部 ID

可选:
  -f FILE     JSON 文件路径（默认 template.json）
  --dry-run   只预览，不执行
  --only X    只导入指定组件（逗号分隔: parameters,steps,features,triggers,settings）
EOF
    exit 1
}

while [ $# -gt 0 ]; do
    case "$1" in
        -u) TC_URL="$2"; shift 2 ;;
        -U) TC_USER="$2"; shift 2 ;;
        -p) TC_PASS="$2"; shift 2 ;;
        -t) TARGET_ID="$2"; shift 2 ;;
        -f) JSON_FILE="$2"; shift 2 ;;
        --dry-run) DRY_RUN=true; shift ;;
        --only) ONLY="$2"; shift 2 ;;
        *) echo "未知参数: $1"; usage ;;
    esac
done

[ -z "$TC_URL" ] || [ -z "$TC_USER" ] || [ -z "$TC_PASS" ] || [ -z "$TARGET_ID" ] && usage
[ ! -f "$JSON_FILE" ] && echo "ERROR: $JSON_FILE not found" && exit 1

TC_URL="${TC_URL%/}"
API_BASE="$TC_URL/httpAuth/app/rest"

# ── 工具函数 ─────────────────────────────────────────────

tc_put() {
    local path="$1"
    local body_file="$2"
    local response
    local http_code

    response=$(curl -s -w "\n%{http_code}" -X PUT \
        -u "$TC_USER:$TC_PASS" \
        -H "Content-Type: application/json; charset=utf-8" \
        -H "Accept: application/json" \
        --data-binary "@$body_file" \
        "$API_BASE/$path")

    http_code=$(echo "$response" | tail -1)
    local body
    body=$(echo "$response" | sed '$d')

    if [ "$http_code" -ge 400 ] 2>/dev/null; then
        echo "FAILED (HTTP $http_code)"
        echo "  $body" | head -3
        return 1
    fi
    echo "OK"
    return 0
}

# ── 主逻辑 ───────────────────────────────────────────────

# 读取元信息
META=$(python3 -c "
import json,sys
d = json.load(open('$JSON_FILE', encoding='utf-8'))
m = d.get('meta', {})
print(f\"{m.get('name','?')}|{m.get('id','?')}|{m.get('version','?')}|{m.get('exportedAt','?')}\")
")
IFS='|' read -r SRC_NAME SRC_ID SRC_VER SRC_DATE <<< "$META"

echo "Source: $SRC_NAME ($SRC_ID)"
echo "Version: $SRC_VER | Exported: $SRC_DATE"
echo "Target: $TARGET_ID @ $TC_URL"
echo ""

# 确定导入组件
ALL_COMPS="parameters steps features triggers settings"
if [ -n "$ONLY" ]; then
    COMPS=$(echo "$ONLY" | tr ',' ' ')
else
    COMPS="$ALL_COMPS"
fi

# 提取各组件到临时文件并预览
TMPDIR=$(mktemp -d)
trap "rm -rf $TMPDIR" EXIT

for comp in $COMPS; do
    python3 -c "
import json,sys
d = json.load(open('$JSON_FILE', encoding='utf-8'))
comp_data = d.get('$comp', {})

# 过滤 inherited 参数
if '$comp' == 'parameters':
    props = comp_data.get('property', [])
    own = [p for p in props if not p.get('inherited')]
    if len(own) < len(props):
        print(f'NOTE: filtered {len(props)-len(own)} inherited params, keeping {len(own)} own', file=sys.stderr)
    comp_data['property'] = own

# 写入临时文件
with open('$TMPDIR/${comp}.json', 'w', encoding='utf-8') as f:
    json.dump(comp_data, f, ensure_ascii=False)

# 预览
array_keys = {'parameters':'property','steps':'step','features':'feature','triggers':'trigger','settings':'property'}
arr = comp_data.get(array_keys.get('$comp','property'), [])
print(f'  ${comp}: {len(arr)} items')
if '$comp' == 'steps':
    for s in arr:
        print(f'    - [{s.get(\"id\",\"\")}] {s.get(\"name\",\"\")} ({s.get(\"type\",\"\")})')
elif '$comp' == 'parameters':
    _sens = {'password','token','secret','key','credential','apikey','api_key'}
    for p in arr[:5]:
        pn = p.get('name','?')
        v = '***' if any(k in pn.lower() for k in _sens) else p.get('value','')
        if len(v)>50: v=v[:50]+'...'
        print(f'    - {pn} = {v}')
    if len(arr)>5: print(f'    ... and {len(arr)-5} more')
elif '$comp' == 'settings':
    for p in arr:
        print(f'    - {p.get(\"name\",\"?\")} = {p.get(\"value\",\"\")}')
" 2>&1
done

echo ""

if [ "$DRY_RUN" = true ]; then
    echo "DRY RUN: no changes made."
    exit 0
fi

# 确认
read -p "Proceed with import? This will REPLACE all items in each component. [y/N] " answer
if [ "$answer" != "y" ] && [ "$answer" != "Y" ]; then
    echo "Cancelled."
    exit 0
fi

echo ""
ERRORS=0
for comp in $COMPS; do
    COMP_FILE="$TMPDIR/${comp}.json"
    if [ ! -s "$COMP_FILE" ] || [ "$(cat "$COMP_FILE")" = "{}" ]; then
        echo "  $comp: skipped (empty)"
        continue
    fi
    printf "  %s: " "$comp"
    if ! tc_put "buildTypes/id:$TARGET_ID/$comp" "$COMP_FILE"; then
        ERRORS=$((ERRORS + 1))
    fi
done

echo ""
if [ $ERRORS -gt 0 ]; then
    echo "DONE with $ERRORS errors."
    exit 1
else
    echo "DONE: all components imported successfully."
fi
