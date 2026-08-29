param(
    [switch]$Online
)

# Local diagnostics for Windows PowerShell 5.1 and PowerShell 7+.
# This script never prints or parses credential values from .netrc.

$Utf8NoBom = [System.Text.UTF8Encoding]::new($false)
$Utf8Strict = [System.Text.UTF8Encoding]::new($false, $true)
[Console]::InputEncoding = $Utf8NoBom
[Console]::OutputEncoding = $Utf8NoBom
$OutputEncoding = $Utf8NoBom

$script:Failures = 0
$script:Warnings = 0

function Write-Check([string]$Level, [string]$Message) {
    if ($Level -eq 'FAIL') { $script:Failures++ }
    if ($Level -eq 'WARN') { $script:Warnings++ }
    Write-Output "${Level}|$Message"
}

Write-Check 'OK' "PowerShell $($PSVersionTable.PSVersion) ($($PSVersionTable.PSEdition))"
if ($PSVersionTable.PSVersion.Major -lt 5) {
    Write-Check 'FAIL' 'PowerShell 5.1 or later is required.'
}

$curl = Get-Command curl.exe -ErrorAction SilentlyContinue
if ($curl) {
    $curlVersion = (& curl.exe --version | Select-Object -First 1)
    Write-Check 'OK' $curlVersion
} else {
    Write-Check 'FAIL' 'curl.exe was not found.'
}

$python = Get-Command python -ErrorAction SilentlyContinue
if ($python) {
    $pythonVersion = (& python --version 2>&1)
    Write-Check 'OK' $pythonVersion
} else {
    Write-Check 'FAIL' 'python was not found.'
}

foreach ($name in @('tc-query.ps1', 'tc-credential.ps1', 'tc-doctor.ps1', 'deliverable\import.ps1')) {
    $path = Join-Path $PSScriptRoot $name
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        Write-Check 'FAIL' "Missing script: $name"
        continue
    }
    $bytes = [IO.File]::ReadAllBytes($path)
    $hasUtf8Bom = $bytes.Length -ge 3 -and
        $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF
    try {
        $offset = if ($hasUtf8Bom) { 3 } else { 0 }
        $null = $Utf8Strict.GetString($bytes, $offset, $bytes.Length - $offset)
        if ($hasUtf8Bom) {
            Write-Check 'OK' "$name is UTF-8 with BOM (Windows PowerShell 5.1 safe)."
        } elseif ($PSVersionTable.PSVersion.Major -le 5) {
            Write-Check 'FAIL' "$name is UTF-8 without BOM; Windows PowerShell 5.1 may decode it as ANSI."
        } else {
            Write-Check 'WARN' "$name is UTF-8 without BOM; add BOM for Windows PowerShell 5.1."
        }
    } catch {
        Write-Check 'FAIL' "$name is not valid UTF-8."
    }
}

$roundTripFile = Join-Path ([IO.Path]::GetTempPath()) ("tc-utf8-" + [guid]::NewGuid().ToString('N') + '.json')
try {
    $sample = '{"message":"中文构建-河南-🚀"}'
    [IO.File]::WriteAllText($roundTripFile, $sample, $Utf8NoBom)
    if ($python) {
        & python -c "import json,sys; assert json.load(open(sys.argv[1], encoding='utf-8'))['message'] == '中文构建-河南-🚀'" $roundTripFile
        if ($LASTEXITCODE -eq 0) {
            Write-Check 'OK' 'PowerShell-to-Python UTF-8 file round-trip passed.'
        } else {
            Write-Check 'FAIL' 'PowerShell-to-Python UTF-8 file round-trip failed.'
        }
    }
} finally {
    Remove-Item -LiteralPath $roundTripFile -ErrorAction SilentlyContinue
}

$configDir = Join-Path $env:USERPROFILE '.claude\skill-config\teamcity'
$configPath = Join-Path $configDir 'config.env'
$netrcPath = Join-Path $env:USERPROFILE '.netrc'
if (Test-Path -LiteralPath $configPath -PathType Leaf) {
    try {
        $configText = $Utf8Strict.GetString([IO.File]::ReadAllBytes($configPath))
        if ($configText -match '(?m)^TC_URL=(.+)$') {
            Write-Check 'OK' "config.env is valid UTF-8; TC_URL is configured."
        } else {
            Write-Check 'FAIL' 'config.env does not contain TC_URL.'
        }
    } catch {
        Write-Check 'FAIL' 'config.env is not valid UTF-8.'
    }
} else {
    Write-Check 'WARN' 'config.env is not configured; run tc-credential.ps1 -Action setup.'
}

if (Test-Path -LiteralPath $netrcPath -PathType Leaf) {
    Write-Check 'OK' '.netrc exists (contents were not read).'
} else {
    Write-Check 'WARN' '.netrc does not exist; run credential setup before online use.'
}

if ($Online) {
    $query = Join-Path $PSScriptRoot 'tc-query.ps1'
    $serverFile = Join-Path ([IO.Path]::GetTempPath()) ("tc-server-" + [guid]::NewGuid().ToString('N') + '.json')
    try {
        $childPowerShell = if ($PSVersionTable.PSEdition -eq 'Desktop') {
            Join-Path $PSHOME 'powershell.exe'
        } else {
            Join-Path $PSHOME 'pwsh.exe'
        }
        & $childPowerShell -NoProfile -ExecutionPolicy Bypass -File $query `
            -Path 'server' -OutFile $serverFile
        $onlineExitCode = $LASTEXITCODE
        if ($onlineExitCode -ne 0) {
            Write-Check 'FAIL' 'Online TeamCity server query failed.'
        } else {
            try {
                $serverJson = [IO.File]::ReadAllText($serverFile, $Utf8NoBom) | ConvertFrom-Json
                Write-Check 'OK' "Online query passed; TeamCity version $($serverJson.version)."
            } catch {
                Write-Check 'FAIL' 'Online response was not valid UTF-8 JSON.'
            }
        }
    } finally {
        Remove-Item -LiteralPath $serverFile -ErrorAction SilentlyContinue
    }
}

Write-Output "SUMMARY|failures=$script:Failures|warnings=$script:Warnings"
if ($script:Failures -gt 0) { exit 1 }
