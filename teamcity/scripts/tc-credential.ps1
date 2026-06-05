param(
    [string]$Action = "setup"
)

$ConfigDir = "$env:USERPROFILE\.claude\skill-config\teamcity"
$EnvPath = Join-Path $ConfigDir "config.env"
$NetrcPath = Join-Path $env:USERPROFILE ".netrc"

function Get-ExistingConfig {
    $config = @{ Url = ""; User = ""; Machine = "" }
    if (Test-Path $EnvPath) {
        $lines = Get-Content $EnvPath -ErrorAction SilentlyContinue
        foreach ($line in $lines) {
            if ($line -match "^TC_URL=(.+)$") { $config.Url = $Matches[1].Trim() }
            if ($line -match "^TC_USER=(.+)$") { $config.User = $Matches[1].Trim() }
        }
    }
    if ($config.Url) {
        try { $config.Machine = ([System.Uri]$config.Url).Host } catch {}
    }
    return $config
}

function Test-FullyConfigured {
    $config = Get-ExistingConfig
    if (-not $config.Url -or -not $config.Machine) { return $false }
    if (-not (Test-Path $NetrcPath)) { return $false }
    $content = Get-Content $NetrcPath -Raw -ErrorAction SilentlyContinue
    if (-not $content) { return $false }
    return ($content -match "machine\s+$([regex]::Escape($config.Machine))")
}

function Show-SetupDialog {
    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing

    $existing = Get-ExistingConfig

    $form = New-Object System.Windows.Forms.Form
    $form.Text = "TeamCity Setup"
    $form.Size = New-Object System.Drawing.Size(440, 250)
    $form.StartPosition = "CenterScreen"
    $form.FormBorderStyle = "FixedDialog"
    $form.MaximizeBox = $false

    $labelUrl = New-Object System.Windows.Forms.Label
    $labelUrl.Location = New-Object System.Drawing.Point(20, 22)
    $labelUrl.Size = New-Object System.Drawing.Size(90, 20)
    $labelUrl.Text = "Server URL:"
    $form.Controls.Add($labelUrl)

    $textUrl = New-Object System.Windows.Forms.TextBox
    $textUrl.Location = New-Object System.Drawing.Point(120, 20)
    $textUrl.Size = New-Object System.Drawing.Size(280, 20)
    $textUrl.Text = if ($existing.Url) { $existing.Url } else { "http://" }
    $form.Controls.Add($textUrl)

    $labelUser = New-Object System.Windows.Forms.Label
    $labelUser.Location = New-Object System.Drawing.Point(20, 57)
    $labelUser.Size = New-Object System.Drawing.Size(90, 20)
    $labelUser.Text = "Username:"
    $form.Controls.Add($labelUser)

    $textUser = New-Object System.Windows.Forms.TextBox
    $textUser.Location = New-Object System.Drawing.Point(120, 55)
    $textUser.Size = New-Object System.Drawing.Size(280, 20)
    $textUser.Text = if ($existing.User) { $existing.User } else { "" }
    $form.Controls.Add($textUser)

    $labelPass = New-Object System.Windows.Forms.Label
    $labelPass.Location = New-Object System.Drawing.Point(20, 92)
    $labelPass.Size = New-Object System.Drawing.Size(90, 20)
    $labelPass.Text = "Password:"
    $form.Controls.Add($labelPass)

    $textPass = New-Object System.Windows.Forms.TextBox
    $textPass.Location = New-Object System.Drawing.Point(120, 90)
    $textPass.Size = New-Object System.Drawing.Size(280, 20)
    $textPass.UseSystemPasswordChar = $true
    $form.Controls.Add($textPass)

    $labelHint = New-Object System.Windows.Forms.Label
    $labelHint.Location = New-Object System.Drawing.Point(20, 125)
    $labelHint.Size = New-Object System.Drawing.Size(390, 16)
    $labelHint.Text = "Password is stored locally in ~/.netrc, never sent to AI."
    $labelHint.ForeColor = [System.Drawing.Color]::Gray
    $form.Controls.Add($labelHint)

    $btnOK = New-Object System.Windows.Forms.Button
    $btnOK.Location = New-Object System.Drawing.Point(190, 160)
    $btnOK.Size = New-Object System.Drawing.Size(100, 32)
    $btnOK.Text = "OK"
    $btnOK.DialogResult = [System.Windows.Forms.DialogResult]::OK
    $form.AcceptButton = $btnOK
    $form.Controls.Add($btnOK)

    $btnCancel = New-Object System.Windows.Forms.Button
    $btnCancel.Location = New-Object System.Drawing.Point(300, 160)
    $btnCancel.Size = New-Object System.Drawing.Size(100, 32)
    $btnCancel.Text = "Cancel"
    $btnCancel.DialogResult = [System.Windows.Forms.DialogResult]::Cancel
    $form.CancelButton = $btnCancel
    $form.Controls.Add($btnCancel)

    $form.TopMost = $true
    $result = $form.ShowDialog()

    if ($result -ne [System.Windows.Forms.DialogResult]::OK) {
        return $null
    }

    return @{
        Url      = $textUrl.Text.TrimEnd("/")
        Username = $textUser.Text
        Password = $textPass.Text
    }
}

