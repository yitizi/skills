param(
    [string]$JdkHome,
    [string]$DumpPath,
    [string[]]$QueryFile = @(),
    [string]$QueryDir = "",
    [int]$Port = 7401,
    [string]$Xmx = "4g",
    [string]$OutputDir = "",
    [ValidateSet("html", "rows", "json")]
    [string]$Format = "rows",
    [int]$StartupTimeoutSec = 120,
    [int]$QueryTimeoutSec = 300,
    [switch]$ContinueOnError,
    [string]$PidFile = "",
    [switch]$Help
)

$ErrorActionPreference = "Stop"

function Show-Help {
    # Use individual Write-Host calls to avoid here-string swallowing backticks.
    # Also avoids PowerShell 5.1 CRLF requirement for @'...'@ single-quoted here-strings.
    # $bt holds one literal backtick character (used for multi-line command continuation examples).
    $bt = [string][char]0x60
    Write-Host 'Usage: powershell -ExecutionPolicy Bypass -File run_jhat_session.ps1 [params]'
    Write-Host ''
    Write-Host 'Required:'
    Write-Host '  -JdkHome     <path>      JDK 8 root directory (NOT jhat.exe path)'
    Write-Host '                           Must contain bin\java.exe and lib\tools.jar'
    Write-Host '  -DumpPath    <path>      Path to .hprof / .dump file'
    Write-Host ''
    Write-Host 'Query input (use ONE of these):'
    Write-Host '  -QueryFile   <paths>     One or more .oql files. Supported forms:'
    Write-Host '                             a) Comma-separated string (works with powershell -File):'
    Write-Host '                                -QueryFile a.oql,b.oql,c.oql'
    Write-Host '                             b) Quoted single string with commas:'
    Write-Host "                                -QueryFile 'a.oql,b.oql,c.oql'"
    Write-Host '                             c) Repeated -QueryFile (in-session call only, NOT via -File):'
    Write-Host '                                & .\run_jhat_session.ps1 -QueryFile a.oql,b.oql,c.oql'
    Write-Host '  -QueryDir    <path>      Directory containing .oql files. All *.oql loaded.'
    Write-Host '                           More reliable than -QueryFile when invoked via powershell -File.'
    Write-Host ''
    Write-Host 'Optional:'
    Write-Host '  -Port               <int>     jhat HTTP port (default: 7401)'
    Write-Host '  -Xmx                <size>    JVM heap for jhat (default: 4g)'
    Write-Host '                                Suggested by dump size:'
    Write-Host '                                  <200MB: 2g'
    Write-Host '                                  200-500MB: 4g'
    Write-Host '                                  500MB-1GB: 8g'
    Write-Host '                                  >1GB: 12g+ (or switch to MAT)'
    Write-Host '  -OutputDir          <path>    Output directory for query results'
    Write-Host '                                Files saved as <queryname>.{txt|json|html}'
    Write-Host '  -Format             <fmt>     html | rows | json (default: rows)'
    Write-Host '  -StartupTimeoutSec  <int>     Wait jhat startup (default: 120s)'
    Write-Host '  -QueryTimeoutSec    <int>     Per-query timeout (default: 300s)'
    Write-Host '  -ContinueOnError              Continue running remaining queries when one fails'
    Write-Host '                                Without this flag, script exits on first error'
    Write-Host '  -PidFile            <path>    Write jhat PID to file (for external cleanup)'
    Write-Host ''
    Write-Host 'Example A (use -QueryDir, RECOMMENDED for powershell -File):'
    Write-Host '  powershell -ExecutionPolicy Bypass -File run_jhat_session.ps1 -JdkHome C:\Java\jdk8 -DumpPath D:\dump\heap.hprof -QueryDir .\queries -Xmx 8g -OutputDir .\out -ContinueOnError'
    Write-Host ''
    Write-Host 'Example B (-QueryFile with comma-separated paths):'
    Write-Host '  powershell -ExecutionPolicy Bypass -File run_jhat_session.ps1 -JdkHome C:\Java\jdk8 -DumpPath D:\dump\heap.hprof -QueryFile .\queries\count.oql,.\queries\wcm.oql -Xmx 8g -OutputDir .\out -ContinueOnError'
    Write-Host ''
    Write-Host 'Example C (multi-line with backtick continuation):'
    Write-Host ('  powershell -ExecutionPolicy Bypass -File run_jhat_session.ps1 ' + $bt)
    Write-Host ('    -JdkHome ''C:\Java\jdk8'' ' + $bt)
    Write-Host ('    -DumpPath ''D:\dump\heap.hprof'' ' + $bt)
    Write-Host ('    -QueryDir ''.\queries'' ' + $bt)
    Write-Host ('    -Xmx 8g ' + $bt)
    Write-Host ('    -OutputDir ''.\out'' ' + $bt)
    Write-Host '    -ContinueOnError'
    Write-Host ''
    Write-Host 'Notes:'
    Write-Host '  - Slow queries (heap.livepaths, full referrers) can take 10+ minutes on >1GB dumps'
    Write-Host '  - Recommend running lightweight count/state queries first, then expensive ones separately'
    Write-Host '  - On any failure: jhat process killed in finally block + PID file removed'
}

