"""Comments on tasks and files, each written by its author on their own
request session, so the change log says who commented and the activity feed
has the week's conversation to show."""

from __future__ import annotations

from app.api.deps import establish_guild_access
from app.db import cohorts
from app.models.tenant._mixins import ActorKind
from app.models.tenant.comment import Comment
from seed.common import Community

#: Each comment names the ``task`` or ``file`` it is on, by title.
COMMENTS: dict[str, list[dict]] = {
    "primary": [
        {
            "author": "Thorn Ironforge",
            "task": "Defeat Strahd von Zarovich",
            "content": "We need the Sunsword AND the Holy Symbol before attempting this.",
        },
        {
            "author": "Elara Moonwhisper",
            "task": "Defeat Strahd von Zarovich",
            "content": "I can prepare Daylight and Greater Restoration. We should also "
            "stock up on holy water.",
        },
        {
            "author": "Dungeon Master",
            "task": "Defeat Strahd von Zarovich",
            "content": "Remember: Strahd can retreat to his coffin. You need to find it first.",
        },
        {
            "author": "Admin User",
            "task": "Rescue Gundren Rockseeker",
            "content": "Last seen heading to Cragmaw Castle with the map.",
        },
        {
            "author": "Thorn Ironforge",
            "task": "Clear the Redbrand Hideout",
            "content": "Completed! The party found Glasstaff's letters from the Black Spider.",
        },
        {
            "author": "Vex Shadowstep",
            "task": "Disable the castle traps",
            "content": "I'll need thieves' tools and a lot of patience. DC 15+ on most of these.",
        },
        {
            "author": "Seraphina Dawnlight",
            "task": "Find the Heart of Sorrow",
            "content": "The crystal heart is somewhere high in the castle towers. I can "
            "sense its dark energy.",
        },
        {
            "author": "Dungeon Master",
            "task": "Write critical hit tables",
            "content": "Playtest feedback from session 2: slashing crits feel too "
            "strong at low levels.",
        },
        {
            "author": "Dungeon Master",
            "file": "Campaign Setting: The Land of Barovia",
            "content": "Don't forget — Barovia is a demiplane, no escape without defeating Strahd.",
        },
        {
            "author": "Elara Moonwhisper",
            "file": "Tarokka Card Reading Results",
            "content": "We should head to the Amber Temple first. The Sunsword is our "
            "highest priority.",
        },
    ],
    "starforge": [
        {
            "author": "Kael Windrunner",
            "task": "Repair the FTL drive core",
            "content": "The plasma leak is worse than expected. We might need to "
            "cannibalize the Icarus VII.",
        },
        {
            "author": "Admin User",
            "task": "Repair the FTL drive core",
            "content": "Do it. The Icarus was going to be decommissioned anyway.",
        },
        {
            "author": "Finley Goldtongue",
            "task": "Negotiate passage through Krellix space",
            "content": "I have a contact in the Diplomat caste. We'll need a gift — "
            "something they don't have.",
        },
        {
            "author": "Aurelia Brightshield",
            "task": "Investigate the distress signal from Sector 7G",
            "content": "Could be a trap. The Crimson Syndicate uses fake distress beacons.",
        },
        {
            "author": "Vex Shadowstep",
            "task": "Infiltrate Station Omega",
            "content": "I can forge the ID badges. Kael, can you loop the security feeds?",
        },
        {
            "author": "Kael Windrunner",
            "task": "Infiltrate Station Omega",
            "content": "Already on it. I'll need 30 minutes once we're inside.",
        },
        {
            "author": "Elara Moonwhisper",
            "file": "Setting Bible: The Exodus Protocol",
            "content": "We should add a section on the cryosleep rotation schedule — it "
            "came up last session.",
        },
    ],
    "tides": [
        {
            "author": "Thorn Ironforge",
            "task": "Repair the hull after the kraken attack",
            "content": "The port breach is the worst. We'll need to beach her to fix "
            "the keel properly.",
        },
        {
            "author": "Kael Windrunner",
            "task": "Repair the hull after the kraken attack",
            "content": "I know a cove on the west side of Port Havoc. Sheltered and private.",
        },
        {
            "author": "Finley Goldtongue",
            "task": "Decipher the Leviathan Map",
            "content": "The fence wants 50 doubloons for the translator. Steep but worth it.",
        },
        {
            "author": "Admin User",
            "task": "Decipher the Leviathan Map",
            "content": "I can cover the cost. Let's not haggle when we're this close.",
        },
        {
            "author": "Dungeon Master",
            "task": "Evade the HMS Vengeance",
            "content": "Blackwood knows you're in Port Havoc. You have maybe 3 days "
            "before she arrives.",
        },
        {
            "author": "Aurelia Brightshield",
            "task": "Negotiate with the Coral Elves",
            "content": "The Coral Elves respect strength but value honor. We should "
            "approach openly, not sneak.",
        },
        {
            "author": "Finley Goldtongue",
            "task": "Forge letters of marque",
            "content": "I've got the royal seal impression from when we raided the "
            "Ironclad. Just need the right paper.",
        },
        {
            "author": "Seraphina Dawnlight",
            "task": "Defeat the Leviathan guardian",
            "content": "The Tide Mother has granted me a vision. The guardian is bound, "
            "not willing. Perhaps we can free it instead of fighting.",
        },
        {
            "author": "Dungeon Master",
            "file": "Intelligence Report: Admiral Blackwood",
            "content": "Updated: Ironclad confirmed sunk. Blackwood is furious. Expect "
            "retaliation.",
        },
        {
            "author": "Thorn Ironforge",
            "file": "Crew Manifest: The Crimson Maiden",
            "content": "We lost 6 crew in the kraken fight. Need to update the manifest "
            "and recruit in Port Havoc.",
        },
    ],
}


async def seed(c: Community) -> None:
    """Write the comments in order, after the community's content is
    committed (an author's session cannot see it before) and before anything
    is archived (archived content takes no comments)."""
    for d in COMMENTS[c.key]:
        author = c.users[d["author"]]
        session = cohorts.request_sessionmaker(c.guild.id)()
        try:
            account = await session.merge(author, load=False)
            await establish_guild_access(session, account, c.guild.id)
            comment = Comment(
                content=d["content"],
                created_by=author.id,
                created_by_kind=ActorKind.member,
                task_id=c.tasks[d["task"]].id if "task" in d else None,
                file_id=c.files[d["file"]].id if "file" in d else None,
            )
            session.add(comment)
            await session.commit()
            c.ids["comments"].append(comment.id)
        finally:
            await session.close()
