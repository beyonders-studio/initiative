"""The two identity types, with and without an installed plug-in's boundary.

For a person both are ``int``, schema and all, the schema marked with what
each names. Under an install's boundary they read references in its input
phase, stay ``int`` in its handler phase, and write markers (or the
community's known reference) in its response phase.
"""

from __future__ import annotations

from typing import Annotated, Any

import pytest
from pydantic import BaseModel, ValidationError
from pydantic_core import PydanticSerializationError

from app.core.config import settings
from app.core.identity_boundary import (
    LEXICAL_MENTIONS,
    MARKDOWN_MENTIONS,
    UNKNOWN_REFERENCE_ERROR,
    UPLOAD_PATH,
    BoundaryPhase,
    GuildId,
    InstallBoundary,
    PersonId,
    admit_install,
    boundary_scope,
    current_install_boundary,
)
from app.core.messages import PluginMessages
from app.db.guild_standing import named_ref_candidates
from app.models.platform.identity_ref import IdentityEntity
from app.schemas.platform.user import UserPublic

_GUILD = 7
_INSTALL = 3
_PERSON_REF = "uplu_person-one"
_OTHER_REF = "uplu_person-two"
_GUILD_REF = "gplu_the-community"


class _Payload(BaseModel):
    guild_id: GuildId
    owner: PersonId
    helpers: list[PersonId] = []
    reviewer: PersonId | None = None


class _Plain(BaseModel):
    guild_id: int
    owner: int
    helpers: list[int] = []
    reviewer: int | None = None


def _boundary(**overrides) -> InstallBoundary:
    values = {
        "guild_id": _GUILD,
        "install_id": _INSTALL,
        "guild_ref": _GUILD_REF,
        "named": {
            _PERSON_REF: (IdentityEntity.user, 11),
            _OTHER_REF: (IdentityEntity.user, 12),
            _GUILD_REF: (IdentityEntity.guild, _GUILD),
        },
    }
    values.update(overrides)
    return InstallBoundary(**values)


def _errors(exc: ValidationError) -> list[tuple[str, str]]:
    return [(e["type"], e["msg"]) for e in exc.errors()]


# ---------------------------------------------------------------------------
# A person
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("mode", ["validation", "serialization"])
def test_the_published_schema_is_a_marked_integer(mode):
    ours = _Payload.model_json_schema(mode=mode)
    plain = _Plain.model_json_schema(mode=mode)
    properties = ours["properties"]
    for schema, identity in (
        (properties["guild_id"], "community"),
        (properties["owner"], "person"),
        (properties["helpers"]["items"], "person"),
        (properties["reviewer"]["anyOf"][0], "person"),
    ):
        assert schema.pop("x-identity") == identity
    ours.pop("title")
    plain.pop("title")
    assert ours == plain


def test_a_person_reads_and_writes_integers():
    payload = _Payload.model_validate(
        {"guild_id": 7, "owner": "11", "helpers": [12], "reviewer": None}
    )
    assert payload.owner == 11
    assert payload.model_dump(mode="json") == {
        "guild_id": 7,
        "owner": 11,
        "helpers": [12],
        "reviewer": None,
    }


def test_an_open_slot_without_an_install_is_a_person():
    with boundary_scope():
        assert current_install_boundary() is None
        payload = _Payload(guild_id=7, owner=11)
        assert payload.model_dump(mode="json")["owner"] == 11


def test_an_install_is_admitted_only_inside_a_slot():
    with pytest.raises(RuntimeError):
        admit_install(_boundary())


# ---------------------------------------------------------------------------
# An install's input
# ---------------------------------------------------------------------------


def test_references_resolve_to_the_rows_they_name():
    with boundary_scope():
        admit_install(_boundary())
        payload = _Payload.model_validate(
            {
                "guild_id": _GUILD_REF,
                "owner": _PERSON_REF,
                "helpers": [_OTHER_REF, _PERSON_REF],
                "reviewer": _OTHER_REF,
            }
        )
    assert (payload.guild_id, payload.owner, payload.helpers, payload.reviewer) == (
        _GUILD,
        11,
        [12, 11],
        12,
    )


@pytest.mark.parametrize(
    "field, value",
    [
        ("owner", 11),
        ("owner", "11"),
        ("owner", "uplu_nobody-here"),
        ("owner", _GUILD_REF),
        ("guild_id", _GUILD),
        ("guild_id", _PERSON_REF),
    ],
)
def test_anything_but_a_resolved_reference_is_refused(field, value):
    body = {"guild_id": _GUILD_REF, "owner": _PERSON_REF}
    body[field] = value
    with boundary_scope():
        admit_install(_boundary())
        with pytest.raises(ValidationError) as caught:
            _Payload.model_validate(body)
    assert _errors(caught.value) == [
        (UNKNOWN_REFERENCE_ERROR, PluginMessages.REFERENCE_UNKNOWN)
    ]


