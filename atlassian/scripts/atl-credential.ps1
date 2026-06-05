param(
    [string]$Action = "setup"
)

# Atlassian credential setup (Jira + Confluence + Bitbucket).
# GUI labels are loaded from atl-credential-strings.zh-CN.txt (UTF-8) at runtime.
# This .ps1 source itself stays pure ASCII because PowerShell 5.1 reads .ps1
# files as system ANSI (GBK on Chinese Windows) and would corrupt inline Chinese.
# .NET WinForms accepts the loaded UTF-16 strings and renders Chinese correctly.
#
# Stdout protocol (English, parsed by callers): OK|... CANCELLED CONFIGURED|...
# NOT_CONFIGURED DELETED NO_CONFIG_FOUND ERROR:...
# Anything after ERROR: may be Chinese explanation.

$ConfigDir = "$env:USERPROFILE\.claude\skill-config\atlassian"
$EnvPath = Join-Path $ConfigDir "config.env"
$NetrcPath = Join-Path $env:USERPROFILE ".netrc"
$Utf8NoBom = [System.Text.UTF8Encoding]::new($false)

# ===== String loading (Chinese GUI labels) =====

function Load-Strings {
    # English fallback (used if zh-CN file missing). Pure ASCII so .ps1 parses fine.
    $strings = @{
        TITLE = "Atlassian Setup (Jira + Confluence + Bitbucket)"
        GROUP_JIRA = "Jira"
        GROUP_CONFLUENCE = "Confluence"
        GROUP_BITBUCKET = "Bitbucket (optional)"
        LABEL_URL = "Server URL:"
        LABEL_USER = "Username:"
        LABEL_PASS = "Password/PAT:"
        HINT_JIRA = "Leave password blank to keep existing one"
        HINT_CONFLUENCE = "If same host as Jira, only one .netrc entry"
        HINT_BITBUCKET = "v1 reads PR/branch/commit via Jira; fill for v2 direct"
        FOOTER_LINE1 = "Passwords stored in ~/.netrc, never sent to AI; URL/user in config.env"
        FOOTER_LINE2 = "Existing URL/user pre-filled; blank password = reuse existing .netrc entry"
        FOOTER_LINE3 = "At least one of Jira/Confluence/Bitbucket required; leave others blank"
        BTN_OK = "OK"
        BTN_CANCEL = "Cancel"
        ERR_AT_LEAST_ONE = "At least one of Jira/Confluence/Bitbucket must have URL+username"
        ERR_INVALID_URL = "Invalid URL format:"
        ERR_PASSWORD_REQUIRED = "Password is required (no existing entry to reuse):"
        WARN_SAME_HOST_DIFF_USER = "Same host but different usernames; .netrc keeps last written"
    }

    # Use $PSScriptRoot - $MyInvocation.MyCommand.Path is null inside a function.
    $scriptDir = $PSScriptRoot
    if (-not $scriptDir) {
        # Fallback for very old PS / dot-sourced scenarios
        $scriptDir = Split-Path -Parent $script:MyInvocation.MyCommand.Path
    }
    $stringsFile = Join-Path $scriptDir "atl-credential-strings.zh-CN.txt"
    if (Test-Path -LiteralPath $stringsFile) {
        try {
            $lines = Get-Content -LiteralPath $stringsFile -Encoding UTF8 -ErrorAction Stop
            foreach ($line in $lines) {
                if ($line -match '^\s*#') { continue }
                if ($line -match '^([A-Z_][A-Z0-9_]*)=(.*)$') {
                    $strings[$Matches[1]] = $Matches[2].Trim()
                }
            }
        } catch {
            # Fall back silently to English
        }
    }
    return $strings
}

# ===== Config / netrc helpers =====

