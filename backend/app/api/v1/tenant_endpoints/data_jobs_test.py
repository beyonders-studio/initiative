from httpx import AsyncClient

from app.models.platform.guild import CommunityRole
from app.models.tenant.data_job import DataJobStatus
from app.services.storage import get_guild_storage
from app.testing import create_export_job, create_import_job


async def test_jobs_list_both_directions_newest_first(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(guild_role=CommunityRole.admin)
    exported = await create_export_job(session, a.guild, a.user)
    imported = await create_import_job(session, a.guild, a.user)

    jobs = (await client.get(a.g("/data-jobs/"), headers=a.headers)).json()

    assert [(job["id"], job["direction"]) for job in jobs] == [
        (imported.id, "import"),
        (exported.id, "export"),
    ]


async def test_a_job_is_acted_on_only_by_its_own_direction(
    client: AsyncClient, acting_user, session
):
    """An import's id names no export to download, and an export's names no
    import to cancel or confirm."""
    a = await acting_user(guild_role=CommunityRole.superadmin)
    imported = await create_import_job(
        session, a.guild, a.user, status=DataJobStatus.staged
    )
    exported = await create_export_job(
        session,
        a.guild,
        a.user,
        status=DataJobStatus.done,
        file_ref="exports/held.pdf",
        initiative_ids=[],
    )

    download = await client.get(
        a.g(f"/exports/jobs/{imported.id}/download"), headers=a.headers
    )
    cancel = await client.delete(a.g(f"/imports/jobs/{exported.id}"), headers=a.headers)
    confirm = await client.post(
        a.g(f"/imports/jobs/{exported.id}/confirm"), headers=a.headers, json={}
    )

    assert (download.status_code, download.json()["detail"]) == (
        404,
        "EXPORT_JOB_NOT_FOUND",
    )
    for resp in (cancel, confirm):
        assert (resp.status_code, resp.json()["detail"]) == (
            404,
            "IMPORT_JOB_NOT_FOUND",
        )


async def test_a_moved_export_downloads_by_the_name_it_was_rendered_with(
    client: AsyncClient, acting_user, session
):
    """An export from before the jobs shared one table has a new id, while
    its stored file still carries the one it was rendered under."""
    a = await acting_user(guild_role=CommunityRole.member)
    key = "exports/7-Q3 Report.pdf"
    get_guild_storage(a.guild.id).write(
        key, b"%PDF-fake", content_type="application/pdf"
    )
    job = await create_export_job(
        session,
        a.guild,
        a.user,
        status=DataJobStatus.done,
        file_ref=key,
        initiative_ids=[],
    )
    assert job.id != 7

    download = await client.get(
        a.g(f"/exports/jobs/{job.id}/download"), headers=a.headers
    )

    assert download.status_code == 200
    assert "Q3%20Report.pdf" in download.headers["content-disposition"]
