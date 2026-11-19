"""The code each tool plug-in's kind is given on this deployment.

A relationship's node ids pack ``(kind, id)`` into one ``bigint`` as
``code << 32 | id`` (``app.core.relationships.node_id``), and
``public.relationship_kind_code`` is the function that says each kind's code.
A built-in kind's code is in :data:`~app.core.tools.KINDS`; a tool plug-in's
kinds (``<key>.<uid in lower case>``, ``tool_plugins.tool_kinds``) are given
theirs here, when a listing version declaring them is registered, and the
function is rendered from both (``app.db.kind_codes``).

A code is given once and never moves or is given again: a row is only ever
inserted, from :data:`FIRST_PLUGIN_KIND_CODE` up (or, for a kind that took a
retired built-in kind's code, that code: :data:`ADOPTED_KIND_CODES`), so a stored node id always
names the kind it was written for. Codes stay below 2^31, which the column's
type holds them to, so a packed node id stays a positive ``bigint``.

Lives in ``public``: it says nothing about any community, only which kinds the
deployment has seen declared. Read and written on the system engine alone.
"""

from __future__ import annotations

from sqlalchemy import CheckConstraint, Column, Integer, Text
from sqlmodel import Field, SQLModel

__all__ = ["ADOPTED_KIND_CODES", "FIRST_PLUGIN_KIND_CODE", "PluginKindCode"]

#: The first code a plug-in's kind is given, far above the built-in kinds'.
FIRST_PLUGIN_KIND_CODE = 1024

#: The kinds of a tool that moved out of Initiative into a plug-in, each with
#: the code its built-in kind had, so a node id stored before the move still
#: names the same row (the Counters plug-in's, from 20261119_0618).
ADOPTED_KIND_CODES: dict[str, int] = {
    "counter_group.tsjvtcm0s7gv2x": 4,
    "counter.tsjvtcm0s7gv2x": 3,
}


class PluginKindCode(SQLModel, table=True):
    __tablename__ = "plugin_kind_codes"
    __table_args__ = (
        CheckConstraint(
            f"code >= {FIRST_PLUGIN_KIND_CODE} OR (kind, code) IN ("
            + ", ".join(
                f"('{kind}', {code})" for kind, code in ADOPTED_KIND_CODES.items()
            )
            + ")",
            name="ck_plugin_kind_codes_code",
        ),
    )

    kind: str = Field(sa_column=Column(Text, primary_key=True))
    code: int = Field(sa_column=Column(Integer, nullable=False, unique=True))
