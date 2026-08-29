# Windows PowerShell and UTF-8

## Encoding contract

| Boundary | Encoding/transport |
|---|---|
| `.ps1` source | UTF-8 with BOM for Windows PowerShell 5.1 compatibility. |
| JSON/XML/HTML/log files | UTF-8; JSON emitted by helpers is UTF-8 without BOM. |
| `config.env` and `.netrc` | UTF-8 without BOM; PowerShell reads them with explicit `-Encoding UTF8`. |
| PowerShell to `curl.exe` request | `--data-binary @file`; never a text pipeline. |
| `curl.exe` response to Python/PowerShell | `-OutFile`, then explicit UTF-8 decoding. |
| Python redirected output | `sys.stdout`/`sys.stderr` reconfigured to UTF-8 by `tc_common.py`. |

Windows PowerShell 5.1 defaults `$OutputEncoding` to ASCII and interprets a
BOM-less script according to the active ANSI code page. PowerShell 7 defaults to
UTF-8, but keep the file-based pattern so both engines behave identically.

## Native PowerShell invocation

Prefer direct invocation:

```powershell
$SkillDir = (Resolve-Path '.\teamcity').Path
$TcQuery = Join-Path $SkillDir 'scripts\tc-query.ps1'
& $TcQuery -Path 'server'
```

If execution policy blocks direct invocation, start one clean child process and
pass arguments with `-File`:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File $TcQuery -Path 'server'
```

Do not construct a second PowerShell command string around JSON or URLs.

## Route through a Docker VPN proxy

When the TeamCity subnet is reachable only from a VPN container, prefer a
container-published SOCKS endpoint and keep the proxy scoped to this skill:

```powershell
& $TcQuery -Path 'server' -Proxy 'socks5h://127.0.0.1:1080'
```

For repeated use, add non-secret entries to `config.env`:

```text
TC_PROXY=socks5h://127.0.0.1:1080
TC_NO_PROXY=localhost,127.0.0.1
```

`socks5h` resolves hostnames through the proxy. Do not set global
`HTTP_PROXY`/`HTTPS_PROXY` variables merely for TeamCity. Verify the actual
published port with `docker ps`; do not assume an HTTP proxy port is functional
because the container exposes it.

## Build a JSON request body

Use PowerShell objects and a UTF-8 file:

```powershell
$payloadPath = Join-Path $env:TEMP 'teamcity-payload.json'
$payload = @{
    buildType = @{ id = 'Example_Build' }
    branchName = 'refs/heads/功能分支'
    properties = @{
        property = @(
            @{ name = 'env.DEPLOY_REGION'; value = '华东' }
        )
    }
}
$json = $payload | ConvertTo-Json -Depth 20 -Compress
[IO.File]::WriteAllText($payloadPath, $json, [Text.UTF8Encoding]::new($false))
& $TcQuery -Path 'buildQueue' -Method POST -BodyFile $payloadPath
```

This avoids the fragile sequence `PowerShell string -> pipeline encoding ->
curl stdin` and avoids escaping JSON inside `-Command`.

## Read and filter a response

For small human-readable output, let `tc-query.ps1` write to the console. For
parsing or redirection, use a response file:

```powershell
$responsePath = Join-Path $env:TEMP 'teamcity-response.json'
& $TcQuery -Path 'projects?locator=count:100&fields=project(id,name)' -OutFile $responsePath
$text = [IO.File]::ReadAllText($responsePath, [Text.UTF8Encoding]::new($false))
$text | ConvertFrom-Json | Select-Object -ExpandProperty project
```

Prefer `tc-search.py` when filtering names containing Chinese. It handles the
file handoff and redirected Python output automatically.

## Save build logs and artifacts

Do not pipe large logs through `Select-Object` before saving them:

```powershell
$logPath = Join-Path $env:TEMP 'build-123.log'
& $TcQuery -Path 'httpAuth/downloadBuildLog.html?buildId=123' -RawPath -Accept 'text/plain,*/*;q=0.8' -OutFile $logPath
Get-Content -LiteralPath $logPath -Encoding UTF8 -Tail 100
```

For a binary artifact, always use `-OutFile` and `-Accept '*/*'`; never use
`Get-Content`, `Write-Output`, or a text pipe on the payload.

## Call from Git Bash

Use `-File` and Windows-style paths. Keep JSON in a file:

```bash
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$TC_QUERY" \
  -Path 'buildQueue' -Method POST -BodyFile "$PAYLOAD_JSON" \
  -OutFile "$RESPONSE_JSON"
```

Do not use a Bash variable such as `$TC_Q` inside a PowerShell `-Command`
string; Bash may expand it before PowerShell parses the command.

## Troubleshooting checklist

Run:

```powershell
& (Join-Path $SkillDir 'scripts\tc-doctor.ps1')
```

Then check:

1. All `.ps1` files report UTF-8 with BOM.
2. `curl.exe`, Python, and PowerShell are found.
3. The PowerShell-to-Python round trip passes.
4. `config.env` reports valid UTF-8.
5. `-Online` can parse the server JSON.

Common symptoms:

| Symptom | Likely cause | Fix |
|---|---|---|
| Chinese in a `.ps1` message becomes mojibake only in PS 5.1 | Script has no UTF-8 BOM. | Restore UTF-8 BOM; run doctor. |
| Chinese request values arrive as `?` | Body passed through a PS 5.1 native pipeline. | Use `-BodyFile`. |
| JSON is correct on screen but Python cannot parse redirected output | Console/pipe code pages differ. | Use `-OutFile` and read UTF-8. |
| URL containing `&` loses parameters | Nested command string or Bash expansion. | Invoke directly or use `-File` argv. |
| Chinese username is corrupted after credential update | Old ASCII-written config. | Run `tc-credential.ps1 -Action update` with the revised script. |
| Artifact is corrupt | Binary content crossed a text pipeline. | Download directly with `-OutFile -Accept '*/*'`. |
