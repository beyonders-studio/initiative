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


async def test_a_beat_under_way_when_the_step_ends_finishes_first():
    """The caller gets its session back only once a beat that was under way
    has finished, not while a cancelled one is still unwinding."""
    finished: list[int] = []

    async def beat() -> None:
        await asyncio.sleep(0.1)
        finished.append(1)

    async def build() -> str:
        await asyncio.sleep(0.03)
        return "built"

    assert await data_jobs.while_beating(build(), beat, every=0.01) == "built"
    assert finished == [1]


async def test_work_that_must_finish_ends_before_a_beats_error():
    """Work in a thread cannot be stopped, so with ``finish`` it runs to its
    end and the beat's error comes after it."""
    import time

    import pytest

    uploaded: list[int] = []

    def upload() -> None:
        time.sleep(0.05)
        uploaded.append(1)

    async def beat() -> None:
        raise LookupError("taken over")

    with pytest.raises(LookupError):
        await data_jobs.while_beating(
            asyncio.to_thread(upload), beat, every=0.01, finish=True
        )
    assert uploaded == [1]