if ($Help) { Show-Help; exit 0 }

function Get-FullPathOrInput {
    param([string]$Path)
    try {
        return $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($Path)
    } catch {
        try { return [System.IO.Path]::GetFullPath($Path) } catch { return $Path }
    }
}

function Get-NearestExistingParent {
    param([string]$Path)
    $candidate = Get-FullPathOrInput -Path $Path
    while ($candidate -and -not (Test-Path -LiteralPath $candidate)) {
        $parent = [System.IO.Directory]::GetParent($candidate)
        if ($null -eq $parent) { return "" }
        $candidate = $parent.FullName
    }
    if ($candidate -and (Test-Path -LiteralPath $candidate)) {
        return (Resolve-Path -LiteralPath $candidate).Path
    }
    return ""
}

function Test-DirectoryWritable {
    param([string]$Directory)
    $probe = Join-Path $Directory ("._jvmdump_write_test_" + [Guid]::NewGuid().ToString("N") + ".tmp")
    try {
        [System.IO.File]::WriteAllText($probe, "test", [System.Text.Encoding]::ASCII)
        Remove-Item -LiteralPath $probe -Force -ErrorAction SilentlyContinue
        return "PASS"
    } catch {
        Remove-Item -LiteralPath $probe -Force -ErrorAction SilentlyContinue
        return "FAIL: $($_.Exception.Message)"
    }
}

function Get-AclSummary {
    param([string]$Path)
    try {
        $acl = Get-Acl -LiteralPath $Path
        $lines = @()
        foreach ($entry in ($acl.Access | Select-Object -First 20)) {
            $lines += ("  {0}: {1}; {2}; inherited={3}" -f $entry.IdentityReference, $entry.FileSystemRights, $entry.AccessControlType, $entry.IsInherited)
        }
        if ($lines.Count -eq 0) { return "  <no ACL entries returned>" }
        return ($lines -join [Environment]::NewLine)
    } catch {
        return "  <failed to read ACL: $($_.Exception.Message)>"
    }
}

function New-OutputDirectory {
    param([string]$Path)
    $fullPath = Get-FullPathOrInput -Path $Path
    try {
        New-Item -ItemType Directory -Path $fullPath -Force | Out-Null
        $resolved = (Resolve-Path -LiteralPath $fullPath).Path
        $writeTest = Test-DirectoryWritable -Directory $resolved
        if (-not $writeTest.StartsWith("PASS")) {
            throw "Created output directory, but write test failed: $writeTest"
        }
        return $resolved
    } catch {
        $nearest = Get-NearestExistingParent -Path $fullPath
        $identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
        $parentWrite = if ($nearest) { Test-DirectoryWritable -Directory $nearest } else { "SKIPPED: no existing parent found" }
        $aclSummary = if ($nearest) { Get-AclSummary -Path $nearest } else { "  <no existing parent found>" }
        $message = @(
            "Failed to create or write OutputDir.",
            "OutputDir: $fullPath",
            "Current user: $identity",
            "Nearest existing parent: $nearest",
            "Parent write test: $parentWrite",
            "Original error: $($_.Exception.Message)",
            "ACL summary for nearest existing parent:",
            $aclSummary,
            "This is a filesystem permission or sandbox ACL issue, not a jhat/OQL failure.",
            "Use an OutputDir under a writable parent or fix ACLs before retrying."
        ) -join [Environment]::NewLine
        throw $message
    }
}

