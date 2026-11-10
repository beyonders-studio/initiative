"""Reading an install's connection schema, and holding what was typed into it.

A plug-in declares *connections* — named groups of typed fields — and the pinned
definition is the only description of them this build trusts. A guild's answers
are validated against that pinned copy rather than against whatever the catalog
says today, so upgrading a listing can never retroactively change what an
existing install was allowed to store.

Two custody rules run through everything here:

* **A secret goes in and does not come back.** Values typed into a ``secret``
  field are encrypted per key and stored; a read reports only whether a value is
  present. Nothing in the API returns one, to anybody.
* **Managed keys are not typed at all.** A field the manifest marks ``managed``
  is written from the plug-in's ``after_connect`` answer, when a vendor flow
  completes or when a typed connection that declares ``after_connect`` is
  saved, so this path refuses one rather than letting a form overwrite it.

A guild-wide connection is not always typed. One that declares a ``flow`` is
established by Initiative instead
(:mod:`app.services.tenant.plugin_connection_flows`): a guild admin runs the
vendor's own flow once — an organization-wide install, on the vendor's page,
where somebody who owns the account grants what it may see — and the plug-in's
``after_connect`` hook says what goes into that connection's managed fields.
The scope is unchanged, since the credential is still the guild's; what
changes is who fills it and how, and :func:`guild_connection_ref` is the
handle the plug-in asks for its token by.

A flow's tokens are held beside the declared fields under reserved keys
(:data:`RESERVED_TOKEN_KEYS`), which no manifest declares and no form writes.

Satisfaction is computed from presence alone — which fields have values. This
build never inspects a credential, calls a vendor, or learns a scope; whether a
credential carries the permissions it needs is the plug-in's to report, and arrives
separately as ``config_state``.

A plug-in may also declare *settings*: values the seat sees and changes on the
install, which every expression of a declarative plug-in reads
(:func:`install_settings`). They are checked against the pinned definition the
same way (:func:`setting_value`).
"""

from __future__ import annotations

import secrets
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from app.core.encryption import SALT_PLUGIN_CONFIG, decrypt_field, encrypt_field
from app.core.errors import CodedError
from app.core.messages import GuildPluginMessages
from app.services.marketplace.manifest_values import is_unique_setting_value

__all__ = [
    "ACCOUNT_LABEL",
    "CONFIG_STATES",
    "MAX_CONFIG_VALUE_LENGTH",
    "MAX_SECRET_VALUE_LENGTH",
    "REMOVED_AT",
    "RESERVED_TOKEN_KEYS",
    "ConfigState",
    "PluginConfigError",
    "apply_connection_values",
    "checks_typed_values",
    "config_state",
    "connection_by_id",
    "connection_id_for_ref",
    "decrypt_connection_secrets",
    "definition_connections",
    "definition_settings",
    "guild_connection_ref",
    "has_value_map",
    "install_settings",
    "is_satisfied",
    "mint_connection_ref",
    "needs_configuration",
    "prune_to_definition",
    "runs_vendor_flow",
    "setting_value",
    "token_of",
    "without_tokens",
]

#: What a plain field may hold. Generous for a hostname or an account name,
#: small enough that the row stays configuration.
MAX_CONFIG_VALUE_LENGTH = 2_000
#: What a secret field may hold. Larger because a private-key PEM is a
#: legitimate credential for several vendors.
MAX_SECRET_VALUE_LENGTH = 16_000

#: What a plug-in may report back about the configuration it was handed.
CONFIG_STATES: frozenset[str] = frozenset({"unverified", "ok", "invalid"})

#: When the vendor reported a connection removed (epoch seconds), kept in its
#: plain map until the connection is read ``ok`` or connected again.
REMOVED_AT = "removed_at"

#: The account the plug-in's ``after_connect`` said a typed connection's values
#: belong to, kept in its plain map.
ACCOUNT_LABEL = "account_label"