def test_a_community_reference_names_only_the_routed_community():
    named = {_GUILD_REF: (IdentityEntity.guild, _GUILD + 1)}
    with boundary_scope():
        admit_install(_boundary(named=named))
        with pytest.raises(ValidationError):
            _Payload.model_validate({"guild_id": _GUILD_REF, "owner": 1})


# ---------------------------------------------------------------------------
# An install's handler and response
# ---------------------------------------------------------------------------


def test_the_handler_works_in_row_ids():
    with boundary_scope():
        boundary = _boundary()
        admit_install(boundary)
        boundary.phase = BoundaryPhase.handler
        payload = _Payload.model_validate({"guild_id": _GUILD, "owner": 11})
        assert payload.model_dump(mode="json")["owner"] == 11
        assert boundary.wanted == set()


def test_the_response_carries_markers_and_the_known_community_reference():
    with boundary_scope():
        boundary = _boundary()
        admit_install(boundary)
        boundary.phase = BoundaryPhase.response
        dumped = _Payload(guild_id=_GUILD, owner=11, helpers=[12]).model_dump(
            mode="json"
        )
    assert dumped["guild_id"] == _GUILD_REF
    assert dumped["owner"] == f"{boundary.nonce}:u:11"
    assert dumped["helpers"] == [f"{boundary.nonce}:u:12"]
    assert dumped["reviewer"] is None
    assert boundary.wanted == {(IdentityEntity.user, 11), (IdentityEntity.user, 12)}


def test_an_unnamed_community_is_marked_for_minting():
    with boundary_scope():
        boundary = _boundary(guild_ref=None)
        admit_install(boundary)
        boundary.phase = BoundaryPhase.response
        dumped = _Payload(guild_id=_GUILD, owner=11).model_dump(mode="json")
    assert dumped["guild_id"] == f"{boundary.nonce}:g:{_GUILD}"
    assert (IdentityEntity.guild, _GUILD) in boundary.wanted


def test_a_response_names_no_other_community():
    with boundary_scope():
        boundary = _boundary(guild_ref=None)
        admit_install(boundary)
        boundary.phase = BoundaryPhase.response
        with pytest.raises(PydanticSerializationError):
            _Payload(guild_id=_GUILD + 1, owner=11).model_dump(mode="json")


def test_each_request_has_its_own_nonce():
    assert _boundary().nonce != _boundary().nonce


def test_the_slot_closes_with_the_request():
    with boundary_scope():
        admit_install(_boundary())
        assert current_install_boundary() is not None
    assert current_install_boundary() is None


# ---------------------------------------------------------------------------
# Mentions
# ---------------------------------------------------------------------------


class _Body(BaseModel):
    text: Annotated[str, MARKDOWN_MENTIONS]
    state: Annotated[dict[str, Any], LEXICAL_MENTIONS] = {}


def _mention(person: int | str | None, name: str) -> dict[str, Any]:
    return {
        "type": "mention",
        "mentionUserId": person,
        "mentionName": name,
        "text": name,
    }


def test_a_person_s_mention_is_stored_by_id_with_no_name():
    """A mention of somebody without an account keeps the name it has."""
    body = _Body.model_validate(
        {
            "text": "@[Ada](11), @[Bo]() on #task[Fix it](3)",
            "state": {
                "root": {"children": [_mention(11, "Ada"), _mention(None, "Bo")]}
            },
        }
    )
    assert body.text == "@[](11), @[Bo]() on #task[Fix it](3)"
    assert body.state == {
        "root": {"children": [_mention(11, ""), _mention(None, "Bo")]}
    }


_PICTURE = f"/uploads/{_GUILD}/pasted-ab12.png?size=small"
_FILE = f"https://initiative.example/uploads/{_GUILD}/notes.pdf#page=2"
_ELSEWHERE = f"https://pictures.example/uploads/{_GUILD}/logo.png?v=2"


@pytest.fixture
def own_origin(monkeypatch):
    """This deployment is served at ``initiative.example``."""
    monkeypatch.setattr(settings, "APP_URL", "https://initiative.example")


def _image(src: str) -> dict[str, Any]:
    return {"type": "image", "src": src, "altText": "chart", "width": 640}


