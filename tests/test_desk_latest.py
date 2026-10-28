"""desk_latest.py finds every pin it claims to bump, without the network."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load():
    spec = importlib.util.spec_from_file_location(
        "desk_latest", REPO_ROOT / "scripts" / "desk_latest.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_pin_reads_exactly_one_value():
    for pin in _load().PINS:
        assert pin.current()   # raises SystemExit if the file's shape drifted


def test_every_base_image_is_pinned_by_digest():
    dockerfiles = [REPO_ROOT / "ai-deck" / "Dockerfile", REPO_ROOT / "ai-deck" / "nginx" / "Dockerfile"]
    for path in dockerfiles:
        for line in path.read_text().splitlines():
            if line.startswith("FROM ") and not line.startswith("FROM desk_runtime"):
                assert re.search(r"@sha256:[0-9a-f]{64}\b", line), line


def test_a_base_pin_rewrites_only_its_digest(tmp_path, monkeypatch):
    module = _load()
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text(
        "FROM node:22-bookworm-slim@sha256:" + "a" * 64 + " AS node_source\n"
        "FROM debian:bookworm-slim@sha256:" + "b" * 64 + " AS desk_runtime\n")
    monkeypatch.setattr(module, "ROOT", tmp_path)
    pin = module.base_image("Node base", "Dockerfile", "node", "22-bookworm-slim")
    assert pin.current() == "sha256:" + "a" * 64
    pin.write("sha256:" + "c" * 64)
    assert dockerfile.read_text() == (
        "FROM node:22-bookworm-slim@sha256:" + "c" * 64 + " AS node_source\n"
        "FROM debian:bookworm-slim@sha256:" + "b" * 64 + " AS desk_runtime\n")


def test_make_commits_the_nginx_dockerfile_with_the_pins():
    makefile = (REPO_ROOT / "Makefile").read_text()
    pins = re.search(r"^DESK_PINS = (.+)$", makefile, re.M)[1].split()
    assert "ai-deck/nginx/Dockerfile" in pins
