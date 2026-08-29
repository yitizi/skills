# TeamCity capability coverage

Use this matrix to set expectations. The skill covers common CI/CD operations,
but it is intentionally not a frozen copy of every TeamCity REST resource.

## Coverage levels

| Level | Meaning |
|---|---|
| Direct | A bundled helper or a tested recipe exists. |
| Generic | Use `tc-query.ps1` after checking the server's Swagger or `$help`. |
| Version-dependent | Confirm the endpoint and payload on the configured server before use. |
| Guarded | High-impact administration; require exact scope, backup where possible, and explicit confirmation. |

## Matrix

| Domain | Level | Included |
|---|---|---|
| Server/configuration check | Direct | Server info, credential state, offline/online doctor, configurable API root, and skill-scoped HTTP/SOCKS proxy. |
| Authentication | Direct for Basic HTTP auth | GUI + `.netrc` keeps the password out of commands. Bearer-token auth is not implemented by the current helper. |
| Projects | Direct read; Generic write | Search/list/details. Project parameters, features, archive/name/description changes use the generic helper after discovery. |
| Build configurations/templates | Direct | Search/details, parameters, steps, features, triggers, settings, template references, history, diff, export/import. |
| Build configuration lifecycle | Version-dependent; Guarded | Create/copy/move/pause/delete are not automated by a dedicated helper. Verify Swagger and use an exact payload. |
| VCS roots and template attachment | Direct read; Generic write | List relationships. Attach/detach only after verifying IDs and server support. Creating/editing VCS roots is guarded. |
| Agent requirements and dependencies | Direct read; Generic write | List requirements plus snapshot/artifact dependencies. Collection replacement is guarded. |
| Builds | Direct | List/detail, status, effective properties, changes, related issues, problems, tests, statistics, logs, artifacts, queue/trigger/cancel. |
| Build metadata | Generic | Tags, comments, pin/unpin, status changes, and VCS labels after server discovery. |
| Queue | Direct | List, trigger, poll, cancel. Queue reorder, pause/resume, and approval are version-dependent and guarded. |
| Agents | Direct read; Generic write | List/details/compatibility. Enable/disable/authorize/pools/cloud actions require version and permission checks. |
| Audit/config versions | Direct | Audit search, local timestamp filtering, settings diff, historical export. The HTML diff endpoint is not a stable REST contract. |
| Tests/problems | Direct read; Guarded write | Test occurrences, build problems, currently failing/muted reads. Mute/unmute and investigations require exact scope. |
| Artifacts | Direct | List and binary download to `-OutFile`. Deleting artifacts or builds is guarded. |
| Users/groups/roles/tokens | Guarded | Do not automate by default. Use least-privilege admin procedures and never expose tokens/passwords. |
| Agent pools/cloud profiles/nodes/licenses | Version-dependent; Guarded | Out of the daily workflow. Discover on the target server and require administrator intent. |

## What “covered” does not mean

- Do not assume an endpoint from current JetBrains documentation exists on a
  TeamCity 2020.1.x server.
- Do not assume the unversioned REST root returns the same fields after a server
  upgrade. Configure `TC_API_ROOT` when a stable API root is required.
- Do not treat a generic `tc-query.ps1` call as authorization to mutate server
  state. Apply the mutation workflow in `SKILL.md`.
- Do not import VCS-root entries or agent requirements across servers without an
  explicit ID/property mapping.

## Discover a gap safely

1. Query `server` and record the TeamCity version.
2. Download `swagger.json` through `-OutFile`, or query
   `<resource>/$help` for locator dimensions.
3. Confirm the endpoint, HTTP method, media type, and payload schema on that
   server.
4. First perform a narrow GET with `fields`.
5. Add a reusable recipe only when the operation recurs and can be validated.

Useful official entry points:

- `https://www.jetbrains.com/help/teamcity/rest/teamcity-rest-api-documentation.html`
- `https://www.jetbrains.com/help/teamcity/rest/manage-build-configuration-details.html`
- `https://www.jetbrains.com/help/teamcity/rest/start-and-cancel-builds.html`
