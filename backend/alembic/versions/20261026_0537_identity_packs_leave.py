"""The profile packs about who somebody is leave the catalog, and every record of them.

Pride, Disability, Faith and Belief, Black heritage, First Nations,
Multicultural and Family are no longer shipped. Each of them was about a
protected characteristic, so taking them off the shelf is not enough: an
account that took one, or wore a piece of one, is a record of that
characteristic. This removes the record too.

* the listings and their versions, rather than leaving them withdrawn;
* every account's grants from these packs, in ``user_decorations``;
* any of their pieces a profile is wearing, from ``users.profile_decorations``.

The pieces are named here rather than read from the listings, because the
listings this revision deletes are the only other place that names them.

Revision ID: 20261026_0537
Revises: 20261022_0536
Create Date: 2026-10-26
"""

import sqlalchemy as sa
from alembic import op

revision = "20261026_0537"
down_revision = "20261022_0536"
branch_labels = None
depends_on = None

#: ``listing uid -> the decorations it granted``.
_PACKS: dict[str, tuple[str, ...]] = {
    # Pride
    "5MT2WPY8CHRK61": (
        "pride.parade",
        "pride.spectrum",
        "pride.heart",
        "pride.nonbinaryflag",
        "pride.nonbinaryring",
        "pride.nonbinaryheart",
        "pride.transflag",
        "pride.transring",
        "pride.transheart",
        "pride.lesbianflag",
        "pride.lesbianring",
        "pride.lesbianheart",
        "pride.gayflag",
        "pride.gayring",
        "pride.gayheart",
        "pride.biflag",
        "pride.biring",
        "pride.biheart",
        "pride.aceflag",
        "pride.acering",
        "pride.aceheart",
        "pride.polyflag",
        "pride.polyring",
        "pride.polyheart",
    ),
    # Disability
    "P9GJ4WXT7NCB25": (
        "disability.pride",
        "disability.stripes",
        "disability.braille",
        "disability.neurodivergent",
        "disability.autistic",
        "disability.blind",
        "disability.deaf",
        "disability.wheelchair",
        "disability.chronicpain",
        "disability.diabetes",
        "disability.mentalhealth",
        "disability.servicedog",
        "disability.spoon",
        "disability.mobility",
    ),
    # Faith and Belief
    "K4TJ7WQ2ND8MRB": (
        "faith.skyline",
        "faith.lights",
        "faith.doors",
        "faith.circle",
        "faith.interlace",
        "faith.cross",
        "faith.crescent",
        "faith.starofdavid",
        "faith.om",
        "faith.dharmawheel",
        "faith.khanda",
        "faith.taijitu",
        "faith.ninepointedstar",
        "faith.ahimsa",
        "faith.torii",
        "faith.pentacle",
    ),
    # Black heritage
    "5HB2CQZ9FN6RTW": (
        "heritage.kente",
        "heritage.cowries",
        "heritage.fist",
        "heritage.panafrican",
        "heritage.flag",
        "heritage.crown",
        "heritage.northstar",
    ),
    # First Nations
    "6P5XW9RK2ZTQ4B": (
        "firstnations.weave",
        "firstnations.morningstar",
        "firstnations.wheel",
        "firstnations.handprint",
        "firstnations.feather",
        "firstnations.medicinewheel",
        "firstnations.twospirit",
        "firstnations.twospiritfeathers",
        "firstnations.formline",
        "firstnations.parfleche",
        "firstnations.pottery",
        "firstnations.beadwork",
        "firstnations.quillwork",
        "firstnations.drum",
        "firstnations.bonenecklace",
    ),
    # Multicultural
    "W3TFH8QN0KCB27": (
        "world.street",
        "world.bunting",
        "flag.argentina",
        "flag.brazil",
        "flag.china",
        "flag.colombia",
        "flag.cuba",
        "flag.egypt",
        "flag.ethiopia",
        "flag.france",
        "flag.ghana",
        "flag.greece",
        "flag.haiti",
        "flag.india",
        "flag.indonesia",
        "flag.ireland",
        "flag.italy",
        "flag.jamaica",
        "flag.japan",
        "flag.kenya",
        "flag.korea",
        "flag.lebanon",
        "flag.mexico",
        "flag.morocco",
        "flag.nigeria",
        "flag.pakistan",
        "flag.peru",
        "flag.philippines",
        "flag.poland",
        "flag.samoa",
        "flag.southafrica",
        "flag.turkey",
        "flag.ukraine",
        "flag.vietnam",
        "flag.germany",
        "flag.netherlands",
        "flag.belgium",
        "flag.spain",
        "flag.portugal",
        "flag.sweden",
        "flag.norway",
        "flag.denmark",
        "flag.finland",
        "flag.iceland",
        "flag.switzerland",
        "flag.austria",
        "flag.czechia",
        "flag.hungary",
        "flag.romania",
        "flag.russia",
        "flag.canada",
        "flag.unitedstates",
        "flag.chile",
        "flag.venezuela",
        "flag.dominicanrepublic",
        "flag.guatemala",
        "flag.puertorico",
        "flag.bangladesh",
        "flag.thailand",
        "flag.singapore",
        "flag.israel",
        "flag.armenia",
        "flag.algeria",
        "flag.tunisia",
        "flag.senegal",
        "flag.cameroon",
        "flag.tanzania",
        "flag.somalia",
        "flag.sudan",
        "flag.papuanewguinea",
        "flag.palestine",
        "flag.australia",
    ),
    # Family
    "M6XBF9TQ4KP3HZ": (
        "family.washing",
        "family.nursery",
        "family.table",
        "family.paperchain",
        "family.photoframe",
        "family.rattle",
        "family.booties",
        "family.engaged",
        "family.married",
        "family.parent",
        "family.newhome",
        "family.caregiver",
        "family.nest",
    ),
}

