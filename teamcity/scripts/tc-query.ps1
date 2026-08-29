param(
    [Parameter(Mandatory = $true)]
    [string]$Path,

    [ValidateSet("GET", "POST", "PUT", "DELETE", "PATCH")]
    [string]$Method = "GET",

    [string]$Body = "",

    [string]$BodyFile = "",

    [string]$OutFile = "",

    [string]$ContentType = "application/json; charset=utf-8",

    [string]$Accept = "application/json",

    [switch]$RawPath,

    [string]$ApiRoot = "",

    # Skill-scoped proxy only. For the hb VPN SOCKS endpoint, use for example:
    # socks5h://127.0.0.1:1080
    [string]$Proxy = "",

    [string]$NoProxy = "",

    [ValidateRange(1, 600)]
    [int]$ConnectTimeoutSec = 15,

    [ValidateRange(1, 3600)]
    [int]$MaxTimeSec = 300,

    # Standalone mode. Prefer the credential helper in normal skill use so the
    # password does not appear in terminal history or process arguments.
    [string]$TcUrl = "",

    [string]$Username = "",

    [string]$Password = ""
)

# TeamCity HTTP helper for Windows PowerShell 5.1 and PowerShell 7+.
# Request bodies and response files cross the native-process boundary as raw
# UTF-8 bytes. This avoids the Windows PowerShell 5.1 pipeline code-page trap.

$Utf8NoBom = [System.Text.UTF8Encoding]::new($false)
[Console]::InputEncoding = $Utf8NoBom
[Console]::OutputEncoding = $Utf8NoBom
$OutputEncoding = $Utf8NoBom

if (($Username -and -not $Password) -or ($Password -and -not $Username)) {
    Write-Error "-Username and -Password must be supplied together."
    exit 1
}
if ($Body -and $BodyFile) {
    Write-Error "Use either -Body or -BodyFile, not both."
    exit 1
}
if (-not (Get-Command curl.exe -ErrorAction SilentlyContinue)) {
    Write-Error "curl.exe was not found. Windows 10/11 includes it by default."
    exit 1
}

$StandaloneMode = [bool]($Username -and $Password)
$ConfiguredApiRoot = ""
$ConfiguredProxy = ""
$ConfiguredNoProxy = ""

if ($StandaloneMode) {
    if (-not $TcUrl) {
        Write-Error "-TcUrl is required when using -Username/-Password."
        exit 1
    }
    $ResolvedTcUrl = $TcUrl
} else {
    $ConfigDir = Join-Path $env:USERPROFILE ".claude\skill-config\teamcity"
    $EnvPath = Join-Path $ConfigDir "config.env"
    if (-not (Test-Path -LiteralPath $EnvPath)) {
        Write-Error "$EnvPath not found. Run tc-credential.ps1 -Action setup first."
        exit 1
    }

    $ResolvedTcUrl = ""
    $lines = Get-Content -LiteralPath $EnvPath -Encoding UTF8 -ErrorAction SilentlyContinue
    foreach ($line in $lines) {
        if ($line -match '^TC_URL=(.+)$') { $ResolvedTcUrl = $Matches[1].Trim() }
        if ($line -match '^TC_API_ROOT=(.+)$') { $ConfiguredApiRoot = $Matches[1].Trim() }
        if ($line -match '^TC_PROXY=(.+)$') { $ConfiguredProxy = $Matches[1].Trim() }
        if ($line -match '^TC_NO_PROXY=(.+)$') { $ConfiguredNoProxy = $Matches[1].Trim() }
    }
    if (-not $ResolvedTcUrl) {
        Write-Error "TC_URL not found in config.env."
        exit 1
    }
}

if (-not $Proxy) { $Proxy = $ConfiguredProxy }
if (-not $NoProxy) { $NoProxy = $ConfiguredNoProxy }
$proxyArgs = @()
if ($Proxy) { $proxyArgs += @('--proxy', $Proxy) }
if ($NoProxy) { $proxyArgs += @('--noproxy', $NoProxy) }

