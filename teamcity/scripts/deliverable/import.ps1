param(
    [Parameter(Mandatory=$true)]
    [string]$TcUrl,

    [Parameter(Mandatory=$true)]
    [string]$Username,

    [Parameter(Mandatory=$true)]
    [string]$Password,

    [Parameter(Mandatory=$true)]
    [string]$TargetId,

    [string]$JsonFile = "template.json",

    [switch]$DryRun,

    [string]$Only = ""
)

<#
.SYNOPSIS
    TeamCity 模板导入脚本（Windows 独立版）

.DESCRIPTION
    从 template.json 导入参数、步骤、特性、触发器、设置到目标模板/构建配置。
    依赖：curl.exe, python

.EXAMPLE
    .\import.ps1 -TcUrl http://tc.example.com:8111 -Username admin -Password pass -TargetId MyTemplate
    .\import.ps1 -TcUrl http://tc.example.com:8111 -Username admin -Password pass -TargetId MyTemplate -DryRun
    .\import.ps1 -TcUrl http://tc.example.com:8111 -Username admin -Password pass -TargetId MyTemplate -Only "parameters,steps"
#>

# UTF-8 设置
$Utf8NoBom = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = $Utf8NoBom
$OutputEncoding = $Utf8NoBom

# 验证
if (-not (Test-Path $JsonFile)) {
    Write-Error "$JsonFile not found"
    exit 1
}

$TcUrl = $TcUrl.TrimEnd("/")
$ApiBase = "$TcUrl/httpAuth/app/rest"
$AuthHeader = "Basic " + [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes("${Username}:${Password}"))

# ── 工具函数 ─────────────────────────────────────────────

function Invoke-TcPut {
    param([string]$Path, [string]$BodyFile)

    $fullUrl = "$ApiBase/$Path"
    $response = & curl.exe -s -w "`n%{http_code}" -X PUT `
        -H "Authorization: $AuthHeader" `
        -H "Content-Type: application/json; charset=utf-8" `
        -H "Accept: application/json" `
        --data-binary "@$BodyFile" `
        "$fullUrl" 2>&1

    $lines = $response -split "`n"
    $httpCode = $lines[-1]
    $body = ($lines[0..($lines.Length - 2)]) -join "`n"

    if ([int]$httpCode -ge 400) {
        Write-Host "FAILED (HTTP $httpCode)"
        Write-Host "  $($body.Substring(0, [Math]::Min(200, $body.Length)))"
        return $false
    }
    Write-Host "OK"
    return $true
}

# ── 主逻辑 ───────────────────────────────────────────────

# 确定导入组件
$allComps = @("parameters", "steps", "features", "triggers", "settings")
if ($Only -ne "") {
    $comps = $Only -split "," | ForEach-Object { $_.Trim() }
} else {
    $comps = $allComps
}

# 创建临时目录
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$tmpDir = Join-Path $env:TEMP "tc-import-$timestamp"
if (-not $tmpDir) {
    $tmpDir = Join-Path $PSScriptRoot "tc-import-tmp-$timestamp"
}
New-Item -ItemType Directory -Path $tmpDir -Force | Out-Null

$jsonFileAbs = (Resolve-Path $JsonFile).Path
$compsStr = $comps -join ","

# 写 Python 脚本到临时文件（避免 python -c 的引号转义问题）
$pyFile = Join-Path $tmpDir "_extract.py"
# 用 @'...'@ 单引号 here-string，不做任何变量展开
$pyCode = @'
import json, os, sys

json_file = sys.argv[1]
comps_str = sys.argv[2]
tmp_dir = sys.argv[3]

d = json.load(open(json_file, encoding="utf-8"))
comps = comps_str.split(",")

# 输出 meta 信息
m = d.get("meta", {})
print(f"Source: {m.get('name','?')} ({m.get('id','?')})")
print(f"Version: {m.get('version','?')} | Exported: {m.get('exportedAt','?')}")

