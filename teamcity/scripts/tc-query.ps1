param(
    [Parameter(Mandatory=$true)]
    [string]$Path,

    [string]$Method = "GET",

    [string]$Body = "",

    [string]$ContentType = "application/json",

    [switch]$RawPath,

    # 独立模式：指定以下三个参数后直接用 Basic auth，不依赖 .netrc 和 config.env
    [string]$TcUrl = "",

    [string]$Username = "",

    [string]$Password = ""
)

# TeamCity API query helper
# Handles: config loading, UTF-8 encoding, curl.exe, .netrc auth
# IMPORTANT: use -Command mode (not -File) to avoid PowerShell 5.1 /path parsing issues
# Usage:
#   powershell -ExecutionPolicy Bypass -Command "& 'tc-query.ps1' -Path 'buildTypes/id:XXX?fields=id,name'"
#   powershell -ExecutionPolicy Bypass -Command "& 'tc-query.ps1' -Path 'buildQueue' -Method POST -Body '{...}'"
#   powershell -ExecutionPolicy Bypass -Command "& 'tc-query.ps1' -Path 'httpAuth/downloadBuildLog.html?buildId=123' -RawPath"
#
# 独立模式（不依赖 skill 基础设施）：
#   powershell -ExecutionPolicy Bypass -Command "& 'tc-query.ps1' -TcUrl 'http://tc:8111' -Username admin -Password pass -Path 'buildTypes/id:XXX?fields=id,name'"

# 判断认证模式
$StandaloneMode = ($Username -ne "" -and $Password -ne "")

if ($StandaloneMode) {
    if ($TcUrl -eq "") {
        Write-Error "-TcUrl is required when using -Username/-Password"
        exit 1
    }
    $TC_URL = $TcUrl
} else {
    $ConfigDir = "$env:USERPROFILE\.claude\skill-config\teamcity"
    $EnvPath = Join-Path $ConfigDir "config.env"

    # Load config
    if (-not (Test-Path $EnvPath)) {
        Write-Error "$EnvPath not found. Run tc-credential.ps1 -Action setup first, or use -TcUrl/-Username/-Password."
        exit 1
    }

    $TC_URL = ""
    $lines = Get-Content $EnvPath -ErrorAction SilentlyContinue
    foreach ($line in $lines) {
        if ($line -match '^TC_URL=(.+)$') { $TC_URL = $Matches[1].Trim() }
    }

    if ([string]::IsNullOrEmpty($TC_URL)) {
        Write-Error "TC_URL not found in config.env"
        exit 1
    }
}

# Set UTF-8 output encoding (without BOM)
# $OutputEncoding controls pipe encoding to native executables (default ASCII in PS 5.1)
# [Console]::OutputEncoding controls stdout encoding
$Utf8NoBom = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = $Utf8NoBom
$OutputEncoding = $Utf8NoBom

# Build full URL - strip leading/trailing slashes to avoid double-slash
$cleanPath = $Path -replace '^/+', ''
if ($RawPath) {
    $fullUrl = $TC_URL.TrimEnd("/") + "/" + $cleanPath
} else {
    $fullUrl = $TC_URL.TrimEnd("/") + "/httpAuth/app/rest/" + $cleanPath
}

# Build auth arguments
if ($StandaloneMode) {
    $AuthHeader = "Basic " + [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes("${Username}:${Password}"))
    $authArgs = @("-H", "Authorization: $AuthHeader")
} else {
    $authArgs = @("--netrc")
}

# Execute curl.exe with exit code and HTTP status check
# 策略：先用 -o 获取 HTTP 状态码检查是否成功，成功后让 curl 再次直接输出到 stdout
# 这样保持 curl 原始 UTF-8 字节直通管道，避免 PowerShell 编码转换破坏中文
$tmpFile = [System.IO.Path]::GetTempFileName()
try {
    if ($Method -eq "GET") {
        $httpCode = & curl.exe -s @authArgs "$fullUrl" -H "Accept: application/json" -o $tmpFile -w "%{http_code}"
    } else {
        $httpCode = ($Body | & curl.exe -s @authArgs -X $Method "$fullUrl" -H "Content-Type: $ContentType" -H "Accept: application/json" -d "@-" -o $tmpFile -w "%{http_code}")
    }

    if ($LASTEXITCODE -ne 0) {
        Write-Error "curl.exe failed (exit code $LASTEXITCODE)"
        exit 1
    }

    if ($httpCode -match '^[45]') {
        $errBody = [System.IO.File]::ReadAllText($tmpFile, $Utf8NoBom)
        Write-Error "HTTP $httpCode"
        Write-Output $errBody
        exit 1
    }

    # 成功：用 cmd /c type 输出文件原始字节到 stdout
    # 不能用 Write-Output（PowerShell 编码层会破坏中文管道传递）
    # 不能用 [Console]::OpenStandardOutput()（bash pipe 收不到）
    & cmd.exe /c type $tmpFile
} finally {
    if (Test-Path $tmpFile) { Remove-Item $tmpFile -ErrorAction SilentlyContinue }
}
