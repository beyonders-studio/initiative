"""The scope vocabulary: what parses, and what a scope set lets a plug-in do."""

from __future__ import annotations

import pytest

from app.core.plugin_scopes import (
    ALL_SCOPES,
    LEVEL_SCOPES,
    MAX_PUBLIC_ID_LENGTH,
    PUBLIC_ID_CHARS,
    InstallLevel,
    PluginScopeAccess,
    PluginScopeResource,
    UnknownPluginScope,
    expand,
    is_known_scope,
    is_standing_scope,
    ordered_scopes,
    parse_scope,
    plugin_scope,
    plugin_scope_target,
    tool_resource,
    validate_scopes,
)
from app.core.tools import Tool


def test_a_tool_scope_parses_to_its_tool():
    resource, access = parse_scope("counter_groups:write")
    assert resource is tool_resource(Tool.counter_group)
    assert access is PluginScopeAccess.write


@pytest.mark.parametrize(
    "scope",
    [
        "members:write",
        "initiatives:write",
        "projects",
        "projects:admin",
        "project:read",
        "settings:read",
        "",
    ],
)
def test_what_is_not_a_scope_is_refused(scope):
    with pytest.raises(UnknownPluginScope):
        parse_scope(scope)


def test_validate_names_the_scope_it_refused():
    with pytest.raises(UnknownPluginScope) as refused:
        validate_scopes(["files:read", "guild:owner"])
    assert refused.value.scope == "guild:owner"


def test_each_level_has_a_standing_scope_a_community_can_grant():
    assert LEVEL_SCOPES == {
        InstallLevel.moderator: "initiatives:moderate",
        InstallLevel.community_admin: "community:admin",
    }
    for scope in LEVEL_SCOPES.values():
        assert scope in ALL_SCOPES
        assert is_known_scope(scope)
        assert is_standing_scope(scope)
    assert validate_scopes(["community:admin", "files:read"]) == {
        "community:admin",
        "files:read",
    }


@pytest.mark.parametrize("scope", ["initiatives:moderate", "community:admin"])
def test_a_standing_names_no_resource(scope):
    """A standing is held by exact name: it reads and writes nothing itself,
    so a grant of one alone reaches no tool."""
    with pytest.raises(UnknownPluginScope):
        parse_scope(scope)
    assert expand([scope]) == (frozenset(), frozenset())
    read, write = expand([scope, "files:read"])
    assert read == {PluginScopeResource("files")} and write == frozenset()


def test_writing_implies_reading():
    read, write = expand(["files:write", "comments:read"])
    assert write == {PluginScopeResource("files")}
    assert read == {PluginScopeResource("files"), PluginScopeResource("comments")}


def test_read_only_resources_have_no_write_scope():
    assert "members:read" in ALL_SCOPES
    assert "initiatives:read" in ALL_SCOPES
    assert "members:write" not in ALL_SCOPES


def test_the_plugin_kit_contract_names_the_same_scopes():
    """Two sources in two repositories: the kit's contract, which an author
    requests scopes from, and this vocabulary, which grants and enforces them.
    A scope in one and not the other is either one no plug-in can ask for or one
    a plug-in can ask for and never be granted."""
    from app.services.marketplace import contract

    assert contract.enum("scope") == frozenset(ALL_SCOPES)


def test_a_plugin_scope_names_the_plugin_it_lets_one_call():
    assert plugin_scope("acme.github") == "plugins:acme.github"
    assert plugin_scope_target("plugins:acme.github") == "acme.github"
    assert is_known_scope("plugins:acme.github")
    assert validate_scopes(["plugins:acme.github", "files:read"]) == {
        "plugins:acme.github",
        "files:read",
    }


@pytest.mark.parametrize(
    "scope",
    [
        "plugins:",
        "plugins:github",
        "plugins:Acme.github",
        "plugins:acme github",
        "plugin:acme.github",
        "xplugins:acme.github",
        "plugins:" + "a." + "b" * MAX_PUBLIC_ID_LENGTH,
    ],
)
def test_what_is_not_a_plugin_scope_is_refused(scope):
    assert plugin_scope_target(scope) is None
    with pytest.raises(UnknownPluginScope):
        validate_scopes([scope])


def test_a_plugin_scope_reaches_no_resource():
    read, write = expand(["plugins:acme.github", "tags:read"])
    assert read == {PluginScopeResource("tags")}
    assert write == set()


def test_plugin_scopes_follow_the_vocabulary_in_order():
    assert ordered_scopes(
        ["plugins:b.one", "tags:read", "plugins:a.two", "projects:read", "nope"]
    ) == ["projects:read", "tags:read", "plugins:a.two", "plugins:b.one"]


def test_the_public_id_rule_is_the_contracts():
    from app.services.marketplace import contract

    assert PUBLIC_ID_CHARS == contract.charset("publicId")
    assert MAX_PUBLIC_ID_LENGTH == contract.cap("publicIdLength")
