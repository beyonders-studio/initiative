"""The shared data-job dispatcher's module-level pieces: shutdown stops every
dispatcher's jobs. Claiming, slots and the sweep are tested through imports."""

import asyncio


from app.services import data_jobs
from app.services.export import worker as export_worker
from app.services.import_engine import worker as import_worker


async def test_cancel_running_jobs_stops_imports_and_exports(monkeypatch):
    render = asyncio.create_task(asyncio.sleep(3600))
    apply = asyncio.create_task(asyncio.sleep(3600))
    monkeypatch.setitem(export_worker.jobs.running, (1, 1), ("render", render))
    monkeypatch.setitem(import_worker.jobs.running, (2, 2), ("apply", apply))

    await data_jobs.cancel_running_jobs()

    assert render.cancelled() and apply.cancelled()


async def test_a_long_step_beats_while_it_runs():
    beats: list[int] = []

    async def beat() -> None:
        beats.append(1)

    async def download() -> str:
        await asyncio.sleep(0.1)
        return "the whole file"

    result = await data_jobs.while_beating(download(), beat, every=0.01)

    assert result == "the whole file"
    assert beats


async def test_a_beat_that_raises_stops_the_step_in_its_place():
    import pytest

    stopped = asyncio.Event()

    async def beat() -> None:
        raise LookupError("cancelled")

    async def download() -> None:
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            stopped.set()
            raise

    with pytest.raises(LookupError):
        await data_jobs.while_beating(download(), beat, every=0.01)
    assert stopped.is_set()
