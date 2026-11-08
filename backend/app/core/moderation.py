"""What can be reported, who handles it, and how a report is settled.

A **report** is what a person sends when they meet something wrong. Where it
goes is decided here and nowhere else — the client sends the same thing from
every surface, and the venue is derived from what was reported:

> A target that resolves to an initiative is that initiative's to moderate.
> Everything else is the platform's.

What may be reported is derived too. Community content is
:class:`~app.core.search.SearchEntityType`, which is already built from
:class:`~app.core.tools.Tool` plus the things that live inside one — so a new
tool becomes reportable with no edit here. Only the identity plane, which has
no tool behind it, is stated.
"""

from __future__ import annotations

from enum import Enum

from app.core.search import SearchEntityType
from app.core.tools import plural_of


class PlatformReportTarget(str, Enum):
    """Things a report can name that live outside any community.

    Identity and the platform plane. Adding a ``Tool`` never adds one of these,
    so stating them drifts against nothing.
    """

    user_profile = "user_profile"
    username = "username"
    avatar = "avatar"
    decoration = "decoration"
    directory_listing = "directory_listing"
    guild = "guild"
    #: A marketplace listing, reported from its page or from an installed
    #: plug-in. The catalog belongs to whoever runs the server, so its operators
    #: handle it.
    marketplace_listing = "marketplace_listing"

    # Direct messages are absent because **private conversations are not
    # moderated**. The server holds ciphertext and no key to it, so there is
    # nothing a report could show anybody — the same reason ``dm_transport``
    # has nothing to configure about retention, moderation or search.
    #
    # This is not a gap waiting to be filled. A member's recourse in a private
    # conversation is to block or ignore, which does not need us to read it.


#: Which **publicly readable** relation a platform target's id is checked
#: against. Not the underlying table: ``public.users`` is own-row for a
#: platform-tier session, and ``public.user_profiles`` is the projection of it
#: that a profile page already reads. ``public.guilds`` is itself scoped by
#: RLS to what the reader may see. ``public.marketplace_listings`` is the
#: catalog every platform tier already browses.
#:
#: Asking through these is what makes a hidden row and a missing row answer
#: the same way — the check runs as the reporter, on the reporter's session,
#: like the community half does. ``core/registry_coverage_test.py`` holds this
#: and the enum in step, so a member added later cannot ship unresolvable.
PLATFORM_TARGET_RELATION: dict[PlatformReportTarget, str] = {
    PlatformReportTarget.user_profile: "user_profiles",
    PlatformReportTarget.username: "user_profiles",
    PlatformReportTarget.avatar: "user_profiles",
    PlatformReportTarget.decoration: "user_profiles",
    PlatformReportTarget.directory_listing: "guilds",
    PlatformReportTarget.guild: "guilds",
    PlatformReportTarget.marketplace_listing: "marketplace_listings",
}


class ReportVenue(str, Enum):
    """Who handles a report."""

    #: The operations guild's moderation project, as an intake case.
    platform = "platform"
    #: A row in the initiative the target belongs to.
    initiative = "initiative"


class ReportReason(str, Enum):
    """Why somebody is reporting. Closed, so it can be counted and filtered."""

    spam = "spam"
    harassment = "harassment"
    hate = "hate"
    violence = "violence"
    sexual_content = "sexual_content"
    self_harm = "self_harm"
    illegal = "illegal"
    misinformation = "misinformation"
    other = "other"


class ReportOutcome(str, Enum):
    """How a report was settled. Every member closes it."""

    #: Looked at; nothing to do.
    dismissed = "dismissed"
    #: The reported thing was taken down.
    content_removed = "content_removed"
    #: Handled with the person.
    member_warned = "member_warned"
    #: Not this community's to settle — opens a platform case.
    escalated = "escalated"
    #: Handed to the platform hidden: a platform case, and the reported thing
    #: held where it is until the platform releases it (``app.db.holds``).
    held = "held"


class LegalBasis(str, Enum):
    """The law something is held, or reported, under. Closed, so cases can be
    counted by it."""

    child_safety = "child_safety"
    terrorism = "terrorism"
    intellectual_property = "intellectual_property"
    fraud = "fraud"
    privacy = "privacy"
    other = "other"


class RemovalReason(str, Enum):
    """Why a moderator took something down. Every reason a report can give,
    and two that only a community's own rules give."""

    spam = "spam"
    harassment = "harassment"
    hate = "hate"
    violence = "violence"
    sexual_content = "sexual_content"
    self_harm = "self_harm"
    illegal = "illegal"
    misinformation = "misinformation"
    other = "other"
    #: Fine in itself, in the wrong place.
    off_topic = "off_topic"
    #: Against a rule this community set for itself.
    community_rule = "community_rule"


class ModerationAct(str, Enum):
    """What a moderator did, as the moderation log records it."""

    #: Took something down: a comment to a tombstone, anything else to the
    #: trash.
    remove = "remove"
    #: Put back what a removal took down.
    restore = "restore"
    #: Closed a thread to new comments. Its owner can't reopen it.
    lock_comments = "lock_comments"
    unlock_comments = "unlock_comments"
    #: Took every reaction off something.
    clear_reactions = "clear_reactions"
    #: Told whoever wrote something that it crossed a line.
    warn = "warn"


class HoldReason(str, Enum):
    """Why content is held."""

    #: Someone with the standing to ask — a court, a regulator, the police —
    #: asked for it to be kept.
    legal_request = "legal_request"
    #: It is, or may be, unlawful. A hold for this names its legal basis.
    illegal_content = "illegal_content"


class HoldVia(str, Enum):
    """Who placed a hold."""

    #: A moderator of the community the content is in.
    community = "community"
    #: A platform moderator, under a ``moderate`` grant on the community.
    platform = "platform"


class HoldRelease(str, Enum):
    """How a hold ended. Only the platform releases one."""

    #: Back as it was.
    restore = "restore"
    #: Taken down: to the trash.
    remove = "remove"
    #: Destroyed. The one path that deletes held content.
    purge = "purge"


def removal_reason_for(reason: ReportReason) -> RemovalReason:
    """The removal reason a report's own reason becomes."""
    return RemovalReason(reason.value)


def target_table(target: SearchEntityType) -> str:
    """The guild-schema table a community target's ids point at."""
    return plural_of(target.value)


def venue_for(target: SearchEntityType | PlatformReportTarget) -> ReportVenue:
    """Who handles a report about ``target``.

    Derived rather than tabulated: a community target is one whose table
    resolves to an initiative, which is the same registry
    (``app.db.initiative_rls.INITIATIVE_PATHS``) the RLS policies are rendered
    from. So a target's venue and its access gate cannot disagree, and a
    guild-level thing — a tag, which belongs to no initiative — falls to the
    platform without being named here.
    """
    if isinstance(target, PlatformReportTarget):
        return ReportVenue.platform

    from app.db.initiative_rls import INITIATIVE_PATHS

    if target_table(target) in INITIATIVE_PATHS:
        return ReportVenue.initiative
    return ReportVenue.platform


def parse_target(raw: str) -> SearchEntityType | PlatformReportTarget:
    """The target type a client named, or ``ValueError``."""
    try:
        return SearchEntityType(raw)
    except ValueError:
        return PlatformReportTarget(raw)
