You are analyzing a WARN/ERROR log event from the Docker container `{{container}}`.

## Log excerpt (30 lines before, trigger line, up to 10 lines after)
```
{{excerpt}}
```

## Repository context
The service's source lives at `{{repo}}/{{subdir}}`. You may use `git log` and
`git diff` to check recent history, and `Read`/`Grep`/`Glob` to inspect the
current code. Do NOT edit any files — this is read-only root-cause analysis.

## Task
1. Identify the root cause of this error.
2. Classify root cause as:
   - `code` — root cause lives in the service's source code in the repo; code change can fix it.
   - `infra` — network failure, external API outage, rate limit, disk/permission problem, runtime configuration issue; code change cannot fix it.
3. Propose a fix as a description of the change (not an actual diff/patch).
4. Respond with **VERDICT line first**, then brief analysis.

## Response format (mandatory)
FIRST line of response exactly one of:

VERDICT: code
VERDICT: infra

Followed by sentences on root cause, then proposed fix description.
