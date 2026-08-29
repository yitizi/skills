---
name: teamcity
description: >
  Operate TeamCity Server/Data Center CI/CD from Windows PowerShell 5.1 or
  PowerShell 7 with UTF-8-safe scripts. Use for project, template, build
  configuration, build, queue, log, test, artifact, agent, audit, configuration
  diff, export, import, parameter, step, feature, trigger, dependency, VCS-root,
  or template-association work; including triggering, monitoring, canceling,
  troubleshooting, and guarded configuration changes.
---

# TeamCity operations

Use the bundled scripts as the execution layer. Prefer PowerShell-native
invocation on Windows; do not wrap commands in another `powershell -Command`
unless the current shell is not PowerShell.

## Locate the skill

Locate this `SKILL.md`, then keep its parent directory in `$SkillDir` for the
session:

```powershell
$SkillDir = (Resolve-Path '<directory-containing-this-SKILL.md>').Path
$TcQuery = Join-Path $SkillDir 'scripts\tc-query.ps1'
```

Check these locations only when discovery is necessary:

1. `.agents/skills/teamcity`
2. `.claude/skills/teamcity`
3. `$env:USERPROFILE\.codex\skills\teamcity`
4. `teamcity` or `skills/teamcity` in the source checkout

## Initialize and diagnose

Run the configuration check before any server call:

```powershell
& (Join-Path $SkillDir 'scripts\tc-credential.ps1') -Action check
```

- Continue when it returns `CONFIGURED|<url>`.
- When it returns `NOT_CONFIGURED`, ask the user to run `-Action setup` in an
  interactive Windows desktop session. The WinForms dialog keeps the password
  out of terminal output and the conversation.
- Use `-Action update` to rotate credentials and `-Action delete` to remove the
  TeamCity entry.
- Never read or print `.netrc`; checking that the file exists is allowed.

Run local diagnostics after installation or whenever encoding behaves oddly:

```powershell
& (Join-Path $SkillDir 'scripts\tc-doctor.ps1')
& (Join-Path $SkillDir 'scripts\tc-doctor.ps1') -Online
```

The first command is offline. The second also verifies a UTF-8 JSON response
from the configured TeamCity server.

## Preserve UTF-8 on Windows

Apply these rules to every operation:

1. Treat `.ps1` source files as UTF-8 with BOM so Windows PowerShell 5.1 loads
   non-ASCII text correctly.
2. Treat JSON, XML, HTML, logs, `config.env`, and `.netrc` as UTF-8. Write JSON
   as UTF-8 without BOM unless a target explicitly requires otherwise.
3. Pass non-trivial request bodies with `-BodyFile`; receive machine-consumed
   responses with `-OutFile`. This keeps native bytes out of the PS 5.1 text
   pipeline.
4. Never pipe TeamCity JSON through `powershell ... | python -c ...` and never
   embed JSON inside a nested `-Command` string.
5. Prefer the Python helpers for search, diff, export, and import; they configure
   redirected stdout/stderr as UTF-8 and use file-based PowerShell calls.

Read [references/windows-powershell.md](references/windows-powershell.md) when
working from Git Bash, handling Chinese text, constructing JSON, redirecting
logs, or troubleshooting mojibake.

## Use the HTTP helper

`tc-query.ps1` loads `TC_URL` from
`$env:USERPROFILE\.claude\skill-config\teamcity\config.env` and authenticates
with `curl.exe --netrc`. Its default API root is `httpAuth/app/rest`; override it
with `-ApiRoot` or optional `TC_API_ROOT` in `config.env` for a version-specific
server root. Use `-Proxy`/`-NoProxy` for a single call, or optional
`TC_PROXY`/`TC_NO_PROXY` config entries, without changing global proxy variables.

```powershell
# Display a small JSON response
& $TcQuery -Path 'server'

# Route one request through a Docker-published SOCKS5 VPN proxy
& $TcQuery -Path 'server' -Proxy 'socks5h://127.0.0.1:1080'

# Save a response as raw bytes, then decode explicitly
$response = Join-Path $env:TEMP 'tc-response.json'
& $TcQuery -Path 'builds?locator=state:running&fields=build(id,buildTypeId,status,state)' -OutFile $response
$data = [IO.File]::ReadAllText($response, [Text.UTF8Encoding]::new($false)) | ConvertFrom-Json

# Send JSON without shell escaping
$payload = Join-Path $env:TEMP 'tc-request.json'
$json = @{ buildType = @{ id = 'Example_Build' }; branchName = 'refs/heads/功能分支' } |
    ConvertTo-Json -Depth 10 -Compress
[IO.File]::WriteAllText($payload, $json, [Text.UTF8Encoding]::new($false))
& $TcQuery -Path 'buildQueue' -Method POST -BodyFile $payload
```