#: Where a connection's flow keeps its tokens, beside its declared fields: the
#: two tokens sealed in the secrets map, the two expiry times (epoch seconds)
#: in the plain map. :data:`REMOVED_AT` and :data:`ACCOUNT_LABEL` are kept in
#: the plain map the same way.
RESERVED_TOKEN_KEYS: frozenset[str] = frozenset(
    {
        "access_token",
        "refresh_token",
        "expires_at",
        "refresh_expires_at",
        REMOVED_AT,
        ACCOUNT_LABEL,
    }
)

#: Long enough that a handle is never guessed, short enough to sit in a URL the
#: plug-in builds. ``token_urlsafe(24)`` renders as 32 characters, which is the
#: column width.
_REF_ENTROPY_BYTES = 24


def mint_connection_ref() -> str:
    return secrets.token_urlsafe(_REF_ENTROPY_BYTES)


def without_tokens(values: Mapping[str, Any] | None) -> dict[str, Any]:
    """A stored map with the reserved token keys taken out."""
    return {k: v for k, v in (values or {}).items() if k not in RESERVED_TOKEN_KEYS}


class PluginConfigError(CodedError):
    """A configuration write this build will not store, as a message code."""


@dataclass(frozen=True)
class ConfigState:
    """What the UI needs to say whether an install still needs attention.

    ``needs_config`` is presence-derived and always knowable here.
    ``state`` / ``detail`` are the plug-in's own verdict, which stays ``unverified``
    for a plug-in that never reports — nothing blocks on the round trip.
    """

    needs_config: bool
    state: str
    detail: str | None = None


# --- reading the pinned definition ------------------------------------------


def definition_connections(definition: dict[str, Any] | None) -> list[dict[str, Any]]:
    """The connections a pinned definition declares, in manifest order."""
    declared = (definition or {}).get("connections")
    if not isinstance(declared, list):
        return []
    return [entry for entry in declared if isinstance(entry, dict)]


def connection_by_id(
    definition: dict[str, Any] | None, connection_id: str
) -> dict[str, Any] | None:
    for connection in definition_connections(definition):
        if connection.get("id") == connection_id:
            return connection
    return None


def definition_settings(definition: dict[str, Any] | None) -> list[dict[str, Any]]:
    """The settings a pinned definition declares, in manifest order."""
    declared = (definition or {}).get("settings")
    if not isinstance(declared, list):
        return []
    return [entry for entry in declared if isinstance(entry, dict)]


def install_settings(plugin: Any) -> dict[str, Any]:
    """What every expression of a declarative plug-in reads of its install:
    ``settings``, each setting's value by key, and ``aliases``, each unique
    setting's earlier values by key, newest first."""
    return {
        "settings": dict(plugin.settings or {}),
        "aliases": dict(plugin.setting_aliases or {}),
    }