function Get-ExistingConfig {
    $config = @{
        JiraUrl = ""; JiraUser = ""; JiraMachine = ""
        ConfluenceUrl = ""; ConfluenceUser = ""; ConfluenceMachine = ""
        BitbucketUrl = ""; BitbucketUser = ""; BitbucketMachine = ""
        CacheDir = ""
    }
    if (Test-Path $EnvPath) {
        $lines = Get-Content $EnvPath -ErrorAction SilentlyContinue
        foreach ($line in $lines) {
            if ($line -match "^JIRA_URL=(.+)$") { $config.JiraUrl = $Matches[1].Trim() }
            if ($line -match "^JIRA_USER=(.+)$") { $config.JiraUser = $Matches[1].Trim() }
            if ($line -match "^CONFLUENCE_URL=(.+)$") { $config.ConfluenceUrl = $Matches[1].Trim() }
            if ($line -match "^CONFLUENCE_USER=(.+)$") { $config.ConfluenceUser = $Matches[1].Trim() }
            if ($line -match "^BITBUCKET_URL=(.+)$") { $config.BitbucketUrl = $Matches[1].Trim() }
            if ($line -match "^BITBUCKET_USER=(.+)$") { $config.BitbucketUser = $Matches[1].Trim() }
            if ($line -match "^CACHE_DIR=(.+)$") { $config.CacheDir = $Matches[1].Trim() }
        }
    }
    if ($config.JiraUrl) { try { $config.JiraMachine = ([System.Uri]$config.JiraUrl).Host } catch {} }
    if ($config.ConfluenceUrl) { try { $config.ConfluenceMachine = ([System.Uri]$config.ConfluenceUrl).Host } catch {} }
    if ($config.BitbucketUrl) { try { $config.BitbucketMachine = ([System.Uri]$config.BitbucketUrl).Host } catch {} }
    return $config
}

function Test-NetrcHasMachine {
    param([string]$Machine)
    if (-not $Machine) { return $false }
    if (-not (Test-Path $NetrcPath)) { return $false }
    $content = Get-Content $NetrcPath -Raw -ErrorAction SilentlyContinue
    if (-not $content) { return $false }
    return ($content -match "machine\s+$([regex]::Escape($Machine))(\s|$)")
}

function Test-FullyConfigured {
    $config = Get-ExistingConfig
    $jiraOk = $config.JiraUrl -and $config.JiraMachine -and (Test-NetrcHasMachine $config.JiraMachine)
    $confOk = $config.ConfluenceUrl -and $config.ConfluenceMachine -and (Test-NetrcHasMachine $config.ConfluenceMachine)
    $bbOk = $config.BitbucketUrl -and $config.BitbucketMachine -and (Test-NetrcHasMachine $config.BitbucketMachine)
    return ($jiraOk -or $confOk -or $bbOk)
}

function Get-NetrcBlocks {
    if (-not (Test-Path $NetrcPath)) { return @() }
    $raw = Get-Content $NetrcPath -ErrorAction SilentlyContinue
    if (-not $raw) { return @() }
    $blocks = @()
    $currentBlock = @()
    foreach ($line in $raw) {
        if ($line -match '^\s*machine\s' -and $currentBlock.Count -gt 0) {
            $blocks += ,@($currentBlock)
            $currentBlock = @()
        }
        if ($line.Trim() -ne '') { $currentBlock += $line }
    }
    if ($currentBlock.Count -gt 0) { $blocks += ,@($currentBlock) }
    return $blocks
}

function Save-NetrcEntry {
    param([string]$Machine, [string]$Username, [string]$Password)
    if (-not $Machine -or -not $Username -or -not $Password) { return }
    $blocks = Get-NetrcBlocks
    $kept = @($blocks | Where-Object {
        $_[0] -notmatch "machine\s+$([regex]::Escape($Machine))(\s|$)"
    })
    $newEntry = "machine $Machine login $Username password $Password"
    $outputLines = @()
    foreach ($b in $kept) { $outputLines += ($b -join "`r`n") }
    $outputLines += $newEntry
    $content = ($outputLines | Where-Object { $_ -ne $null -and $_ -ne "" }) -join "`r`n"
    [System.IO.File]::WriteAllText($NetrcPath, $content, $Utf8NoBom)
}

function Get-NetrcPasswordForMachine {
    param([string]$Machine)
    if (-not $Machine) { return "" }
    $blocks = Get-NetrcBlocks
    foreach ($b in $blocks) {
        $joined = $b -join " "
        if ($joined -match "machine\s+$([regex]::Escape($Machine))\b.*?\bpassword\s+(\S+)") {
            return $Matches[1]
        }
    }
    return ""
}