Use `-RawPath` for non-REST endpoints such as
`httpAuth/downloadBuildLog.html?buildId=<id>`. Use `-ContentType text/plain`
for plain-text PUT requests. Default connect/request timeouts are 15/300 seconds;
override `-ConnectTimeoutSec` or `-MaxTimeSec` for slow servers.

## Follow the operation workflow

### Read-only work

1. Resolve stable IDs before retrieving large collections.
2. Use server-side `locator` and `fields`; set an explicit `count`.
3. Save large responses or logs to a file and inspect only the relevant slice.
4. Report IDs, status, URL, and the filters used so the result is reproducible.

TeamCity 2020.1.x may return no results for
`name:(value:...,matchType:contains)` on projects and build types. Use the local
search helper instead:

```powershell
python (Join-Path $SkillDir 'scripts\tc-search.py') projects '河南'
python (Join-Path $SkillDir 'scripts\tc-search.py') templates 'deploy'
python (Join-Path $SkillDir 'scripts\tc-search.py') builds 'war' --project ProjectId
python (Join-Path $SkillDir 'scripts\tc-search.py') audit TemplateId --version 65
```

### Mutating work

Before `POST`, `PUT`, `PATCH`, or `DELETE`:

1. GET the current target and confirm its exact external ID.
2. Explain whether the operation updates one resource or replaces a collection.
3. For imports or collection-level PUT, produce a backup and run `--dry-run`.
4. Obtain explicit confirmation unless the user's current request already names
   the exact mutation and target.
5. Execute the smallest supported mutation, then GET the resource again and
   verify the intended fields.

Treat project/build-configuration deletion, queue-wide deletion, credential
deletion, and collection-level PUT as destructive. Never infer these operations
from a general cleanup or update request.

## Prefer task-specific helpers

### Configuration history and diff

```powershell
python (Join-Path $SkillDir 'scripts\tc-search.py') audit TemplateId
python (Join-Path $SkillDir 'scripts\tc-diff.py') TemplateId 64 65
python (Join-Path $SkillDir 'scripts\tc-diff.py') BuildConfigId 10 11 --type buildType
```

`tc-diff.py` reads `settingsDiffView.html`, extracts before/after XML, and
optionally decodes long `*_B64` script values for a readable unified diff.
TeamCity 2020.1.x audit locators do not support `sinceDate`; page with
`count`/`start` and filter timestamps locally.

### Export, preview, import, and package

```powershell
$export = Join-Path $env:TEMP 'template.json'
python (Join-Path $SkillDir 'scripts\tc-export.py') TemplateId -o $export
python (Join-Path $SkillDir 'scripts\tc-export.py') TemplateId --version 65 -o $export
python (Join-Path $SkillDir 'scripts\tc-import.py') TargetTemplateId $export --dry-run
python (Join-Path $SkillDir 'scripts\tc-import.py') TargetTemplateId $export --only parameters,steps --yes
python (Join-Path $SkillDir 'scripts\tc-package.py') $export -o (Join-Path $SkillDir 'artifact')
```

Import replaces each selected component as a collection. It filters inherited
parameters and intentionally does not import VCS-root entries or agent
requirements because IDs and agent properties often differ between servers.
Back up the target before import.

The packaged Windows `import.ps1` is UTF-8-with-BOM, prompts securely for the
password only when a write will occur, and does not require a password for
`-DryRun`.

## Select detailed references

- Read [references/api-operations.md](references/api-operations.md) for endpoint
  recipes covering builds, queue, tests, artifacts, changes, projects, build
  configuration internals, templates, VCS roots, dependencies, requirements,
  agents, and audit history.
- Read [references/coverage.md](references/coverage.md) to decide whether a
  request is directly covered, supported through the generic helper, version
  dependent, or intentionally guarded.
- Read [references/windows-powershell.md](references/windows-powershell.md) for
  Windows invocation and encoding details.

For an endpoint not documented in the references, inspect the configured
server's `/app/rest/swagger.json` or `/<resource>/$help` first. Prefer read-only
discovery. Do not guess a write endpoint or copy a payload from a different
TeamCity version.