_TABLES = ("public.marketplace_listings", "public.user_decorations", "public.users")


def upgrade() -> None:
    uids = list(_PACKS)
    ids = sorted({piece for pieces in _PACKS.values() for piece in pieces})
    # Every table here is FORCE RLS and a migration carries no request context,
    # so the owner's policies are lifted for the writes and restored after.
    for table in _TABLES:
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
    try:
        bind = op.get_bind()
        bind.execute(
            sa.text(
                "DELETE FROM public.user_decorations "
                "WHERE source = ANY(:uids) OR decoration_id = ANY(:ids)"
            ),
            {"uids": uids, "ids": ids},
        )
        bind.execute(
            sa.text(
                "UPDATE public.users "
                "SET profile_decorations = profile_decorations - 'banner' "
                "WHERE profile_decorations ->> 'banner' = ANY(:ids)"
            ),
            {"ids": ids},
        )
        bind.execute(
            sa.text(
                "UPDATE public.users "
                "SET profile_decorations = profile_decorations - 'frame' - 'frame_tint' "
                "WHERE profile_decorations ->> 'frame' = ANY(:ids)"
            ),
            {"ids": ids},
        )
        # The trophies left, in the order they were worn.
        bind.execute(
            sa.text(
                "UPDATE public.users SET profile_decorations = jsonb_set("
                "profile_decorations, '{trophies}', COALESCE(("
                "SELECT jsonb_agg(worn.id ORDER BY worn.position) "
                "FROM jsonb_array_elements_text(profile_decorations -> 'trophies') "
                "WITH ORDINALITY AS worn(id, position) "
                "WHERE worn.id <> ALL(:ids)), '[]'::jsonb)) "
                "WHERE jsonb_typeof(profile_decorations -> 'trophies') = 'array' "
                "AND EXISTS (SELECT 1 FROM jsonb_array_elements_text("
                "profile_decorations -> 'trophies') AS worn(id) "
                "WHERE worn.id = ANY(:ids))"
            ),
            {"ids": ids},
        )
        # Versions go with their listing (ON DELETE CASCADE).
        bind.execute(
            sa.text(
                "DELETE FROM public.marketplace_listings "
                "WHERE source = 'builtin' AND uid = ANY(:uids)"
            ),
            {"uids": uids},
        )
    finally:
        for table in _TABLES:
            op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    # What was deleted was a record of who somebody is; nothing puts it back.
    pass
