# TeamCity API operation recipes

Assume `$TcQuery` points to `scripts\tc-query.ps1`. Keep paths relative to the
configured API root; do not add a leading slash. Use external IDs rather than
internal IDs such as `bt123` unless a server response explicitly requires one.

When routing through a Docker VPN proxy, add for example
`-Proxy 'socks5h://127.0.0.1:1080'` to any `tc-query.ps1` call. Keep this proxy
skill-scoped; do not export global proxy environment variables.

For TeamCity 2020.1.x, verify any recipe marked **version-check** against the
server's `swagger.json` before writing.

## Server and discovery

```powershell
& $TcQuery -Path 'server'
& $TcQuery -Path 'swagger.json' -OutFile (Join-Path $env:TEMP 'teamcity-swagger.json')
& $TcQuery -Path 'agents/$help'
```

Use `$help` to discover locator dimensions. Use the Swagger document to verify
methods, payloads, and API-version differences.

## Projects

```powershell
# Search locally because name:contains is unreliable on some 2020.1.x servers
python (Join-Path $SkillDir 'scripts\tc-search.py') projects 'keyword'

# Children only
& $TcQuery -Path 'projects?locator=parentProject:(id:ProjectId),count:100&fields=project(id,name,description,parentProjectId)'

# Project details
& $TcQuery -Path 'projects/id:ProjectId?fields=id,name,description,archived,parentProjectId,parameters(property(name,value)),projectFeatures(projectFeature(id,type))'
```

Project parameters and features use collection/member patterns under
`projects/id:<id>/parameters` and `projects/id:<id>/projectFeatures`. Treat name,
description, archive, feature, and parameter changes as version-dependent writes;
GET the same resource and inspect Swagger before modifying.

## Build configurations and templates

```powershell
python (Join-Path $SkillDir 'scripts\tc-search.py') builds 'keyword' --project ProjectId
python (Join-Path $SkillDir 'scripts\tc-search.py') templates 'keyword'

& $TcQuery -Path 'buildTypes/id:BuildConfigId?fields=id,name,projectId,projectName,templateFlag,paused,templates(buildType(id,name))'
& $TcQuery -Path 'buildTypes?locator=templateFlag:true,project:(id:ProjectId),count:100&fields=buildType(id,name,projectId,projectName)'
& $TcQuery -Path 'buildTypes?locator=template:(id:TemplateId),count:100&fields=buildType(id,name,projectId,projectName)'
```

Use `affectedProject:(id:<project>)` instead of `project:(id:<project>)` when the
server supports recursive child-project lookup and the request needs it.

Create/copy/move/pause/delete operations are **version-check + guarded**. Current
servers expose creation at `buildTypes`, copying under a target project's
`buildTypes`, moving under `buildTypes/<locator>/move`, pausing at
`buildTypes/<locator>/paused`, and deletion of the build-type resource. Do not
apply these paths to a 2020.1.x server without Swagger confirmation.

## Builds

```powershell
# Recent builds for one configuration
& $TcQuery -Path 'builds?locator=buildType:(id:BuildConfigId),count:10&fields=build(id,number,status,statusText,state,branchName,queuedDate,startDate,finishDate,webUrl)'

# One build, including trigger and effective parameters
& $TcQuery -Path 'builds/id:123?fields=id,buildTypeId,number,status,statusText,state,branchName,triggered(type,user(username)),agent(id,name),queuedDate,startDate,finishDate,properties(property(name,value)),resultingProperties(property(name,value)),webUrl'

# Running and recently failed
& $TcQuery -Path 'builds?locator=state:running,count:100&fields=build(id,buildTypeId,status,state,percentageComplete,branchName,agent(id,name),webUrl)'
& $TcQuery -Path 'builds?locator=status:FAILURE,state:finished,count:20&fields=build(id,buildTypeId,number,statusText,startDate,finishDate,webUrl)'
```

Prefer `resultingProperties` to understand the final value after project,
template, configuration, and custom-run parameter merging. Do not print values
whose names indicate passwords, tokens, secrets, credentials, or keys.

## Trigger and poll

Create request JSON as described in `windows-powershell.md`, then:

```powershell
& $TcQuery -Path 'buildQueue' -Method POST -BodyFile $payloadPath -OutFile $responsePath
```

Common payload shapes:

```json
{"buildType":{"id":"BuildConfigId"}}
```

```json
{
  "buildType": {"id": "BuildConfigId"},
  "branchName": "refs/heads/feature/example",
  "properties": {
    "property": [
      {"name": "env.DEPLOY_REGION", "value": "华东"}
    ]
  }
}
```

Read the queued build ID from the response, then poll narrowly:

```powershell
& $TcQuery -Path 'buildQueue?locator=id:123&fields=build(id,state,queuePosition,waitReason,buildTypeId,branchName)'
& $TcQuery -Path 'builds/id:123?fields=id,state,status,statusText,percentageComplete,agent(id,name),startDate,finishDate'
```

Do not poll faster than necessary. Use increasing intervals for long builds.

## Cancel builds

Create a UTF-8 JSON body such as:

```json
{"comment":"Cancelled by requested maintenance","readdIntoQueue":false}
```

Then POST it to:

```powershell
# Queued build
& $TcQuery -Path 'buildQueue/id:123' -Method POST -BodyFile $payloadPath

# Running build
& $TcQuery -Path 'builds/id:123' -Method POST -BodyFile $payloadPath
```

