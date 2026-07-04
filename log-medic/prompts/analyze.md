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
2. Propose a fix as a description of the change (not an actual diff/patch).
3. Respond concisely — a few sentences of root cause, followed by the proposed fix description.
