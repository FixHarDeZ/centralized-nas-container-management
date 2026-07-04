from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Request

from app import db
from app.deps import get_db

router = APIRouter(prefix="/api/containers")


@router.get("")
def list_containers(request: Request, conn=Depends(get_db)):
    monitored = {r["name"]: dict(r) for r in db.list_monitored_containers(conn)}
    docker_client = request.app.state.docker_client
    running = {c.name for c in docker_client.containers.list()}
    discovered = [{"name": n, "monitored": False} for n in running if n not in monitored]
    return list(monitored.values()) + discovered


@router.post("")
def add_container(payload: dict, request: Request, conn=Depends(get_db)):
    name = payload["name"]
    docker_client = request.app.state.docker_client
    running_names = {c.name for c in docker_client.containers.list()}
    if running_names and name not in running_names:
        raise HTTPException(status_code=400, detail=f"container '{name}' not found on docker")
    db.upsert_monitored_container(
        conn,
        name,
        payload.get("repo"),
        payload.get("subdir"),
        payload.get("maturity", "dev"),
        1 if payload.get("notify_only") else 0,
        0,
        payload.get("regex_override"),
    )
    db.write_audit(conn, "add_container", json.dumps(payload))
    return dict(db.get_monitored_container(conn, name))


@router.patch("/{name}")
def patch_container(name: str, payload: dict, conn=Depends(get_db)):
    row = db.get_monitored_container(conn, name)
    if not row:
        raise HTTPException(status_code=404, detail="not found")
    merged = dict(row)
    merged.update(payload)
    db.upsert_monitored_container(
        conn,
        name,
        merged.get("repo"),
        merged.get("subdir"),
        merged.get("maturity"),
        1 if merged.get("notify_only") else 0,
        1 if merged.get("paused") else 0,
        merged.get("regex_override"),
    )
    db.write_audit(conn, "patch_container", json.dumps({"name": name, **payload}))
    return dict(db.get_monitored_container(conn, name))


@router.delete("/{name}")
def delete_container(name: str, conn=Depends(get_db)):
    db.delete_monitored_container(conn, name)
    db.write_audit(conn, "delete_container", json.dumps({"name": name}))
    return {"deleted": name}