function Stop-JhatProcess {
    param($Process, [int]$ProcessId)

    if ($null -ne $Process -and -not $Process.HasExited) {
        try {
            Stop-Process -Id $Process.Id -Force -ErrorAction Stop
            Write-Host "Killed jhat process PID=$($Process.Id)"
        } catch {
            Write-Warning "Failed to kill jhat process PID=$($Process.Id): $($_.Exception.Message)"
        }
    }

    # Second-pass cleanup by PID in case the process object is stale.
    if ($ProcessId -gt 0) {
        try {
            $stillAlive = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
            if ($stillAlive) {
                Stop-Process -Id $ProcessId -Force -ErrorAction Stop
                Write-Host "Force-killed residual process PID=$ProcessId"
            }
        } catch {
            Write-Warning "Failed to force-kill PID=${ProcessId}: $($_.Exception.Message)"
        }
    }
}

# ===== Parameter validation =====
if (-not $JdkHome) { throw "Missing -JdkHome (use -Help for usage)" }
if (-not $DumpPath) { throw "Missing -DumpPath" }
if (-not (Test-Path -LiteralPath $DumpPath)) { throw "Dump not found: $DumpPath" }

# Resolve query files from -QueryFile and/or -QueryDir.
# powershell -File CLI does NOT honor PS array literals, so a "-QueryFile a,b,c" call
# arrives as a single-element array containing the literal string "a,b,c".
# Detect and split that case so users get array semantics regardless of invocation mode.
$resolvedQueries = New-Object System.Collections.Generic.List[string]

if ($QueryFile -and $QueryFile.Count -gt 0) {
    foreach ($entry in $QueryFile) {
        if ($null -eq $entry) { continue }
        $trimmed = $entry.Trim()
        if (-not $trimmed) { continue }
        # Split on comma if present (handles powershell -File comma-joining).
        # If user passed a path that legitimately contains commas, they should use -QueryDir.
        if ($trimmed.Contains(",")) {
            foreach ($part in $trimmed.Split(",")) {
                $p = $part.Trim()
                if ($p) { $resolvedQueries.Add($p) }
            }
        } else {
            $resolvedQueries.Add($trimmed)
        }
    }
}

if ($QueryDir) {
    if (-not (Test-Path -LiteralPath $QueryDir)) {
        throw "QueryDir not found: $QueryDir"
    }
    $oqlFiles = Get-ChildItem -LiteralPath $QueryDir -Filter "*.oql" -File | Sort-Object Name
    if ($oqlFiles.Count -eq 0) {
        throw "No *.oql files found in QueryDir: $QueryDir"
    }
    foreach ($f in $oqlFiles) {
        $resolvedQueries.Add($f.FullName)
    }
}

if ($resolvedQueries.Count -eq 0) {
    throw "Missing query input. Provide -QueryFile <paths> or -QueryDir <directory>. Use -Help for examples."
}

# Replace original $QueryFile with the resolved array for downstream code
$QueryFile = $resolvedQueries.ToArray()
Write-Host "Resolved $($QueryFile.Count) query file(s):"
foreach ($q in $QueryFile) { Write-Host "  - $q" }
Write-Host ""

$java = Join-Path $JdkHome "bin\java.exe"
$tools = Join-Path $JdkHome "lib\tools.jar"
if (-not (Test-Path -LiteralPath $java)) { throw "java.exe not found: $java (is -JdkHome a JDK 8 root?)" }
if (-not (Test-Path -LiteralPath $tools)) { throw "tools.jar not found: $tools (JDK 9+ removed tools.jar; jhat requires JDK 8)" }

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$runOql = Join-Path $scriptDir "run_oql.py"
if (-not (Test-Path -LiteralPath $runOql)) { throw "run_oql.py not found: $runOql" }

if ($OutputDir) {
    $OutputDir = New-OutputDirectory -Path $OutputDir
}

# ===== Start jhat =====
$baseUrl = "http://127.0.0.1:$Port"
$arguments = @(
    "-Xmx$Xmx",
    "-cp", "`"$tools`"",
    "com.sun.tools.hat.Main",
    "-port", "$Port",
    "`"$DumpPath`""
)

$proc = $null
$jhatPid = 0
$succeeded = New-Object System.Collections.Generic.List[string]
$failed = New-Object System.Collections.Generic.List[hashtable]

