param(
    [string]$DumpPath = "",
    [switch]$Help
)

$ErrorActionPreference = "Continue"

function Show-Help {
    @"
Usage: powershell -ExecutionPolicy Bypass -File find_mat.ps1 [-DumpPath <path>]

Discover Eclipse MAT installation and existing analysis artifacts.

Steps:
  1. Check PATH for ParseHeapDump.bat / MemoryAnalyzer.exe
  2. Search common install locations (Program Files, user dirs, G:\jvmdump)
  3. If -DumpPath given: check dump dir for existing .index / _Leak_Suspects / .html

Output:
  Plain-text findings for AI to consume.

Examples:
  powershell -ExecutionPolicy Bypass -File find_mat.ps1
  powershell -ExecutionPolicy Bypass -File find_mat.ps1 -DumpPath 'D:\dump\heap.hprof'
"@
}

if ($Help) { Show-Help; exit 0 }

Write-Host "===== Eclipse MAT Discovery ====="
Write-Host ""

# 1. Check PATH
Write-Host "[1] Searching PATH..."
$inPath = $false
foreach ($exe in @("ParseHeapDump.bat", "MemoryAnalyzer.exe", "MemoryAnalyzerc.exe")) {
    $found = Get-Command $exe -ErrorAction SilentlyContinue
    if ($found) {
        Write-Host "  FOUND in PATH: $($found.Source)"
        $inPath = $true
    }
}
if (-not $inPath) {
    Write-Host "  NOT in PATH"
}
Write-Host ""

# 2. Search common install locations
Write-Host "[2] Searching common install locations..."
$candidates = @(
    "C:\Program Files\mat",
    "C:\Program Files\Eclipse\mat",
    "C:\Program Files (x86)\mat",
    "C:\mat",
    "C:\eclipse\mat",
    "C:\tools\mat",
    "D:\mat",
    "D:\tools\mat",
    "G:\jvmdump\mat",
    "G:\tools\mat",
    "$env:USERPROFILE\mat",
    "$env:USERPROFILE\eclipse\mat",
    "$env:USERPROFILE\Desktop\mat",
    "$env:USERPROFILE\Downloads\mat"
)
# Also search mat-* wildcards
$wildcards = @(
    "C:\Program Files\mat-*",
    "C:\mat-*",
    "D:\mat-*",
    "G:\*\mat-*",
    "$env:USERPROFILE\mat-*"
)
foreach ($wc in $wildcards) {
    try {
        Get-Item -Path $wc -ErrorAction SilentlyContinue | ForEach-Object {
            $candidates += $_.FullName
        }
    } catch {}
}

$matRoot = ""
foreach ($dir in $candidates | Select-Object -Unique) {
    if (Test-Path -LiteralPath $dir) {
        $bat = Join-Path $dir "ParseHeapDump.bat"
        $exe = Join-Path $dir "MemoryAnalyzer.exe"
        if ((Test-Path -LiteralPath $bat) -or (Test-Path -LiteralPath $exe)) {
            Write-Host "  FOUND: $dir"
            if (Test-Path -LiteralPath $bat) { Write-Host "    - ParseHeapDump.bat" }
            if (Test-Path -LiteralPath $exe) { Write-Host "    - MemoryAnalyzer.exe" }
            if (-not $matRoot) { $matRoot = $dir }
        }
    }
}
if (-not $matRoot -and -not $inPath) {
    Write-Host "  NOT found in common locations"
    Write-Host ""
    Write-Host "  Install MAT from: https://eclipse.dev/mat/downloads.php"
    Write-Host "  Or use jhat-only workflow (acceptable for <500MB dumps)"
}
Write-Host ""

# 3. Check for reusable MAT artifacts in dump directory
if ($DumpPath) {
    Write-Host "[3] Checking for existing MAT artifacts in dump directory..."
    if (-not (Test-Path -LiteralPath $DumpPath)) {
        Write-Host "  Dump file not found: $DumpPath"
    } else {
        $dumpDir = Split-Path -Parent (Resolve-Path -LiteralPath $DumpPath)
        $dumpName = [System.IO.Path]::GetFileNameWithoutExtension($DumpPath)
        Write-Host "  Dump dir: $dumpDir"

        # MAT index files (.index, .a2s, .o2c, .o2h, .domIn, etc.)
        $indexFiles = Get-ChildItem -LiteralPath $dumpDir -Filter "$dumpName*.index" -ErrorAction SilentlyContinue
        if ($indexFiles) {
            Write-Host "  FOUND existing MAT index ($($indexFiles.Count) files):"
            $indexFiles | Select-Object -First 5 | ForEach-Object {
                Write-Host "    - $($_.Name) ($($_.Length) bytes)"
            }
            Write-Host "  -> MAT has already parsed this dump. Load in GUI directly, no need to re-run ParseHeapDump."
        } else {
            Write-Host "  No existing MAT index"
        }

        # Leak Suspects / Top Components reports
        $reports = Get-ChildItem -LiteralPath $dumpDir -Filter "$dumpName*_*.zip" -ErrorAction SilentlyContinue
        if ($reports) {
            Write-Host "  FOUND existing MAT reports:"
            $reports | ForEach-Object {
                Write-Host "    - $($_.Name) ($([math]::Round($_.Length/1024,1)) KB)"
            }
            Write-Host "  -> Existing reports can be reused directly. Unzip and open index.html."
        }

        # HTML report directories
        $htmlDirs = Get-ChildItem -LiteralPath $dumpDir -Directory -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -like "$dumpName*" }
        if ($htmlDirs) {
            Write-Host "  FOUND extracted report dirs:"
            $htmlDirs | ForEach-Object {
                $idx = Join-Path $_.FullName "index.html"
                if (Test-Path -LiteralPath $idx) {
                    Write-Host "    - $($_.Name)/index.html"
                }
            }
        }
    }
    Write-Host ""
}

# 4. Summary
Write-Host "===== Summary ====="
if ($matRoot) {
    Write-Host "MAT_HOME=$matRoot"
    Write-Host "ParseHeapDump=$matRoot\ParseHeapDump.bat"
    Write-Host ""
    Write-Host "Run leak suspects:"
    Write-Host "  & '$matRoot\ParseHeapDump.bat' '<dump>' org.eclipse.mat.api:suspects"
} elseif ($inPath) {
    Write-Host "MAT in PATH (use ParseHeapDump.bat directly)"
} else {
    Write-Host "MAT not installed. Options:"
    Write-Host "  1. Install: https://eclipse.dev/mat/downloads.php"
    Write-Host "  2. Use jhat-only workflow (acceptable for small dumps, no retained heap)"
    Write-Host "  3. Reuse existing MAT artifacts if present (see [3] above)"
}