def token_of(connection: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """The connection's ``token``, when it declares one."""
    token = (connection or {}).get("token")
    return token if isinstance(token, dict) else None


def runs_vendor_flow(connection: dict[str, Any] | None) -> bool:
    """Whether this connection is established by a vendor flow rather than by
    typing.

    The question a ``flow`` answers, asked of either scope. The scope answers a
    different one — whose credential comes back — and the two are independent:
    a member authorizing their own account and an admin installing for the
    whole guild are the same flow run by different people.
    """
    return bool(connection) and isinstance(connection.get("flow"), dict)


def checks_typed_values(connection: Mapping[str, Any] | None) -> bool:
    """Whether the plug-in's ``after_connect`` checks what an admin types into
    this connection before it is stored: a guild-wide connection without a
    flow that declares ``after_connect``."""
    return (
        bool(connection)
        and connection.get("scope") == "static"
        and not isinstance(connection.get("flow"), dict)
        and connection.get("after_connect") is True
    )


# --- the handle a guild-wide flow is joined by -------------------------------


def guild_connection_ref(plugin: Any, connection_id: str) -> str:
    """The opaque handle the plug-in writes this guild connection's result against.

    Minted on the admin's first connect and kept, so reconnecting keeps one
    identity rather than minting a new one each time — the rule a member's ref
    already follows. Clearing the connection drops it, since the flow it was
    routing is over; starting again mints a fresh one. It lives on the install
    row because a guild-wide credential does.

    Mutating rather than returning a new mapping is deliberate: the caller is
    holding the row inside a transaction it is about to commit, and a ref handed
    out but not stored is one the write-back would refuse.

    The ref is the authorization: a write-back is accepted for the connection
    its handle names, and only for one this install actually minted.
    """
    refs = dict(plugin.connection_refs or {})
    existing = refs.get(connection_id)
    if isinstance(existing, str) and existing:
        return existing

    refs[connection_id] = mint_connection_ref()
    # Reassigned rather than mutated in place: SQLAlchemy tracks a JSONB column
    # by identity, and a dict changed under it is a change that never lands.
    plugin.connection_refs = refs
    return refs[connection_id]


def connection_id_for_ref(plugin: Any, connection_ref: str) -> str | None:
    """Which guild connection a handle names, or ``None`` for none of them.

    ``None`` is the ordinary answer for a member's ref, which this install keeps
    nowhere: the caller tries the per-member rows and finds it there.
    """
    if not connection_ref:
        return None
    for connection_id, ref in (plugin.connection_refs or {}).items():
        if ref == connection_ref:
            return connection_id
    return None


def _fields(connection: dict[str, Any]) -> list[dict[str, Any]]:
    declared = connection.get("fields")
    if not isinstance(declared, list):
        return []
    return [entry for entry in declared if isinstance(entry, dict)]


# --- validating what was typed ----------------------------------------------


def _coerce(field: dict[str, Any], value: Any) -> Any:
    """One submitted value, checked against its declared type.

    Types are the closed manifest enum, so this is a total match rather than a
    fallback: a field whose type this build does not know never reaches here,
    because the definition that declared it would not have validated.
    """
    field_type = field.get("type")

    if field_type == "bool":
        if not isinstance(value, bool):
            raise PluginConfigError(GuildPluginMessages.CONFIG_INVALID_VALUE)
        return value

    if field_type == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            raise PluginConfigError(GuildPluginMessages.CONFIG_INVALID_VALUE)
        return value

    if not isinstance(value, str):
        raise PluginConfigError(GuildPluginMessages.CONFIG_INVALID_VALUE)
    text = value.strip()
    if not text:
        raise PluginConfigError(GuildPluginMessages.CONFIG_INVALID_VALUE)

    limit = (
        MAX_SECRET_VALUE_LENGTH if field_type == "secret" else MAX_CONFIG_VALUE_LENGTH
    )
    if len(text) > limit:
        raise PluginConfigError(GuildPluginMessages.CONFIG_VALUE_TOO_LONG)

    if field_type == "select":
        options = field.get("options")
        if not isinstance(options, list) or text not in options:
            raise PluginConfigError(GuildPluginMessages.CONFIG_INVALID_VALUE)
        return text

    if field_type == "url":
        if not text.startswith(("https://", "http://")):
            raise PluginConfigError(GuildPluginMessages.CONFIG_INVALID_VALUE)
        if " " in text:
            raise PluginConfigError(GuildPluginMessages.CONFIG_INVALID_VALUE)
        return text

    return text


def setting_value(setting: Mapping[str, Any], value: Any) -> str | None:
    """A value submitted for ``setting``, as it is kept: one line of text, or
    ``None`` to clear a setting that is not unique.

    A unique setting always holds a value, in lowercase: a lowercase letter,
    then lowercase letters and digits (``SETTING_INVALID`` otherwise).
    """
    text = value.strip() if isinstance(value, str) else value
    if setting.get("unique") is True:
        text = text.lower() if isinstance(text, str) else text
        if not is_unique_setting_value(text):
            raise PluginConfigError(GuildPluginMessages.SETTING_INVALID)
        return text
    if text is None:
        return None
    if (
        not isinstance(text, str)
        or not text
        or any(ord(character) < 32 or ord(character) == 127 for character in text)
    ):
        raise PluginConfigError(GuildPluginMessages.CONFIG_INVALID_VALUE)
    if len(text) > MAX_CONFIG_VALUE_LENGTH:
        raise PluginConfigError(GuildPluginMessages.CONFIG_VALUE_TOO_LONG)
    return text


def apply_connection_values(
    connection: dict[str, Any],
    submitted: dict[str, Any],
    *,
    current: dict[str, Any],
    current_secrets: dict[str, Any],
    allow_managed: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Merge a submitted form into one connection's stored values.

    Returns the new ``(config, secrets)`` for this connection. A key present
    with ``None`` is a clear; a key absent is left alone, so a form that renders
    a subset of the fields cannot wipe the rest. Secret values are encrypted on
    the way in and only ever leave again through
    :func:`decrypt_connection_secrets`.

    ``allow_managed`` is for the plug-in's own write-back path, which is the only
    caller entitled to set a field the manifest marked ``managed``.
    """
    fields = {field["key"]: field for field in _fields(connection) if "key" in field}

    config = dict(current or {})
    secrets = dict(current_secrets or {})

    cleared: set[str] = set()
    for key, value in submitted.items():
        field = fields.get(key)
        if field is None:
            raise PluginConfigError(GuildPluginMessages.CONFIG_UNKNOWN_FIELD)
        if field.get("managed") is True and not allow_managed:
            raise PluginConfigError(GuildPluginMessages.CONFIG_MANAGED_FIELD)

        is_secret = field.get("type") == "secret"
        if value is None:
            config.pop(key, None)
            secrets.pop(key, None)
            cleared.add(key)
            continue

        coerced = _coerce(field, value)
        if is_secret:
            secrets[key] = encrypt_field(coerced, SALT_PLUGIN_CONFIG)
            config.pop(key, None)
        else:
            config[key] = coerced
            secrets.pop(key, None)

    # A required field left empty is a connection that cannot work, and saying
    # so at the point of the write is the difference between a form the admin
    # can fix and a widget that mysteriously stays dark.
    #
    # Clearing one is the exception, and deliberately so: taking a credential
    # back has to work at any moment, whether or not what remains adds up to a
    # working connection. What is left then reads as unconfigured — satisfaction
    # is recomputed from what is stored, so the capability lapses with it.
    for key, field in fields.items():
        if field.get("required") is not True or key in cleared:
            continue
        if key not in config and key not in secrets:
            raise PluginConfigError(GuildPluginMessages.CONFIG_REQUIRED_FIELD)

    return config, secrets


def decrypt_connection_secrets(secrets: dict[str, Any] | None) -> dict[str, str]:
    """The plaintext values, for the one caller that hands them to the plug-in.

    Never reached from a response path: the API's own reads report presence.
    """
    out: dict[str, str] = {}
    for key, ciphertext in (secrets or {}).items():
        if isinstance(ciphertext, str):
            out[key] = decrypt_field(ciphertext, SALT_PLUGIN_CONFIG)
    return out


# --- presence, and what it implies ------------------------------------------


def prune_to_definition(
    definition: dict[str, Any] | None,
    config: dict[str, Any] | None,
    secrets: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any], set[str]]:
    """Stored values, minus anything the definition no longer declares.

    Used when an install moves to a new version. A value cannot outlive the
    field it was typed into, and the pruning has to reach fields rather than
    stopping at connections: a version that keeps a connection but drops one of
    its fields would otherwise leave that value stored, and a non-secret one
    would keep appearing in the install's own detail payload.

    Returns the pruned maps and the ids of connections the definition dropped
    entirely, which the caller revokes — the plug-in is still holding whatever
    those values bought it.
    """
    # A connection with a flow keeps its tokens and its removal mark too, under
    # the reserved keys, and a checked typed one its account.
    declared: dict[str, set[str]] = {
        connection["id"]: {
            field["key"] for field in _fields(connection) if "key" in field
        }
        | (
            RESERVED_TOKEN_KEYS
            if runs_vendor_flow(connection) or checks_typed_values(connection)
            else set()
        )
        for connection in definition_connections(definition)
        if isinstance(connection.get("id"), str)
    }

    def _prune(stored: dict[str, Any] | None) -> dict[str, Any]:
        kept: dict[str, Any] = {}
        for connection_id, values in (stored or {}).items():
            fields = declared.get(connection_id)
            if fields is None or not isinstance(values, dict):
                continue
            surviving = {key: value for key, value in values.items() if key in fields}
            # An emptied connection is stored as absent rather than as an empty
            # map, so "has anything been configured here?" has one shape.
            if surviving:
                kept[connection_id] = surviving
        return kept

    dropped = {
        connection_id
        for connection_id in {*(config or {}), *(secrets or {})}
        if connection_id not in declared
    }
    return _prune(config), _prune(secrets), dropped


def has_value_map(
    connection: dict[str, Any],
    config: dict[str, Any] | None,
    secrets: dict[str, Any] | None,
) -> dict[str, bool]:
    """Which of a connection's fields hold a value.

    This is the whole of what a client is told about a stored credential, and
    the only input to satisfaction.
    """
    stored_config = config or {}
    stored_secrets = secrets or {}
    return {
        field["key"]: (field["key"] in stored_config or field["key"] in stored_secrets)
        for field in _fields(connection)
        if "key" in field
    }


def is_satisfied(
    connection: dict[str, Any],
    config: dict[str, Any] | None,
    secrets: dict[str, Any] | None,
) -> bool:
    """Whether this connection has everything it declared it needs.

    A connection with no required fields is satisfied once anything is set. A
    flow connection holding the token its flow stored is satisfied once its
    required managed values are there too.
    """
    present = has_value_map(connection, config, secrets)
    if runs_vendor_flow(connection) and "access_token" in (secrets or {}):
        return all(
            present.get(field["key"], False)
            for field in _fields(connection)
            if field.get("required") is True and "key" in field
        )
    if not present:
        return False
    required = [
        field["key"]
        for field in _fields(connection)
        if field.get("required") is True and "key" in field
    ]
    if required:
        return all(present.get(key, False) for key in required)
    return any(present.values())


def installation_meets(
    plugin: Any, requires: Any, *, members_connect: bool = False
) -> bool:
    """Whether a call the installation makes meets ``requires``: the
    community's own connections it names hold a value, every one for
    ``all_of`` and one for ``any_of``. A member's connection never answers the
    installation. With ``members_connect``, one it names counts as held: it is
    the member's to make when they run what asks for it, and they are asked to
    then. Absent, it asks nothing."""
    if not isinstance(requires, dict):
        return True
    for key, check in (("all_of", all), ("any_of", any)):
        terms = requires.get(key)
        if isinstance(terms, list):
            return check(
                _community_connection_holds(plugin, term, members_connect)
                for term in terms
            )
    return True


def _community_connection_holds(
    plugin: Any, connection_id: Any, members_connect: bool
) -> bool:
    connection = (
        connection_by_id(plugin.definition, connection_id)
        if isinstance(connection_id, str)
        else None
    )
    if connection is None:
        return False
    if connection.get("scope") == "interactive":
        return members_connect
    return is_satisfied(
        connection,
        (plugin.config or {}).get(connection_id) or {},
        (plugin.secret_fields or {}).get(connection_id) or {},
    )


def needs_configuration(
    definition: dict[str, Any] | None,
    config: dict[str, Any] | None,
    secrets: dict[str, Any] | None,
) -> bool:
    """Whether a guild admin still has something to fill in.

    Only guild-scoped (``static``) connections count. A per-member connection
    nobody has completed is not an unfinished install — installation is never
    gated on one, and members connect when and if they want what it unlocks.
    """
    stored_config = config or {}
    stored_secrets = secrets or {}
    for connection in definition_connections(definition):
        if connection.get("scope") != "static":
            continue
        connection_id = connection.get("id")
        if not isinstance(connection_id, str):
            continue
        if not is_satisfied(
            connection,
            stored_config.get(connection_id) or {},
            stored_secrets.get(connection_id) or {},
        ):
            return True
    return False


def config_state(plugin: Any) -> ConfigState:
    """The combined answer the settings page shows for an install."""
    return ConfigState(
        needs_config=needs_configuration(
            plugin.definition, plugin.config, plugin.secret_fields
        ),
        state=plugin.config_state
        if plugin.config_state in CONFIG_STATES
        else "unverified",
        detail=plugin.config_state_detail,
    )
