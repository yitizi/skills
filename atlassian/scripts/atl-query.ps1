param(
    [Parameter(Mandatory=$true)]
    [ValidateSet("jira", "confluence", "bitbucket")]
    [string]$Service,

    [Parameter(Mandatory=$true)]
    [string]$Path,

    [string]$Method = "GET",

    [string]$Body = "",

    [string]$BodyFile = "",

    [string]$ContentType = "application/json",

    # Standalone mode: bypass config/.netrc, use explicit URL+auth
    [string]$BaseUrl = "",
    [string]$Username = "",
    [string]$Password = ""
)

# Atlassian REST API helper (Jira + Confluence).
# Mirrors tc-query.ps1 patterns: config from ~/.claude/skill-config/atlassian/config.env,
# auth via curl --netrc, UTF-8 raw byte output via cmd /c type to preserve Chinese.
#
# Usage (skill mode, reads config + .netrc):
#   powershell -Command "& 'atl-query.ps1' -Service confluence -Path 'rest/api/content/12345?expand=body.storage,version'"
#   powershell -Command "& 'atl-query.ps1' -Service jira -Path 'rest/api/2/issue/PROJ-123'"
#   powershell -Command "& 'atl-query.ps1' -Service jira -Path 'rest/api/2/issue/PROJ-123/transitions' -Method POST -Body '{...}'"
#   powershell -Command "& 'atl-query.ps1' -Service confluence -Path 'rest/api/content/12345' -Method PUT -BodyFile 'C:\path\payload.json'"
#
# Standalone mode (skip skill infra):
#   powershell -Command "& 'atl-query.ps1' -Service jira -BaseUrl 'http://jira:8080' -Username u -Password p -Path 'rest/api/2/issue/PROJ-123'"

$StandaloneMode = ($Username -ne "" -and $Password -ne "")

if ($StandaloneMode) {
    if ($BaseUrl -eq "") {
        Write-Error "-BaseUrl is required when using -Username/-Password"
        exit 1
    }
    $ResolvedBase = $BaseUrl
} else {
    $ConfigDir = "$env:USERPROFILE\.claude\skill-config\atlassian"
    $EnvPath = Join-Path $ConfigDir "config.env"
    if (-not (Test-Path $EnvPath)) {
        Write-Error "$EnvPath not found. Run atl-credential.ps1 -Action setup first, or use -BaseUrl/-Username/-Password."
        exit 1
    }

    $JiraUrl = ""
    $ConfluenceUrl = ""
    $BitbucketUrl = ""
    $lines = Get-Content $EnvPath -ErrorAction SilentlyContinue
    foreach ($line in $lines) {
        if ($line -match '^JIRA_URL=(.+)$') { $JiraUrl = $Matches[1].Trim() }
        if ($line -match '^CONFLUENCE_URL=(.+)$') { $ConfluenceUrl = $Matches[1].Trim() }
        if ($line -match '^BITBUCKET_URL=(.+)$') { $BitbucketUrl = $Matches[1].Trim() }
    }

    switch ($Service) {
        "jira" {
            $ResolvedBase = $JiraUrl
            if ([string]::IsNullOrEmpty($ResolvedBase)) {
                Write-Error "JIRA_URL not configured. Run atl-credential.ps1 -Action setup."
                exit 1
            }
        }
        "confluence" {
            $ResolvedBase = $ConfluenceUrl
            if ([string]::IsNullOrEmpty($ResolvedBase)) {
                Write-Error "CONFLUENCE_URL not configured. Run atl-credential.ps1 -Action setup."
                exit 1
            }
        }
        "bitbucket" {
            $ResolvedBase = $BitbucketUrl
            if ([string]::IsNullOrEmpty($ResolvedBase)) {
                Write-Error "BITBUCKET_URL not configured. Run atl-credential.ps1 -Action setup. (Note: v1 atl-bitbucket.py CLI not yet shipped; use this -Service for low-level REST calls.)"
                exit 1
            }
        }
    }
}

