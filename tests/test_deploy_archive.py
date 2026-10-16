"""Exercise deploy.sh's real archive exclusions without running deployment."""

from __future__ import annotations

import io
import os
import re
import shlex
import subprocess
import tarfile
from pathlib import Path


def test_deploy_archive_excludes_workstation_secrets(
    tmp_path: Path, scripts_dir: Path
) -> None:
    # Parse only the literal array; never source deploy.sh or its credentials.
    script = (scripts_dir / "deploy.sh").read_text()
    array = re.search(r"(?ms)^\s*TAR_EXCLUDES=\(\s*\n(.*?)^\s*\)", script)
    assert array is not None, "deploy.sh must define its archive exclusions"
    excludes = shlex.split(array.group(1), comments=True)
    assert excludes and all(arg.startswith("--exclude=") for arg in excludes)

    project = tmp_path / "project"
    included = {
        "lotto-picker/app/static/app.js",
        "lotto-picker/nginx/.htpasswd",
        "secrets/vault.sops.yaml",
    }
    excluded = {
        ".env",
        ".env.deploy",
        "secrets/vault.yaml",
        "lotto-picker/.env",
        "secretary/query/.env",
    }
    for name in included | excluded:
        path = project / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("synthetic fixture\n")

    archive = subprocess.run(
        ["tar", "-czf", "-", *excludes, "-C", str(project), "."],
        check=True,
        capture_output=True,
        env={**os.environ, "COPYFILE_DISABLE": "1"},
    ).stdout
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as bundle:
        names = {member.name.removeprefix("./") for member in bundle if member.isfile()}

    assert included <= names, "deployment source and required auth must remain bundled"
    assert not (excluded & names), f"private files bundled: {sorted(excluded & names)}"