function Save-Config($input_data) {
    $url = $input_data.Url
    $username = $input_data.Username
    $password = $input_data.Password

    if ([string]::IsNullOrWhiteSpace($url) -or $url -eq "http://") {
        Write-Output "ERROR: server URL is empty"; exit 1
    }
    if ([string]::IsNullOrWhiteSpace($username) -or [string]::IsNullOrWhiteSpace($password)) {
        Write-Output "ERROR: username or password is empty"; exit 1
    }

    try { $machine = ([System.Uri]$url).Host } catch {
        Write-Output "ERROR: invalid URL format"; exit 1
    }

    $existing = Get-ExistingConfig

    # Write config.env
    if (-not (Test-Path $ConfigDir)) {
        New-Item -ItemType Directory -Path $ConfigDir -Force | Out-Null
    }
    $envContent = "TC_URL=$url`r`nTC_USER=$username"
    [System.IO.File]::WriteAllText($EnvPath, $envContent, [System.Text.Encoding]::ASCII)

    # Write .netrc（按 block 解析，兼容多行格式）
    # 标准 .netrc 支持单行（machine X login Y password Z）和多行格式
    $machinesToRemove = @($machine)
    if ($existing.Machine -and $existing.Machine -ne $machine) {
        $machinesToRemove += $existing.Machine
    }

    $remainingBlocks = @()
    if (Test-Path $NetrcPath) {
        $raw = Get-Content $NetrcPath -ErrorAction SilentlyContinue
        if ($raw) {
            # 按 machine 关键词分 block
            $currentBlock = @()
            foreach ($line in $raw) {
                if ($line -match '^\s*machine\s' -and $currentBlock.Count -gt 0) {
                    $remainingBlocks += ,@($currentBlock)
                    $currentBlock = @()
                }
                if ($line.Trim() -ne '') {
                    $currentBlock += $line
                }
            }
            if ($currentBlock.Count -gt 0) {
                $remainingBlocks += ,@($currentBlock)
            }

            # 过滤掉要删除的 machine
            $remainingBlocks = @($remainingBlocks | Where-Object {
                $blockFirst = $_[0]
                $remove = $false
                foreach ($m in $machinesToRemove) {
                    if ($blockFirst -match "machine\s+$([regex]::Escape($m))(\s|$)") { $remove = $true }
                }
                -not $remove
            })
        }
    }

    # 新条目始终写单行格式
    $newEntry = "machine $machine login $username password $password"
    $outputLines = @()
    foreach ($block in $remainingBlocks) {
        $outputLines += ($block -join "`r`n")
    }
    $outputLines += $newEntry
    $content = ($outputLines | Where-Object { $_ -ne $null -and $_ -ne "" }) -join "`r`n"
    [System.IO.File]::WriteAllText($NetrcPath, $content, [System.Text.Encoding]::ASCII)

    Write-Output "OK|$url"
}

# Main
if ($Action -eq "check") {
    $config = Get-ExistingConfig
    if (Test-FullyConfigured) {
        Write-Output "CONFIGURED|$($config.Url)"
    } else {
        Write-Output "NOT_CONFIGURED"
    }
}
elseif ($Action -eq "setup" -or $Action -eq "update") {
    $data = Show-SetupDialog
    if ($null -eq $data) {
        Write-Output "CANCELLED"; exit 1
    }
    Save-Config $data
}
elseif ($Action -eq "delete") {
    $config = Get-ExistingConfig
    $deleted = $false

    if (Test-Path $EnvPath) {
        Remove-Item $EnvPath
        $deleted = $true
    }

    if ($config.Machine -and (Test-Path $NetrcPath)) {
        $raw = Get-Content $NetrcPath -ErrorAction SilentlyContinue
        if ($raw) {
            # 按 block 解析，删除目标 machine 的整个 block
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

            $kept = @($blocks | Where-Object {
                $_[0] -notmatch "machine\s+$([regex]::Escape($config.Machine))(\s|$)"
            })
            if ($kept.Count -gt 0) {
                $outputLines = @()
                foreach ($b in $kept) { $outputLines += ($b -join "`r`n") }
                $remaining = ($outputLines | Where-Object { $_ -ne $null -and $_ -ne "" }) -join "`r`n"
                [System.IO.File]::WriteAllText($NetrcPath, $remaining, [System.Text.Encoding]::ASCII)
            } else {
                Remove-Item $NetrcPath
            }
            $deleted = $true
        }
    }

    if ($deleted) { Write-Output "DELETED" }
    else { Write-Output "NO_CONFIG_FOUND" }
}
