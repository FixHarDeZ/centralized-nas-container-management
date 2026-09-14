from pathlib import Path

from app import render


def _flags(name: str) -> list[str]:
    cmd = render.build_command(Path(name), Path("a.wav"), Path("out.mp4"))
    return cmd[: cmd.index("-i", cmd.index("-i") + 1)]


def test_a_clip_backdrop_is_looped_as_a_stream():
    assert "-stream_loop" in _flags("backdrop.mp4")


def test_a_still_backdrop_gets_loop_and_a_framerate():
    # `-stream_loop -1` on an image reads one frame and produces a one-frame
    # video. build() only notices at the end, after the Story is already voiced.
    flags = _flags("backdrop.png")
    assert "-stream_loop" not in flags
    assert flags[flags.index("-loop") + 1] == "1"
    assert "-framerate" in flags


def test_cancelling_the_task_kills_the_child_process():
    # `/cancel` during a render used to be a lie: to_thread cannot stop ffmpeg.
    # render.run is an asyncio subprocess so cancellation reaches the child.
    import asyncio
    import time

    async def scenario():
        task = asyncio.create_task(render.run("sleep", "30"))
        await asyncio.sleep(0.1)
        task.cancel()
        started = time.monotonic()
        try:
            await task
        except asyncio.CancelledError:
            pass
        return time.monotonic() - started

    assert asyncio.run(scenario()) < 2.0


def test_a_failing_tool_reports_its_stderr():
    import asyncio

    async def scenario():
        await render.run("sh", "-c", "echo boom >&2; exit 3")

    try:
        asyncio.run(scenario())
    except RuntimeError as error:
        assert "exited 3" in str(error) and "boom" in str(error)
    else:
        raise AssertionError("expected RuntimeError")
