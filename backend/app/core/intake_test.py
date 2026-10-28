"""The stream registry, and the blueprints that must agree with it."""

from __future__ import annotations

import pytest

from app.blueprints.intake import blueprint_for
from app.core.intake import (
    CASE_FIELD_TYPES,
    STREAM_FIELDS,
    CaseField,
    IntakeStream,
    meta,
)
from app.models.tenant.metadata import MetadataType
from app.models.tenant.task import TaskStatusCategory

pytestmark = pytest.mark.always


def test_every_case_field_names_a_property_type_the_writer_can_create():
    """Which fields exist at all is a row in ``core/registry_coverage_test.py``;
    this is the type each one declares."""
    for field, declared in CASE_FIELD_TYPES.items():
        assert MetadataType(declared), field


def test_tracker_key_belongs_to_security_alone():
    """It names a finding in the private repository, which only security gets."""
    carrying = {
        s for s, fields in STREAM_FIELDS.items() if CaseField.tracker_key in fields
    }
    assert carrying == {IntakeStream.security}


@pytest.mark.parametrize("stream", list(IntakeStream))
def test_every_stream_ships_a_blueprint_that_parses(stream: IntakeStream):
    envelope = blueprint_for(stream)
    assert envelope.project.name
    assert envelope.task_statuses
    assert meta(stream).blueprint.endswith(".json")


@pytest.mark.parametrize("stream", list(IntakeStream))
def test_a_blueprint_defines_exactly_the_streams_case_fields(stream: IntakeStream):
    """The writer fills these by name, so the two declarations must agree."""
    envelope = blueprint_for(stream)
    defined = {
        definition.name: definition.type for definition in envelope.property_definitions
    }
    expected = {
        field.value: MetadataType(CASE_FIELD_TYPES[field])
        for field in STREAM_FIELDS[stream]
    }
    assert defined == expected


@pytest.mark.parametrize("stream", list(IntakeStream))
def test_a_blueprint_can_open_and_close_a_case(stream: IntakeStream):
    """A stream whose statuses had no ``done`` could never record a closure."""
    envelope = blueprint_for(stream)
    categories = {status.category for status in envelope.task_statuses}
    assert TaskStatusCategory.done in categories
    assert sum(1 for status in envelope.task_statuses if status.is_default) == 1


@pytest.mark.parametrize("stream", list(IntakeStream))
def test_a_blueprint_seeds_one_task_explaining_the_project(stream: IntakeStream):
    assert len(blueprint_for(stream).tasks) == 1
    seed = blueprint_for(stream).tasks[0]
    assert seed.description
    status_names = {status.name for status in blueprint_for(stream).task_statuses}
    assert seed.status_name in status_names


@pytest.mark.parametrize("stream", list(IntakeStream))
def test_a_blueprint_can_wait_on_whoever_filed_a_case(stream: IntakeStream):
    """A stream that holds a conversation sets up both statuses its binding
    names: waiting on the requester, and the one their answer moves a case to.
    A stream with none has nobody to wait on."""
    from app.blueprints.intake import REQUESTER_REPLIED, WAITING_ON_REQUESTER
    from app.core.intake import Conversation

    names = {status.name for status in blueprint_for(stream).task_statuses}
    holds = {WAITING_ON_REQUESTER, REQUESTER_REPLIED} <= names
    assert holds is (meta(stream).conversation is not Conversation.none)


def test_every_intake_error_code_is_localized():
    """A code the API can return says something in every language.

    Two independent sources, checked against each other: the constants the
    endpoints raise, and the four catalogues the SPA reads. A refusal reaches
    the reader as its own sentence rather than as a generic "could not save".
    """
    import json
    from pathlib import Path

    from app.core.messages import IntakeMessages

    codes = {
        value
        for name, value in vars(IntakeMessages).items()
        if not name.startswith("_") and isinstance(value, str)
    }
    assert codes, "IntakeMessages declares no codes"

    locales = Path(__file__).resolve().parents[2].parent / "frontend/public/locales"
    for locale in ("de", "en", "es", "fr"):
        catalogue = json.loads((locales / locale / "errors.json").read_text())
        missing = sorted(codes - set(catalogue))
        assert not missing, f"{locale}/errors.json is missing {missing}"


@pytest.mark.parametrize("stream", list(IntakeStream))
def test_every_stream_states_a_pace_the_limiter_reads(stream: IntakeStream):
    """A filing rate the limiter cannot parse would surface as an error on the
    first filing rather than here."""
    from limits import parse

    declared = meta(stream)
    assert parse(declared.filing_rate).amount > 0
    assert declared.max_open_per_filer is None or declared.max_open_per_filer > 0
