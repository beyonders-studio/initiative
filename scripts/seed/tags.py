"""Tags: each community's labels, made before anything that carries one."""

from __future__ import annotations

from app.models.tenant.tag import Tag
from seed.common import Community

#: ``(name, colour)`` per community.
TAGS: dict[str, list[tuple[str, str]]] = {
    "primary": [
        ("quest", "#EF4444"),
        ("NPC", "#8B5CF6"),
        ("lore", "#F59E0B"),
        ("combat", "#DC2626"),
        ("roleplay", "#3B82F6"),
        ("exploration", "#10B981"),
        ("puzzle", "#F97316"),
        ("boss fight", "#991B1B"),
        ("side quest", "#6366F1"),
        ("items/loot", "#D97706"),
    ],
    "starforge": [
        ("main quest", "#EF4444"),
        ("side quest", "#6366F1"),
        ("engineering", "#0EA5E9"),
        ("diplomacy", "#10B981"),
        ("combat", "#DC2626"),
        ("exploration", "#8B5CF6"),
        ("NPC", "#F59E0B"),
        ("loot", "#D97706"),
        ("survival", "#059669"),
        ("stealth", "#475569"),
    ],
    "tides": [
        ("main quest", "#EF4444"),
        ("side quest", "#6366F1"),
        ("naval combat", "#0EA5E9"),
        ("NPC", "#F59E0B"),
        ("exploration", "#10B981"),
        ("loot", "#D97706"),
        ("ship upgrades", "#8B5CF6"),
        ("stealth", "#475569"),
        ("boss fight", "#991B1B"),
        ("diplomacy", "#059669"),
    ],
}


async def seed(c: Community) -> None:
    for name, color in TAGS[c.key]:
        c.tags[name] = Tag(name=name, color=color)
        c.session.add(c.tags[name])
        await c.session.flush()
        c.ids["tags"].append(c.tags[name].id)