# ===== GUI =====

function Show-SetupDialog {
    param($Strings)

    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing

    $existing = Get-ExistingConfig

    $form = New-Object System.Windows.Forms.Form
    $form.Text = $Strings.TITLE
    $form.Size = New-Object System.Drawing.Size(500, 605)
    $form.StartPosition = "CenterScreen"
    $form.FormBorderStyle = "FixedDialog"
    $form.MaximizeBox = $false
    # Use a font that ships with Chinese glyphs on Windows
    $form.Font = New-Object System.Drawing.Font("Microsoft YaHei UI", 9)

    # Helper: build a credential group (URL / user / pass + hint)
    function New-CredGroup {
        param(
            [string]$Title, [int]$YPos,
            [string]$ExistingUrl, [string]$ExistingUser,
            [string]$LabelUrl, [string]$LabelUser, [string]$LabelPass,
            [string]$Hint
        )
        $grp = New-Object System.Windows.Forms.GroupBox
        $grp.Location = New-Object System.Drawing.Point(10, $YPos)
        $grp.Size = New-Object System.Drawing.Size(465, 130)
        $grp.Text = $Title

        $labelUrl = New-Object System.Windows.Forms.Label
        $labelUrl.Location = New-Object System.Drawing.Point(10, 22)
        $labelUrl.Size = New-Object System.Drawing.Size(120, 20)
        $labelUrl.Text = $LabelUrl
        $grp.Controls.Add($labelUrl)

        $textUrl = New-Object System.Windows.Forms.TextBox
        $textUrl.Location = New-Object System.Drawing.Point(135, 20)
        $textUrl.Size = New-Object System.Drawing.Size(310, 20)
        $textUrl.Text = if ($ExistingUrl) { $ExistingUrl } else { "http://" }
        $grp.Controls.Add($textUrl)

        $labelUser = New-Object System.Windows.Forms.Label
        $labelUser.Location = New-Object System.Drawing.Point(10, 52)
        $labelUser.Size = New-Object System.Drawing.Size(120, 20)
        $labelUser.Text = $LabelUser
        $grp.Controls.Add($labelUser)

        $textUser = New-Object System.Windows.Forms.TextBox
        $textUser.Location = New-Object System.Drawing.Point(135, 50)
        $textUser.Size = New-Object System.Drawing.Size(310, 20)
        $textUser.Text = $ExistingUser
        $grp.Controls.Add($textUser)

        $labelPass = New-Object System.Windows.Forms.Label
        $labelPass.Location = New-Object System.Drawing.Point(10, 82)
        $labelPass.Size = New-Object System.Drawing.Size(120, 20)
        $labelPass.Text = $LabelPass
        $grp.Controls.Add($labelPass)

        $textPass = New-Object System.Windows.Forms.TextBox
        $textPass.Location = New-Object System.Drawing.Point(135, 80)
        $textPass.Size = New-Object System.Drawing.Size(310, 20)
        $textPass.UseSystemPasswordChar = $true
        $grp.Controls.Add($textPass)

        $labelHint = New-Object System.Windows.Forms.Label
        $labelHint.Location = New-Object System.Drawing.Point(135, 105)
        $labelHint.Size = New-Object System.Drawing.Size(310, 18)
        $labelHint.Text = $Hint
        $labelHint.ForeColor = [System.Drawing.Color]::Gray
        $grp.Controls.Add($labelHint)

        return @{
            GroupBox = $grp
            Url = $textUrl
            User = $textUser
            Pass = $textPass
        }
    }

    $jira = New-CredGroup -Title $Strings.GROUP_JIRA -YPos 8 `
        -ExistingUrl $existing.JiraUrl -ExistingUser $existing.JiraUser `
        -LabelUrl $Strings.LABEL_URL -LabelUser $Strings.LABEL_USER -LabelPass $Strings.LABEL_PASS `
        -Hint $Strings.HINT_JIRA
    $form.Controls.Add($jira.GroupBox)

    $conf = New-CredGroup -Title $Strings.GROUP_CONFLUENCE -YPos 145 `
        -ExistingUrl $existing.ConfluenceUrl -ExistingUser $existing.ConfluenceUser `
        -LabelUrl $Strings.LABEL_URL -LabelUser $Strings.LABEL_USER -LabelPass $Strings.LABEL_PASS `
        -Hint $Strings.HINT_CONFLUENCE
    $form.Controls.Add($conf.GroupBox)

    $bb = New-CredGroup -Title $Strings.GROUP_BITBUCKET -YPos 282 `
        -ExistingUrl $existing.BitbucketUrl -ExistingUser $existing.BitbucketUser `
        -LabelUrl $Strings.LABEL_URL -LabelUser $Strings.LABEL_USER -LabelPass $Strings.LABEL_PASS `
        -Hint $Strings.HINT_BITBUCKET
    $form.Controls.Add($bb.GroupBox)

    # Footer (three lines)
    $labelFoot1 = New-Object System.Windows.Forms.Label
    $labelFoot1.Location = New-Object System.Drawing.Point(20, 422)
    $labelFoot1.Size = New-Object System.Drawing.Size(460, 18)
    $labelFoot1.Text = $Strings.FOOTER_LINE1
    $labelFoot1.ForeColor = [System.Drawing.Color]::Gray
    $form.Controls.Add($labelFoot1)

    $labelFoot2 = New-Object System.Windows.Forms.Label
    $labelFoot2.Location = New-Object System.Drawing.Point(20, 442)
    $labelFoot2.Size = New-Object System.Drawing.Size(460, 18)
    $labelFoot2.Text = $Strings.FOOTER_LINE2
    $labelFoot2.ForeColor = [System.Drawing.Color]::Gray
    $form.Controls.Add($labelFoot2)

    $labelFoot3 = New-Object System.Windows.Forms.Label
    $labelFoot3.Location = New-Object System.Drawing.Point(20, 462)
    $labelFoot3.Size = New-Object System.Drawing.Size(460, 18)
    $labelFoot3.Text = $Strings.FOOTER_LINE3
    $labelFoot3.ForeColor = [System.Drawing.Color]::Gray
    $form.Controls.Add($labelFoot3)

    # Buttons
    $btnOK = New-Object System.Windows.Forms.Button
    $btnOK.Location = New-Object System.Drawing.Point(255, 498)
    $btnOK.Size = New-Object System.Drawing.Size(100, 32)
    $btnOK.Text = $Strings.BTN_OK
    $btnOK.DialogResult = [System.Windows.Forms.DialogResult]::OK
    $form.AcceptButton = $btnOK
    $form.Controls.Add($btnOK)

    $btnCancel = New-Object System.Windows.Forms.Button
    $btnCancel.Location = New-Object System.Drawing.Point(365, 498)
    $btnCancel.Size = New-Object System.Drawing.Size(100, 32)
    $btnCancel.Text = $Strings.BTN_CANCEL
    $btnCancel.DialogResult = [System.Windows.Forms.DialogResult]::Cancel
    $form.CancelButton = $btnCancel
    $form.Controls.Add($btnCancel)

    $form.TopMost = $true
    $result = $form.ShowDialog()

    if ($result -ne [System.Windows.Forms.DialogResult]::OK) { return $null }

    return @{
        JiraUrl = $jira.Url.Text.TrimEnd("/")
        JiraUser = $jira.User.Text
        JiraPass = $jira.Pass.Text
        ConfluenceUrl = $conf.Url.Text.TrimEnd("/")
        ConfluenceUser = $conf.User.Text
        ConfluencePass = $conf.Pass.Text
        BitbucketUrl = $bb.Url.Text.TrimEnd("/")
        BitbucketUser = $bb.User.Text
        BitbucketPass = $bb.Pass.Text
    }
}

# ===== Save =====

function Save-Config {
    param($Data, $Strings)

    $jiraValid = $Data.JiraUrl -and $Data.JiraUrl -ne "http://" -and $Data.JiraUser
    $confValid = $Data.ConfluenceUrl -and $Data.ConfluenceUrl -ne "http://" -and $Data.ConfluenceUser
    $bbValid = $Data.BitbucketUrl -and $Data.BitbucketUrl -ne "http://" -and $Data.BitbucketUser

    if (-not $jiraValid -and -not $confValid -and -not $bbValid) {
        Write-Output ("ERROR: " + $Strings.ERR_AT_LEAST_ONE)
        exit 1
    }

    # Compute machine hosts
    $jiraMachine = ""
    $confMachine = ""
    $bbMachine = ""
    if ($jiraValid) {
        try { $jiraMachine = ([System.Uri]$Data.JiraUrl).Host } catch {
            Write-Output ("ERROR: " + $Strings.ERR_INVALID_URL + " " + $Data.JiraUrl); exit 1
        }
    }
    if ($confValid) {
        try { $confMachine = ([System.Uri]$Data.ConfluenceUrl).Host } catch {
            Write-Output ("ERROR: " + $Strings.ERR_INVALID_URL + " " + $Data.ConfluenceUrl); exit 1
        }
    }
    if ($bbValid) {
        try { $bbMachine = ([System.Uri]$Data.BitbucketUrl).Host } catch {
            Write-Output ("ERROR: " + $Strings.ERR_INVALID_URL + " " + $Data.BitbucketUrl); exit 1
        }
    }

    # Resolve passwords (allow blank to keep existing per-machine)
    $jiraPass = $Data.JiraPass
    $confPass = $Data.ConfluencePass
    $bbPass = $Data.BitbucketPass
    if ($jiraValid -and -not $jiraPass) { $jiraPass = Get-NetrcPasswordForMachine $jiraMachine }
    if ($confValid -and -not $confPass) { $confPass = Get-NetrcPasswordForMachine $confMachine }
    if ($bbValid -and -not $bbPass) { $bbPass = Get-NetrcPasswordForMachine $bbMachine }
    if ($jiraValid -and -not $jiraPass) {
        Write-Output ("ERROR: " + $Strings.ERR_PASSWORD_REQUIRED + " Jira"); exit 1
    }
    if ($confValid -and -not $confPass) {
        Write-Output ("ERROR: " + $Strings.ERR_PASSWORD_REQUIRED + " Confluence"); exit 1
    }
    if ($bbValid -and -not $bbPass) {
        Write-Output ("ERROR: " + $Strings.ERR_PASSWORD_REQUIRED + " Bitbucket"); exit 1
    }

    # Write config.env
    if (-not (Test-Path $ConfigDir)) {
        New-Item -ItemType Directory -Path $ConfigDir -Force | Out-Null
    }
    $envLines = @()
    if ($jiraValid) {
        $envLines += "JIRA_URL=$($Data.JiraUrl)"
        $envLines += "JIRA_USER=$($Data.JiraUser)"
    }
    if ($confValid) {
        $envLines += "CONFLUENCE_URL=$($Data.ConfluenceUrl)"
        $envLines += "CONFLUENCE_USER=$($Data.ConfluenceUser)"
    }
    if ($bbValid) {
        $envLines += "BITBUCKET_URL=$($Data.BitbucketUrl)"
        $envLines += "BITBUCKET_USER=$($Data.BitbucketUser)"
    }
    $envContent = $envLines -join "`r`n"
    [System.IO.File]::WriteAllText($EnvPath, $envContent, $Utf8NoBom)

    # Write .netrc entries (one per unique machine).
    # Same-host services share one entry; if usernames differ, the LAST written wins.
    $hostUserMap = @{}
    if ($jiraValid) {
        if ($hostUserMap.ContainsKey($jiraMachine) -and $hostUserMap[$jiraMachine] -ne $Data.JiraUser) {
            Write-Output ("WARN: " + $Strings.WARN_SAME_HOST_DIFF_USER + " (" + $jiraMachine + ")")
        }
        Save-NetrcEntry -Machine $jiraMachine -Username $Data.JiraUser -Password $jiraPass
        $hostUserMap[$jiraMachine] = $Data.JiraUser
    }
    if ($confValid) {
        if ($hostUserMap.ContainsKey($confMachine) -and $hostUserMap[$confMachine] -ne $Data.ConfluenceUser) {
            Write-Output ("WARN: " + $Strings.WARN_SAME_HOST_DIFF_USER + " (" + $confMachine + ")")
        }
        Save-NetrcEntry -Machine $confMachine -Username $Data.ConfluenceUser -Password $confPass
        $hostUserMap[$confMachine] = $Data.ConfluenceUser
    }
    if ($bbValid) {
        if ($hostUserMap.ContainsKey($bbMachine) -and $hostUserMap[$bbMachine] -ne $Data.BitbucketUser) {
            Write-Output ("WARN: " + $Strings.WARN_SAME_HOST_DIFF_USER + " (" + $bbMachine + ")")
        }
        Save-NetrcEntry -Machine $bbMachine -Username $Data.BitbucketUser -Password $bbPass
        $hostUserMap[$bbMachine] = $Data.BitbucketUser
    }

    $summary = @()
    if ($jiraValid) { $summary += "JIRA=$($Data.JiraUrl)" }
    if ($confValid) { $summary += "CONFLUENCE=$($Data.ConfluenceUrl)" }
    if ($bbValid)   { $summary += "BITBUCKET=$($Data.BitbucketUrl)" }
    Write-Output "OK|$($summary -join '|')"
}

# ===== Main =====

$strings = Load-Strings

if ($Action -eq "check") {
    $config = Get-ExistingConfig
    if (Test-FullyConfigured) {
        $parts = @()
        if ($config.JiraUrl) { $parts += "JIRA=$($config.JiraUrl)" }
        if ($config.ConfluenceUrl) { $parts += "CONFLUENCE=$($config.ConfluenceUrl)" }
        if ($config.BitbucketUrl) { $parts += "BITBUCKET=$($config.BitbucketUrl)" }
        Write-Output "CONFIGURED|$($parts -join '|')"
    } else {
        Write-Output "NOT_CONFIGURED"
    }
}
elseif ($Action -eq "setup" -or $Action -eq "update") {
    $data = Show-SetupDialog -Strings $strings
    if ($null -eq $data) { Write-Output "CANCELLED"; exit 1 }
    Save-Config -Data $data -Strings $strings
}
elseif ($Action -eq "delete") {
    $config = Get-ExistingConfig
    $deleted = $false

    if (Test-Path $EnvPath) { Remove-Item $EnvPath; $deleted = $true }

    $machinesToRemove = @()
    if ($config.JiraMachine) { $machinesToRemove += $config.JiraMachine }
    if ($config.ConfluenceMachine -and ($config.ConfluenceMachine -notin $machinesToRemove)) {
        $machinesToRemove += $config.ConfluenceMachine
    }
    if ($config.BitbucketMachine -and ($config.BitbucketMachine -notin $machinesToRemove)) {
        $machinesToRemove += $config.BitbucketMachine
    }

    if ($machinesToRemove.Count -gt 0 -and (Test-Path $NetrcPath)) {
        $blocks = Get-NetrcBlocks
        $kept = @($blocks | Where-Object {
            $blockFirst = $_[0]
            $remove = $false
            foreach ($m in $machinesToRemove) {
                if ($blockFirst -match "machine\s+$([regex]::Escape($m))(\s|$)") { $remove = $true }
            }
            -not $remove
        })
        if ($kept.Count -gt 0) {
            $outputLines = @()
            foreach ($b in $kept) { $outputLines += ($b -join "`r`n") }
            $remaining = ($outputLines | Where-Object { $_ -ne $null -and $_ -ne "" }) -join "`r`n"
            [System.IO.File]::WriteAllText($NetrcPath, $remaining, $Utf8NoBom)
        } else {
            Remove-Item $NetrcPath
        }
        $deleted = $true
    }

    if ($deleted) { Write-Output "DELETED" } else { Write-Output "NO_CONFIG_FOUND" }
}
else {
    Write-Output "ERROR: unknown action '$Action'. Use: check / setup / update / delete"
    exit 1
}
