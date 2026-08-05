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
_DELETE_TIMEOUT = 300


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
        try:
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
        except httpx.HTTPError as e:
            await self._client.aclose()
            raise DsmError(f"DSM unreachable: {e}") from e
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

    async def _call(self, endpoint: str, timeout: float | None = None, **params) -> dict:
        params["_sid"] = self._sid
        try:
            # Anything httpx raises must come back out as DsmError: the callback
            # poller swallows stray exceptions, so a bare timeout mid-delete would
            # leave the user staring at a button that silently did something.
            r = await self._client.post(f"/webapi/{endpoint}", data=params, timeout=timeout or _TIMEOUT)
        except httpx.HTTPError as e:
            raise DsmError(f"{params.get('api')}.{params.get('method')}: {e}") from e
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
        # DS reports per-id failures inside data with success=true at the top level
        # ([{"error": 544, "id": "..."}]), so _call alone would call a no-op a win.
        data = await self._call(
            "DownloadStation/task.cgi",
            api="SYNO.DownloadStation.Task",
            version="1",
            method="delete",
            id=task_id,
            force_complete="false",
        )
        err = next((r.get("error") for r in (data if isinstance(data, list) else []) if r.get("error")), None)
        if err is None:
            return
        # A missing id answers 544 here, and "the task is already gone" is the
        # outcome both callers wanted — but 544 reads as a generic removal
        # failure, so ask the task list instead of trusting the code.
        if any(t.get("id") == task_id for t in await self.list_tasks()):
            raise DsmError(f"SYNO.DownloadStation.Task.delete: {err} ({task_id})")

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
        try:
            await self._call(
                "entry.cgi",
                # method=delete is the blocking variant, and a recursive multi-GB
                # folder outlives the normal timeout.
                timeout=_DELETE_TIMEOUT,
                api="SYNO.FileStation.Delete",
                version="2",
                method="delete",
                path=json.dumps([share_path]),
                recursive="true",
            )
        except DsmError as e:
            # 408 = no such file. Download Station may already have taken the
            # payload out with the task, and "gone" is the outcome we asked for.
            if "408" not in str(e):
                raise


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

    import asyncio

    class _Fake(Dsm):
        def __init__(self, err):
            self._err = err

        async def _call(self, endpoint, timeout=None, **params):
            raise DsmError(self._err)

    # "already gone" is the outcome we wanted; any other DSM error must surface
    asyncio.run(_Fake("SYNO.FileStation.Delete: {'code': 408}").delete_path("/x"))
    try:
        asyncio.run(_Fake("SYNO.FileStation.Delete: {'code': 407}").delete_path("/x"))
        raise AssertionError("non-408 delete error must propagate")
    except DsmError:
        pass

    class _FakeData(Dsm):
        def __init__(self, data, left=()):
            self._data, self._left = data, left

        async def _call(self, endpoint, timeout=None, **params):
            return {"tasks": list(self._left)} if params["method"] == "list" else self._data

    # a per-id failure hides behind success=true, so delete_task has to read it —
    # but only a task still in the list is a real failure
    asyncio.run(_FakeData([{"id": "dbid_1"}]).delete_task("dbid_1"))
    asyncio.run(_FakeData([{"error": 544, "id": "dbid_1"}]).delete_task("dbid_1"))
    try:
        asyncio.run(_FakeData([{"error": 544, "id": "dbid_1"}], [{"id": "dbid_1"}]).delete_task("dbid_1"))
        raise AssertionError("delete error on a task that is still there must propagate")
    except DsmError:
        pass
    print("dsm self-check OK")
