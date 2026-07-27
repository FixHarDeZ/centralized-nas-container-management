"""Minimal Synology DSM WebAPI client — enough to delete a finished torrent.

Only three things are needed: find the Download Station task behind a torrent,
resolve where its payload really sits, and remove both. Everything else DSM can
do is out of scope.

Deletion is permanent — SYNO.FileStation.Delete does not route through #recycle —
so no call here runs without the double confirmation in hr_delete.py.

Login is per-operation and never retried in a loop: repeated DSM login failures
get the container IP auto-blocked (see CLAUDE.md).
"""

import json

import config
import httpx

_TIMEOUT = 20


class DsmError(RuntimeError):
    pass


def configured() -> bool:
    return bool(config.DSM_URL and config.DSM_USERNAME and config.DSM_PASSWORD)


class Dsm:
    """Async context manager holding one DSM session."""

    def __init__(self):
        self._client: httpx.AsyncClient | None = None
        self._sid = ""

    async def __aenter__(self) -> "Dsm":
        self._client = httpx.AsyncClient(base_url=config.DSM_URL, timeout=_TIMEOUT)
        r = await self._client.post(
            "/webapi/auth.cgi",
            data={
                "api": "SYNO.API.Auth",
                "version": "3",
                "method": "login",
                "account": config.DSM_USERNAME,
                "passwd": config.DSM_PASSWORD,
                "session": "torrentwatch",
                "format": "sid",
            },
        )
        body = r.json()
        if not body.get("success"):
            await self._client.aclose()
            raise DsmError(f"DSM login failed: {body.get('error')}")
        self._sid = body["data"]["sid"]
        return self

    async def __aexit__(self, *exc):
        try:
            await self._client.post(
                "/webapi/auth.cgi",
                data={
                    "api": "SYNO.API.Auth",
                    "version": "1",
                    "method": "logout",
                    "session": "torrentwatch",
                    "_sid": self._sid,
                },
            )
        except httpx.HTTPError:
            pass
        await self._client.aclose()

    async def _call(self, endpoint: str, **params) -> dict:
        params["_sid"] = self._sid
        r = await self._client.post(f"/webapi/{endpoint}", data=params)
        body = r.json()
        if not body.get("success"):
            raise DsmError(f"{params.get('api')}.{params.get('method')}: {body.get('error')}")
        return body.get("data") or {}

    async def list_tasks(self) -> list[dict]:
        data = await self._call(
            "DownloadStation/task.cgi",
            api="SYNO.DownloadStation.Task",
            version="1",
            method="list",
            additional="detail",
        )
        return data.get("tasks") or []

    async def delete_task(self, task_id: str):
        await self._call(
            "DownloadStation/task.cgi",
            api="SYNO.DownloadStation.Task",
            version="1",
            method="delete",
            id=task_id,
            force_complete="false",
        )

    async def stat(self, share_path: str) -> dict | None:
        """Resolve a share-relative path to its real path + size, or None if gone."""
        data = await self._call(
            "entry.cgi",
            api="SYNO.FileStation.List",
            version="2",
            method="getinfo",
            path=json.dumps([share_path]),
            additional=json.dumps(["real_path", "size"]),
        )
        files = data.get("files") or []
        if not files or files[0].get("code"):
            return None
        f = files[0]
        add = f.get("additional") or {}
        return {
            "path": f.get("path"),
            "real_path": add.get("real_path"),
            "size": add.get("size"),
            "isdir": f.get("isdir"),
        }

    async def delete_path(self, share_path: str):
        await self._call(
            "entry.cgi",
            api="SYNO.FileStation.Delete",
            version="2",
            method="delete",
            path=json.dumps([share_path]),
            recursive="true",
        )


def task_payload_path(task: dict) -> str:
    """Share-relative path of a task's payload: /<destination>/<title>."""
    dest = ((task.get("additional") or {}).get("detail") or {}).get("destination") or ""
    return "/" + "/".join(p for p in (dest.strip("/"), task.get("title") or "") if p)


def find_task(tasks: list[dict], title: str, torrent_name: str) -> dict | None:
    """Match a bearbit row to its DS task.

    `title` is the torrent's own name, which DS reports verbatim. `torrent_name`
    is the filename apply_fix dropped into the watch folder, which DS echoes back
    as `uri` — the stronger key, so it wins.
    """
    for t in tasks:
        uri = ((t.get("additional") or {}).get("detail") or {}).get("uri") or ""
        if torrent_name and uri == torrent_name:
            return t
    for t in tasks:
        if (t.get("title") or "") == title:
            return t
    return None


if __name__ == "__main__":
    _tasks = [
        {
            "id": "dbid_1",
            "title": "MIAA-362 Eimi Fukada [ Destroyed ]",
            "additional": {"detail": {"destination": "home/Torrents_Download", "uri": "x.torrent"}},
        },
        {
            "id": "dbid_2",
            "title": "Troy - Director's Cut (2004).mkv",
            "additional": {"detail": {"destination": "Movies/Western", "uri": "Troy.mkv"}},
        },
    ]
    assert find_task(_tasks, "nope", "x.torrent")["id"] == "dbid_1"
    assert find_task(_tasks, "Troy - Director's Cut (2004).mkv", "")["id"] == "dbid_2"
    # a wrong filename must not silently fall through to a title that also mismatches
    assert find_task(_tasks, "nope", "nope.torrent") is None
    assert task_payload_path(_tasks[0]) == "/home/Torrents_Download/MIAA-362 Eimi Fukada [ Destroyed ]"
    assert task_payload_path(_tasks[1]) == "/Movies/Western/Troy - Director's Cut (2004).mkv"
    # a task with no destination must not produce a path that deletes a share root
    assert task_payload_path({"title": "x", "additional": {}}) == "/x"
    print("dsm self-check OK")