def _shown(text: str, picture: str, file: str) -> dict[str, Any]:
    """A body mentioning somebody, showing a stored picture and file, and a
    linked picture from another site."""
    elsewhere = f"[![logo]({_ELSEWHERE})]({_ELSEWHERE})"
    return {
        "text": f"{text} ![chart]({picture}) [notes.pdf]({file}) {elsewhere}",
        "state": {
            "root": {
                "children": [
                    _mention(11, ""),
                    _image(picture),
                    {"type": "link", "url": file, "children": []},
                    _image(_ELSEWHERE),
                ]
            }
        },
    }


def test_a_person_s_stored_files_pass_through():
    body = _shown("@[](11) on #task[Fix it](3)", _PICTURE, _FILE)
    assert _Body.model_validate(body).model_dump(mode="json") == body


def test_an_install_s_mention_is_stored_by_row_id():
    with boundary_scope():
        admit_install(_boundary(members=frozenset({11})))
        body = _Body.model_validate(
            {
                "text": f"@[anyone]({_PERSON_REF}) on #task[Fix it](3)",
                "state": {"root": _mention(_PERSON_REF, "anyone")},
            }
        )
    assert body.text == "@[](11) on #task[Fix it](3)"
    assert body.state == {"root": _mention(11, "")}


def test_an_install_reads_a_mention_and_no_stored_file_s_path(own_origin):
    body = _Body.model_validate(_shown("@[](11)", _PICTURE, _FILE))
    with boundary_scope():
        boundary = _boundary()
        admit_install(boundary)
        boundary.phase = BoundaryPhase.response
        dumped = body.model_dump(mode="json")
    expected = _shown(f"@[]({boundary.nonce}:u:11)", "", "")
    expected["state"]["root"]["children"][0]["mentionUserId"] = f"{boundary.nonce}:u:11"
    assert dumped == expected


class _Files(BaseModel):
    picture: Annotated[str, UPLOAD_PATH]
    file: Annotated[str | None, UPLOAD_PATH] = None
    cover: Annotated[str | None, UPLOAD_PATH] = None
    missing: Annotated[str | None, UPLOAD_PATH] = None


def test_an_install_reads_a_stored_file_as_an_empty_string(own_origin):
    files = _Files(picture=_PICTURE, file=_FILE, cover=_ELSEWHERE)
    shown = {"picture": _PICTURE, "file": _FILE, "cover": _ELSEWHERE, "missing": None}
    assert files.model_dump(mode="json") == shown
    with boundary_scope():
        boundary = _boundary()
        admit_install(boundary)
        boundary.phase = BoundaryPhase.response
        dumped = files.model_dump(mode="json")
    assert dumped == shown | {"picture": "", "file": ""}


@pytest.mark.parametrize("named", ["11", "uplu_nobody-here", _GUILD_REF, _OTHER_REF])
def test_a_mention_of_nobody_named_here_is_refused(named):
    with boundary_scope():
        admit_install(_boundary(members=frozenset({11})))
        for body in (
            {"text": f"@[Ada]({named})"},
            {"text": "", "state": {"root": _mention(named, "Ada")}},
        ):
            with pytest.raises(ValidationError) as caught:
                _Body.model_validate(body)
            assert _errors(caught.value) == [
                (UNKNOWN_REFERENCE_ERROR, PluginMessages.REFERENCE_UNKNOWN)
            ]


# ---------------------------------------------------------------------------
# What the standing statement is asked about
# ---------------------------------------------------------------------------


def test_only_plugin_references_are_candidates():
    assert named_ref_candidates(
        [
            _PERSON_REF,
            _PERSON_REF,
            _GUILD_REF,
            "ubil_billing-person",
            "ucli_session-subject",
            "uplu_" + "x" * 80,
            "plain text",
            "42",
        ]
    ) == sorted({_PERSON_REF, _GUILD_REF})


# ---------------------------------------------------------------------------
# A person, as an install receives them
# ---------------------------------------------------------------------------


_ADA = UserPublic(
    id=11,
    username="ada",
    discriminator=1234,
    display_name="Ada Lovelace",
    avatar_url="https://pictures.example/ada.png",
)


@pytest.mark.parametrize(
    ("reads_names", "names"),
    [
        (
            True,
            {"username": "ada", "discriminator": 1234, "display_name": "Ada Lovelace"},
        ),
        (False, {}),
    ],
)
def test_a_person_reaches_an_install_by_reference_and_by_name_under_members_read(
    reads_names, names
):
    with boundary_scope():
        boundary = _boundary(reads_names=reads_names)
        admit_install(boundary)
        boundary.phase = BoundaryPhase.response
        dumped = _ADA.model_dump(mode="json")
    assert dumped == {"id": f"{boundary.nonce}:u:11", **names}


def test_a_person_reads_a_person_whole():
    dumped = _ADA.model_dump(mode="json")
    assert dumped["id"] == 11
    assert dumped["avatar_url"] == "https://pictures.example/ada.png"