# UTF-8 output encoding (no BOM)
$Utf8NoBom = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = $Utf8NoBom
$OutputEncoding = $Utf8NoBom

# Build URL: caller passes full path including 'rest/api/...'
$cleanPath = $Path -replace '^/+', ''
$fullUrl = $ResolvedBase.TrimEnd("/") + "/" + $cleanPath

# Build auth args
if ($StandaloneMode) {
    $AuthHeader = "Basic " + [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes("${Username}:${Password}"))
    $authArgs = @("-H", "Authorization: $AuthHeader")
} else {
    $authArgs = @("--netrc")
}

# Resolve body source: caller may pass -Body string, -BodyFile path, or neither (GET/DELETE).
# To avoid PowerShell pipe encoding mangling non-ASCII content (PS 5.1 pipe to native exe
# uses ANSI not UTF-8), always materialize -Body to a UTF-8 temp file before invoking curl.
$bodyFileToUse = ""
$bodyTmpToCleanup = ""
if ($BodyFile) {
    if (-not (Test-Path -LiteralPath $BodyFile)) {
        Write-Error "BodyFile not found: $BodyFile"
        exit 1
    }
    $bodyFileToUse = $BodyFile
} elseif ($Body) {
    $bodyTmpToCleanup = [System.IO.Path]::GetTempFileName()
    [System.IO.File]::WriteAllText($bodyTmpToCleanup, $Body, $Utf8NoBom)
    $bodyFileToUse = $bodyTmpToCleanup
}

# Execute curl with HTTP status check via -o tmp + -w '%{http_code}'.
# Use --data-binary @<file> for any body (no stdin), so UTF-8 bytes go through unchanged.
$tmpFile = [System.IO.Path]::GetTempFileName()
try {
    if ($Method -eq "GET" -or ($Method -eq "DELETE" -and -not $bodyFileToUse)) {
        $httpCode = & curl.exe -s @authArgs -X $Method "$fullUrl" `
            -H "Accept: application/json" `
            -o $tmpFile -w "%{http_code}"
    } else {
        if (-not $bodyFileToUse) {
            # POST/PUT without body - emit empty payload via empty file
            $bodyTmpToCleanup = [System.IO.Path]::GetTempFileName()
            [System.IO.File]::WriteAllText($bodyTmpToCleanup, "", $Utf8NoBom)
            $bodyFileToUse = $bodyTmpToCleanup
        }
        $httpCode = & curl.exe -s @authArgs -X $Method "$fullUrl" `
            -H "Content-Type: $ContentType" -H "Accept: application/json" `
            --data-binary "@$bodyFileToUse" `
            -o $tmpFile -w "%{http_code}"
    }

    if ($LASTEXITCODE -ne 0) {
        Write-Error "curl.exe failed (exit code $LASTEXITCODE)"
        exit 1
    }

    if ($httpCode -match '^[45]') {
        $errBody = ""
        if (Test-Path $tmpFile) {
            $errBody = [System.IO.File]::ReadAllText($tmpFile, $Utf8NoBom)
        }
        # Emit "HTTP <code>" prefix so callers can grep stderr for specific codes (e.g. 409 conflict)
        Write-Error "HTTP $httpCode"
        if ($errBody) { Write-Output $errBody }
        exit 1
    }

    # Success: stream raw bytes through cmd /c type to preserve UTF-8 in pipe
    if ((Get-Item $tmpFile).Length -gt 0) {
        & cmd.exe /c type $tmpFile
    }
} finally {
    if (Test-Path $tmpFile) { Remove-Item $tmpFile -ErrorAction SilentlyContinue }
    if ($bodyTmpToCleanup -and (Test-Path $bodyTmpToCleanup)) {
        Remove-Item $bodyTmpToCleanup -ErrorAction SilentlyContinue
    }
}
