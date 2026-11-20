"""The deferred link pass: what is counted and what is not written twice.
That links resolve, and one out of the selection is counted, is tested
through the imports in ``imports_test``."""

import pytest

from app.core.relationships import RelationshipType
from app.core.search import SearchEntityType
from app.models.platform.guild import CommunityRole
from app.services.import_engine.links import LinkCollector
from app.services.tenant import relationships as relationships_service
from app.services.tenant.relationships import Endpoint
from app.testing.factories import create_task


def test_a_ref_nothing_named_registers_nothing():
    """A task with no external ref is a task nothing can point at — not an
    error, and not a key in the map."""
    collector = LinkCollector()
    collector.register(None, SearchEntityType.task, 1)
    collector.register("", SearchEntityType.task, 2)
    collector.register("jira:ACME-1", SearchEntityType.task, None)
    collector.link("jira:ACME-1", RelationshipType.depends_on, "jira:ACME-2")
    assert collector.pending_count == 1


def test_a_link_missing_an_end_is_not_a_link():
    collector = LinkCollector()
    collector.link(None, RelationshipType.depends_on, "jira:ACME-2")
    collector.link("jira:ACME-1", RelationshipType.depends_on, None)
    assert collector.pending_count == 0


async def test_a_ref_pointing_at_itself_writes_nothing(session, acting_user):
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    task = await create_task(session, a.project, title="Sand the sill")

    collector = LinkCollector()
    collector.register("jira:ACME-1", SearchEntityType.task, task.id)
    collector.link("jira:ACME-1", RelationshipType.related_to, "jira:ACME-1")

    resolution = await collector.resolve(session, created_by=a.user.id)
    assert (resolution.created, resolution.unresolved) == (0, 1)


async def test_an_edge_already_there_is_counted_as_a_duplicate(session, acting_user):
    """Re-asserting an edge is the answer already being correct, not a
    second row and not a failure."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    one = await create_task(session, a.project, title="Hang the gate")
    two = await create_task(session, a.project, title="Oil the hinge")

    collector = LinkCollector()
    collector.register("a", SearchEntityType.task, one.id)
    collector.register("b", SearchEntityType.task, two.id)
    collector.link("a", RelationshipType.related_to, "b")
    collector.link("a", RelationshipType.related_to, "b")

    resolution = await collector.resolve(session, created_by=a.user.id)
    assert (resolution.created, resolution.duplicate) == (1, 1)


async def test_resolving_twice_does_not_write_twice(session, acting_user):
    """The collection is emptied by the pass, so a second call is a no-op
    rather than a second set of edges."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    one = await create_task(session, a.project, title="Set the post")
    two = await create_task(session, a.project, title="String the wire")

    collector = LinkCollector()
    collector.register("a", SearchEntityType.task, one.id)
    collector.register("b", SearchEntityType.task, two.id)
    collector.link("a", RelationshipType.part_of, "b")

    first = await collector.resolve(session, created_by=a.user.id)
    second = await collector.resolve(session, created_by=a.user.id)
    assert first.created == 1
    assert (second.created, second.unresolved, second.duplicate) == (0, 0, 0)


async def test_two_things_claiming_one_name_keeps_the_first(session, acting_user):
    """A repeated ref is the source's ambiguity. Keeping the earlier one at
    least makes a re-run land in the same place."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    first_task = await create_task(session, a.project, title="Lay the course")
    second_task = await create_task(session, a.project, title="Point the joints")
    other = await create_task(session, a.project, title="Clean the tools")

    collector = LinkCollector()
    collector.register("dup", SearchEntityType.task, first_task.id)
    collector.register("dup", SearchEntityType.task, second_task.id)
    collector.register("other", SearchEntityType.task, other.id)
    collector.link("dup", RelationshipType.related_to, "other")

    await collector.resolve(session, created_by=a.user.id)
    assert await relationships_service.related_ids(
        session,
        Endpoint(kind=SearchEntityType.task, id=first_task.id),
        relationship_type=RelationshipType.related_to,
        other_kind=SearchEntityType.task,
    ) == [other.id]


@pytest.mark.parametrize(
    "raw,expected",
    [
        (["Priority", "Team"], frozenset({"Priority", "Team"})),
        (None, frozenset()),
        ("Priority", frozenset()),
        (["Priority", 3, "", None], frozenset({"Priority"})),
    ],
)
def test_unticked_properties_are_read_back_defensively(raw, expected):
    """They round-tripped through a request into the job's params, so only a
    list of names counts."""
    from app.services.import_engine.context import excluded_property_names

    assert excluded_property_names(raw) == expected


def test_a_confluence_page_link_is_named_by_its_page_id_on_its_own_site():
    from app.services.import_engine.links import confluence_page_ref

    site = "https://acme.atlassian.net"
    assert confluence_page_ref(f"{site}/wiki/spaces/DOCS/pages/12/Guide", site) == (
        "confluence:12"
    )
    assert confluence_page_ref(
        f"{site}/wiki/pages/viewpage.action?pageId=34", site
    ) == ("confluence:34")
    # Another site's page, or not a page at all, is no ref.
    assert (
        confluence_page_ref("https://other.atlassian.net/wiki/spaces/X/pages/1", site)
        is None
    )
    assert confluence_page_ref(f"{site}/browse/ACME-1", site) is None


def test_a_link_to_a_page_that_came_over_becomes_a_mention_of_it():
    from app.services.import_engine.links import rewrite_page_links

    text = (
        "See [the guide](https://acme.atlassian.net/wiki/spaces/D/pages/2/Guide), "
        "[https://acme.atlassian.net/wiki/spaces/D/pages/2](<https://acme.atlassian.net/wiki/spaces/D/pages/2>) "
        "and [elsewhere](https://example.com)."
    )

    def resolve(url):
        return (7, "Guide") if "/pages/2" in url else None

    assert rewrite_page_links(text, resolve) == (
        "See #wiki_page[the guide](7), #wiki_page[Guide](7) and "
        "[elsewhere](https://example.com)."
    )