try {
    $proc = Start-Process -FilePath $java -ArgumentList $arguments -PassThru -WindowStyle Hidden
    $jhatPid = $proc.Id
    Write-Host "Started jhat: PID=$jhatPid Port=$Port Xmx=$Xmx Dump=$DumpPath"

    # Write PID file for external cleanup.
    if ($PidFile) {
        $pidFullPath = Get-FullPathOrInput -Path $PidFile
        Set-Content -LiteralPath $pidFullPath -Value $jhatPid -Encoding ASCII
        Write-Host "PID file: $pidFullPath"
    }

    # Wait for jhat to listen.
    $deadline = (Get-Date).AddSeconds($StartupTimeoutSec)
    $ready = $false
    while ((Get-Date) -lt $deadline) {
        if ($proc.HasExited) {
            throw "jhat exited before listening on $baseUrl (exit code: $($proc.ExitCode))"
        }
        try {
            Invoke-WebRequest -UseBasicParsing -Uri "$baseUrl/" -TimeoutSec 2 | Out-Null
            $ready = $true
            break
        } catch {
            Start-Sleep -Seconds 1
        }
    }
    if (-not $ready) {
        throw "Timed out waiting for jhat on $baseUrl after ${StartupTimeoutSec}s"
    }
    Write-Host "jhat ready on $baseUrl"
    Write-Host ""

    # ===== Run queries serially =====
    foreach ($query in $QueryFile) {
        if (-not (Test-Path -LiteralPath $query)) {
            $msg = "Query file not found: $query"
            if ($ContinueOnError) {
                Write-Warning $msg
                $failed.Add(@{Query=$query; Error=$msg})
                continue
            } else {
                throw $msg
            }
        }

        $queryName = [System.IO.Path]::GetFileNameWithoutExtension($query)
        Write-Host "=== Running: $queryName ==="

        $cmd = @($runOql, "--base-url", $baseUrl, "--query-file", $query, "--format", $Format, "--timeout", "$QueryTimeoutSec")
        $outFile = $null
        if ($OutputDir) {
            $ext = if ($Format -eq "html") { ".html" } elseif ($Format -eq "json") { ".json" } else { ".txt" }
            $outFile = Join-Path $OutputDir ($queryName + $ext)
            $cmd += @("--output", $outFile)
        }

        $startTime = Get-Date
        try {
            & python @cmd
            $elapsed = ((Get-Date) - $startTime).TotalSeconds
            if ($LASTEXITCODE -ne 0) {
                $msg = "run_oql.py exit code $LASTEXITCODE (after ${elapsed}s)"
                if ($ContinueOnError) {
                    Write-Warning "FAILED: $queryName - $msg"
                    $failed.Add(@{Query=$queryName; Error=$msg; Elapsed=$elapsed})
                } else {
                    throw $msg
                }
            } else {
                Write-Host "OK: $queryName ($([math]::Round($elapsed,1))s)"
                $succeeded.Add($queryName)
            }
        } catch {
            $elapsed = ((Get-Date) - $startTime).TotalSeconds
            $msg = $_.Exception.Message
            if ($ContinueOnError) {
                Write-Warning "FAILED: $queryName - $msg (after ${elapsed}s)"
                $failed.Add(@{Query=$queryName; Error=$msg; Elapsed=$elapsed})
            } else {
                throw
            }
        }
        Write-Host ""
    }
} finally {
    # ===== Process cleanup =====
    Stop-JhatProcess -Process $proc -ProcessId $jhatPid

    # Remove PID file.
    if ($PidFile) {
        $pidFullPath = Get-FullPathOrInput -Path $PidFile
        if (Test-Path -LiteralPath $pidFullPath) {
            Remove-Item -LiteralPath $pidFullPath -Force -ErrorAction SilentlyContinue
        }
    }

    # ===== Summary =====
    Write-Host ""
    Write-Host "===== Summary ====="
    Write-Host "Succeeded ($($succeeded.Count)):"
    foreach ($q in $succeeded) { Write-Host "  + $q" }
    if ($failed.Count -gt 0) {
        Write-Host "Failed ($($failed.Count)):"
        foreach ($f in $failed) {
            $elapsedStr = if ($f.ContainsKey('Elapsed')) { " ($([math]::Round($f.Elapsed,1))s)" } else { "" }
            Write-Host "  - $($f.Query)$elapsedStr : $($f.Error)"
        }
    }

    if ($OutputDir) {
        Write-Host ""
        Write-Host "Generated files in $OutputDir :"
        Get-ChildItem -LiteralPath $OutputDir -File | Sort-Object Name | ForEach-Object {
            Write-Host "  $($_.FullName) ($($_.Length) bytes)"
        }
    }
}

# Return non-zero when any query failed, even with -ContinueOnError.
if ($failed.Count -gt 0) { exit 1 }
exit 0