$cleanPath = $Path -replace '^/+', ''
if ($RawPath) {
    $fullUrl = $ResolvedTcUrl.TrimEnd('/') + '/' + $cleanPath
} else {
    $ResolvedApiRoot = if ($ApiRoot) {
        $ApiRoot
    } elseif ($ConfiguredApiRoot) {
        $ConfiguredApiRoot
    } else {
        'httpAuth/app/rest'
    }
    $fullUrl = $ResolvedTcUrl.TrimEnd('/') + '/' + $ResolvedApiRoot.Trim('/') + '/' + $cleanPath
}

if ($StandaloneMode) {
    $AuthHeader = 'Basic ' + [Convert]::ToBase64String(
        [Text.Encoding]::UTF8.GetBytes("${Username}:${Password}")
    )
    $authArgs = @('-H', "Authorization: $AuthHeader")
} else {
    $authArgs = @('--netrc')
}

$bodyFileToUse = ""
$bodyTempFile = ""
if ($BodyFile) {
    if (-not (Test-Path -LiteralPath $BodyFile -PathType Leaf)) {
        Write-Error "BodyFile not found: $BodyFile"
        exit 1
    }
    $bodyFileToUse = (Resolve-Path -LiteralPath $BodyFile).Path
} elseif ($Body) {
    $bodyTempFile = [System.IO.Path]::GetTempFileName()
    [System.IO.File]::WriteAllText($bodyTempFile, $Body, $Utf8NoBom)
    $bodyFileToUse = $bodyTempFile
}

$responseTempFile = [System.IO.Path]::GetTempFileName()
try {
    $curlArgs = @(
        '-sS',
        '--connect-timeout', "$ConnectTimeoutSec",
        '--max-time', "$MaxTimeSec"
    ) + $authArgs + $proxyArgs + @(
        '-X', $Method,
        $fullUrl,
        '-H', "Accept: $Accept"
    )

    if ($bodyFileToUse) {
        $curlArgs += @(
            '-H', "Content-Type: $ContentType",
            '--data-binary', "@$bodyFileToUse"
        )
    } elseif ($Method -in @('POST', 'PUT', 'PATCH')) {
        $bodyTempFile = [System.IO.Path]::GetTempFileName()
        [System.IO.File]::WriteAllText($bodyTempFile, '', $Utf8NoBom)
        $curlArgs += @(
            '-H', "Content-Type: $ContentType",
            '--data-binary', "@$bodyTempFile"
        )
    }

    $curlArgs += @('-o', $responseTempFile, '-w', '%{http_code}')
    $httpCode = (& curl.exe @curlArgs)
    $curlExitCode = $LASTEXITCODE

    if ($curlExitCode -ne 0) {
        Write-Error "curl.exe failed (exit code $curlExitCode)."
        exit 1
    }

    $httpCode = ("$httpCode").Trim()
    if ($httpCode -notmatch '^\d{3}$') {
        Write-Error "curl.exe returned an invalid HTTP status: $httpCode"
        exit 1
    }
    if ([int]$httpCode -ge 400) {
        $errorBody = [System.IO.File]::ReadAllText($responseTempFile, $Utf8NoBom)
        Write-Error "HTTP $httpCode"
        if ($errorBody) { Write-Output $errorBody }
        exit 1
    }

    if ($OutFile) {
        $resolvedOutFile = [System.IO.Path]::GetFullPath($OutFile)
        $parentDir = [System.IO.Path]::GetDirectoryName($resolvedOutFile)
        if ($parentDir -and -not (Test-Path -LiteralPath $parentDir -PathType Container)) {
            Write-Error "OutFile parent directory not found: $parentDir"
            exit 1
        }
        [System.IO.File]::Copy($responseTempFile, $resolvedOutFile, $true)
    } elseif ((Get-Item -LiteralPath $responseTempFile).Length -gt 0) {
        # cmd.exe/type forwards the response file's bytes without decoding and
        # re-encoding them in Windows PowerShell 5.1.
        & cmd.exe /d /c type "$responseTempFile"
    }
} finally {
    if (Test-Path -LiteralPath $responseTempFile) {
        Remove-Item -LiteralPath $responseTempFile -ErrorAction SilentlyContinue
    }
    if ($bodyTempFile -and (Test-Path -LiteralPath $bodyTempFile)) {
        Remove-Item -LiteralPath $bodyTempFile -ErrorAction SilentlyContinue
    }
}