for comp in comps:
    comp_data = d.get(comp, {})
    # 过滤 inherited 参数
    if comp == "parameters":
        props = comp_data.get("property", [])
        own = [p for p in props if not p.get("inherited")]
        if len(own) < len(props):
            print(f"NOTE: filtered {len(props)-len(own)} inherited params, keeping {len(own)} own")
        comp_data["property"] = own

    out_path = os.path.join(tmp_dir, f"{comp}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(comp_data, f, ensure_ascii=False)

    array_keys = {"parameters":"property","steps":"step","features":"feature","triggers":"trigger","settings":"property"}
    arr = comp_data.get(array_keys.get(comp,"property"), [])
    print(f"  {comp}: {len(arr)} items")
    if comp == "steps":
        for s in arr:
            print(f"    - [{s.get('id','')}] {s.get('name','')} ({s.get('type','')})")
    elif comp == "parameters":
        _sens = {"password","token","secret","key","credential","apikey","api_key"}
        for p in arr[:5]:
            pn = p.get("name","?")
            v = "***" if any(k in pn.lower() for k in _sens) else p.get("value","")
            if len(v)>50: v=v[:50]+"..."
            print(f"    - {pn} = {v}")
        if len(arr)>5: print(f"    ... and {len(arr)-5} more")
    elif comp == "settings":
        for p in arr:
            print(f"    - {p.get('name','?')} = {p.get('value','')}")
'@
[System.IO.File]::WriteAllText($pyFile, $pyCode, $Utf8NoBom)

# 执行 Python 提取和预览
python $pyFile $jsonFileAbs $compsStr $tmpDir

if ($LASTEXITCODE -ne 0) {
    Write-Error "Python extraction failed"
    if (Test-Path $tmpDir) { Remove-Item -Recurse -Force $tmpDir }
    exit 1
}

Write-Host ""
Write-Host "Target: $TargetId @ $TcUrl"

# VCS 提醒
$vcsFile = Join-Path $tmpDir "vcs-check.json"
if (-not (Test-Path $vcsFile)) {
    # 快速检查 JSON 中是否有 vcs-root-entries
    $hasVcs = python -c "import json,sys; d=json.load(open(sys.argv[1],encoding='utf-8')); v=d.get('vcs-root-entries',{}).get('vcs-root-entry',[]); print(len(v))" $jsonFileAbs 2>$null
    if ($hasVcs -and [int]$hasVcs -gt 0) {
        Write-Host ""
        Write-Host "NOTE: VCS root entries ($hasVcs) not imported (IDs may differ across environments)."
    }
}

Write-Host ""

if ($DryRun) {
    Write-Host "DRY RUN: no changes made."
    if (Test-Path $tmpDir) { Remove-Item -Recurse -Force $tmpDir }
    exit 0
}

# 确认
$answer = Read-Host "Proceed with import? This will REPLACE all items in each component. [y/N]"
if ($answer -ne "y" -and $answer -ne "Y") {
    Write-Host "Cancelled."
    if (Test-Path $tmpDir) { Remove-Item -Recurse -Force $tmpDir }
    exit 0
}

Write-Host ""
$errors = 0
foreach ($comp in $comps) {
    $compFile = Join-Path $tmpDir "$comp.json"
    if (-not (Test-Path $compFile)) {
        Write-Host "  ${comp}: skipped (no file)"
        continue
    }
    $content = Get-Content $compFile -Raw -Encoding UTF8
    if ([string]::IsNullOrWhiteSpace($content) -or $content.Trim() -eq "{}") {
        Write-Host "  ${comp}: skipped (empty)"
        continue
    }
    Write-Host -NoNewline "  ${comp}: "
    $ok = Invoke-TcPut -Path "buildTypes/id:$TargetId/$comp" -BodyFile $compFile
    if (-not $ok) { $errors++ }
}

if (Test-Path $tmpDir) { Remove-Item -Recurse -Force $tmpDir }
Write-Host ""
if ($errors -gt 0) {
    Write-Host "DONE with $errors errors."
    exit 1
} else {
    Write-Host "DONE: all components imported successfully."
}