Use DELETE on `buildQueue/id:<id>` only when the user explicitly wants the
queued item removed without cancellation metadata. Do not replace cancellation
with `PUT .../state finished`.

## Logs, tests, problems, changes, and issues

```powershell
# Full build log to a file
& $TcQuery -Path 'httpAuth/downloadBuildLog.html?buildId=123' -RawPath -Accept 'text/plain,*/*;q=0.8' -OutFile $logPath

# Problems and failed tests
& $TcQuery -Path 'problemOccurrences?locator=build:(id:123)&fields=problemOccurrence(id,type,identity,details,additionalData)'
& $TcQuery -Path 'testOccurrences?locator=build:(id:123),status:FAILURE&fields=testOccurrence(id,name,status,duration,details,currentlyMuted,firstFailed(id,number))'

# Changes and related issue references
& $TcQuery -Path 'builds/id:123/changes?fields=change(id,version,username,date,comment,files(file(file,relative-file)))'
& $TcQuery -Path 'builds/id:123/relatedIssues?fields=issueUsage(issue(id,url,summary,resolved))'

# Statistics
& $TcQuery -Path 'builds/id:123/statistics'
```

Mute/unmute and investigation creation are guarded writes because a broad scope
can hide failures across a project. Verify `mutes` or `investigations` schemas
and show the exact target/scope/resolution before posting.

## Artifacts

```powershell
# List artifact metadata
& $TcQuery -Path 'builds/id:123/artifacts?fields=file(name,size,modificationTime,href,children(file(name,size,href)))'

# Download one binary artifact. URL-encode the artifact path when required.
& $TcQuery -Path 'builds/id:123/artifacts/content/path/to/app.zip' -Accept '*/*' -OutFile 'C:\Temp\app.zip'
```

Some server versions expose downloads under `artifacts/files/<path>` instead of
`artifacts/content/<path>`. Follow the `href` returned by the artifact listing or
confirm Swagger. Never route binary data through a text pipeline.

## Parameters, steps, features, triggers, and settings

```powershell
& $TcQuery -Path 'buildTypes/id:BuildConfigId/parameters'
& $TcQuery -Path 'buildTypes/id:BuildConfigId/steps?fields=step(id,name,type,disabled,properties(property(name,value)))'
& $TcQuery -Path 'buildTypes/id:BuildConfigId/features?fields=feature(id,type,disabled,properties(property(name,value)))'
& $TcQuery -Path 'buildTypes/id:BuildConfigId/triggers?fields=trigger(id,type,disabled,properties(property(name,value)))'
& $TcQuery -Path 'buildTypes/id:BuildConfigId/settings'
```

Member-level endpoints normally support GET/PUT/DELETE using the member ID.
Collections normally support GET/POST and often whole-collection PUT. Prefer a
member update. Before PUT of a step, GET its complete representation, change the
smallest field, and send the complete object back.

For a plain parameter value on servers that support it:

```powershell
& $TcQuery -Path 'buildTypes/id:BuildConfigId/parameters/ParameterName/value' -Method PUT -Body '新值' -ContentType 'text/plain; charset=utf-8'
```

URL-encode parameter names that contain `/`, `?`, `#`, `%`, spaces, or non-ASCII
characters. Prefer a JSON property payload when the member URL is ambiguous.

## Dependencies, VCS roots, requirements, and templates

```powershell
& $TcQuery -Path 'buildTypes/id:BuildConfigId/snapshot-dependencies'
& $TcQuery -Path 'buildTypes/id:BuildConfigId/artifact-dependencies'
& $TcQuery -Path 'buildTypes/id:BuildConfigId/vcs-root-entries'
& $TcQuery -Path 'buildTypes/id:BuildConfigId/agent-requirements'
& $TcQuery -Path 'buildTypes/id:BuildConfigId/templates'
& $TcQuery -Path 'buildTypes/id:BuildConfigId/compatibleAgents?fields=agent(id,name,connected,enabled,authorized)'
```

These collections are easy to replace accidentally. Prefer member POST/PUT or
DELETE only after confirming the endpoint schema. Cross-server imports require
explicit mappings for VCS-root IDs, source build-type IDs, and agent properties.

## Agents

```powershell
& $TcQuery -Path 'agents?locator=count:500&fields=agent(id,name,connected,enabled,authorized,uptodate,ip,currentBuild(id,buildTypeId))'
& $TcQuery -Path 'agents/id:AgentId?fields=id,name,connected,enabled,authorized,uptodate,ip,properties(property(name,value)),currentBuild(id,buildTypeId)'
```

Enable/disable and authorize/unauthorize use `enabledInfo` and `authorizedInfo`
on supported versions. These writes affect scheduling capacity; verify the
server schema, current agent state, reason, and restoration plan first.

## Audit and configuration versions

```powershell
python (Join-Path $SkillDir 'scripts\tc-search.py') audit TemplateOrBuildTypeId
python (Join-Path $SkillDir 'scripts\tc-diff.py') TemplateId 64 65
```

On TeamCity 2020.1.x, use `count` and `start` pagination for audit events and
filter timestamps locally. The version is encoded in the `settingsChange`
entity's `internalId` as `<internal-id>|<from>|<to>` on the verified legacy
server; do not assume this undocumented representation on every version.
