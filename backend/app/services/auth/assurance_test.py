"""Tests for reading an IdP's account of an authentication.

Pins the two halves: what a verified id_token's ``amr``/``acr``/``auth_time``
become, and how one provider's entry folds into a session that may already
carry several.
"""

from __future__ import annotations

import pytest

from app.services.auth.assurance import (
    MAX_AMR_VALUE_LENGTH,
    MAX_AMR_VALUES,
    MAX_AUTH_TIME,
    MAX_CLAIM_VALUES,
    MAX_TRACKED_PROVIDERS,
    POLICY_AMR_MARKERS,
    RESERVED_AMR_PREFIXES,
    SECOND_FACTOR_AMR,
    ProviderAssurance,
    passkey_amr,
    policy_markers,
    read_assurance,
    read_narrowing,
    record_for_provider,
    session_amr,
)


def test_an_idp_that_describes_its_authentication_is_taken_at_its_word():
    assurance = read_assurance(
        {
            "sub": "s",
            "amr": ["pwd", "mfa", "otp"],
            "acr": "phr",
            "auth_time": 1757600000,
        }
    )
    assert assurance.amr == ("pwd", "mfa", "otp")
    assert assurance.acr == "phr"
    assert assurance.auth_time == 1757600000
    assert assurance.as_record() == {
        "auth_time": 1757600000,
        "amr": ["pwd", "mfa", "otp"],
        "acr": "phr",
    }


def test_an_idp_that_says_nothing_records_nothing():
    assurance = read_assurance({"sub": "s", "email": "a@example.com"})
    assert assurance == ProviderAssurance()
    assert assurance.as_record() == {}


@pytest.mark.parametrize(
    "claims",
    [
        {"amr": "mfa"},
        {"amr": {"0": "mfa"}},
        {"amr": [1, None, True]},
        {"amr": ["", "   "]},
        {"amr": ["x" * (MAX_AMR_VALUE_LENGTH + 1)]},
    ],
)
def test_an_amr_in_a_shape_oidc_does_not_describe_is_dropped(claims):
    assert read_assurance(claims).amr == ()


def test_amr_values_are_trimmed_deduplicated_and_bounded():
    claims = {"amr": [" pwd ", "pwd", *[f"m{i}" for i in range(MAX_AMR_VALUES + 5)]]}
    amr = read_assurance(claims).amr
    assert amr[0] == "pwd"
    assert len(amr) == MAX_AMR_VALUES
    assert len(set(amr)) == len(amr)


@pytest.mark.parametrize(
    "value, expected",
    [
        (1757600000, 1757600000),
        (1757600000.0, 1757600000),
        ("1757600000", 1757600000),
        (True, None),
        (0, None),
        (-5, None),
        ("yesterday", None),
        (None, None),
        (1757600000.5, None),
        (MAX_AUTH_TIME, MAX_AUTH_TIME),
        (MAX_AUTH_TIME + 1, None),
        (str(MAX_AUTH_TIME), MAX_AUTH_TIME),
        # Past the far end of any time, in each shape a JSON number arrives in.
        ("9" * 5000, None),
        (10**40, None),
        (1e300, None),
        (float("inf"), None),
        (float("nan"), None),
    ],
)
def test_auth_time_is_read_as_epoch_seconds_or_not_at_all(value, expected):
    assert read_assurance({"auth_time": value}).auth_time == expected


@pytest.mark.parametrize("value", [123, ["phr"], "", "  ", "x" * 300])
def test_an_acr_that_is_not_one_string_is_dropped(value):
    assert read_assurance({"acr": value}).acr is None


def test_the_session_amr_names_the_provider_and_what_it_used():
    assurance = read_assurance({"amr": ["mfa", "pwd"]})
    assert session_amr("acme", assurance, asserts_second_factor=True) == [
        "mfa",
        "oidc:acme",
        "pwd",
    ]


def test_the_session_amr_names_the_provider_even_when_the_idp_is_silent():
    assert session_amr("acme", ProviderAssurance()) == ["oidc:acme"]


def test_a_provider_replaces_only_its_own_entry():
    prior = {
        "4": {"auth_time": 100, "amr": ["pwd"]},
        "9": {"auth_time": 200, "amr": ["mfa"]},
    }
    merged = record_for_provider(
        prior,
        provider_id=4,
        assurance=ProviderAssurance(auth_time=300, amr=("mfa", "hwk")),
    )
    assert merged == {
        "4": {"auth_time": 300, "amr": ["mfa", "hwk"]},
        "9": {"auth_time": 200, "amr": ["mfa"]},
    }


def test_a_first_provider_starts_the_record():
    assert record_for_provider(
        None, provider_id=7, assurance=ProviderAssurance(auth_time=1)
    ) == {"7": {"auth_time": 1}}


def test_an_entry_that_is_not_an_object_is_not_carried_forward():
    merged = record_for_provider(
        {"4": "pwd", "9": {"auth_time": 2}},
        provider_id=1,
        assurance=ProviderAssurance(auth_time=3),
    )
    assert merged == {"1": {"auth_time": 3}, "9": {"auth_time": 2}}


def test_a_provider_that_now_says_nothing_leaves_no_stale_account():
    merged = record_for_provider(
        {"4": {"auth_time": 100, "amr": ["mfa"]}, "9": {"auth_time": 2}},
        provider_id=4,
        assurance=ProviderAssurance(),
    )
    assert merged == {"9": {"auth_time": 2}}


def test_the_record_is_bounded_and_keeps_the_provider_just_used():
    prior = {
        str(pid): {"auth_time": pid} for pid in range(1, MAX_TRACKED_PROVIDERS + 5)
    }
    merged = record_for_provider(
        prior, provider_id=999, assurance=ProviderAssurance(auth_time=1)
    )
    assert len(merged) == MAX_TRACKED_PROVIDERS
    assert "999" in merged
    # The least recently authenticated fall off first.
    assert "1" not in merged
    assert str(MAX_TRACKED_PROVIDERS + 4) in merged


# --- What a provider asserted about belonging ------------------------------


def test_a_provider_marks_itself_and_nothing_else():
    """A sign-in names the provider it came through. Which communities count
    it as theirs is read from their connections, so no marker says."""
    amr = session_amr("google", ProviderAssurance(amr=["pwd"]))
    assert amr == ["oidc:google", "pwd"]


def test_an_identity_providers_own_values_are_left_alone():
    """The IdP's vocabulary travels untouched beside our marker."""
    amr = session_amr(
        "corp", ProviderAssurance(amr=["mfa", "hwk"]), asserts_second_factor=True
    )
    assert set(amr) == {"oidc:corp", "mfa", "hwk"}


def test_a_provider_contributes_no_factor_until_the_operator_says_it_may():
    """The markers a rule reads are this application's account of what it
    verified. A provider contributes them where the operator has said that
    provider's word counts, and not before."""
    amr = session_amr("corp", ProviderAssurance(amr=["mfa", "hwk", "pwd"]))

    assert set(amr) == {"oidc:corp", "pwd"}


@pytest.mark.parametrize(
    "assurance",
    [
        ProviderAssurance(amr=("phr",)),
        ProviderAssurance(amr=("phrh",)),
        ProviderAssurance(acr="phr"),
    ],
)
def test_a_phishing_resistant_sign_in_is_a_second_factor(assurance):
    """Pocket ID names a passkey sign-in ``phr`` rather than ``mfa``. Where
    the provider's word counts, that is a second factor; where it does not,
    it is only the provider's vocabulary."""
    assert SECOND_FACTOR_AMR in session_amr(
        "pocket-id", assurance, asserts_second_factor=True
    )
    assert SECOND_FACTOR_AMR not in session_amr("pocket-id", assurance)


def test_a_one_time_code_alone_is_not_a_second_factor():
    """Pocket ID's emailed sign-in code is ``otp`` and nothing else: one factor."""
    amr = session_amr(
        "pocket-id", ProviderAssurance(amr=("otp",)), asserts_second_factor=True
    )

    assert amr == ["oidc:pocket-id", "otp"]


def test_what_the_provider_named_besides_is_kept_either_way():
    """Only the rule's own vocabulary is held back; the rest is the provider's
    and nothing reads it."""
    silent = session_amr("corp", ProviderAssurance(amr=["pwd", "kba"]))
    counted = session_amr(
        "corp", ProviderAssurance(amr=["pwd", "kba"]), asserts_second_factor=True
    )

    assert silent == counted == ["kba", "oidc:corp", "pwd"]


def test_the_narrowing_claim_is_recorded_for_the_gate():
    """What the provider said for a claim some community narrows by is kept
    beside the assurance, because the gate compares it later."""
    narrowing = read_narrowing({"hd": "acme.com"}, None, ["hd"])
    assurance = ProviderAssurance(auth_time=1, claims=narrowing)

    assert assurance.as_record() == {"auth_time": 1, "claims": {"hd": ["acme.com"]}}


def test_only_the_claims_somebody_narrows_by_are_recorded():
    """A provider says a great deal. What is kept is what a community asked
    a question about."""
    claims = {"hd": "acme.com", "groups": ["eng"], "email": "a@acme.com"}

    assert read_narrowing(claims, None, ["hd"]) == (("hd", ("acme.com",)),)
    assert read_narrowing(claims, None, []) == ()


def test_a_claim_the_provider_did_not_send_records_nothing():
    """An absent claim is an absent key rather than an empty one, so a
    connection narrowing by it is answered by nothing rather than by a blank."""
    assert read_narrowing({"sub": "x"}, None, ["hd"]) == ()
    assert ProviderAssurance(claims=()).as_record() == {}


def test_a_nested_path_is_read_like_the_rules_read_it():
    """The same dot-path extractor the group rules use, so a claim buried in
    an object is reachable here too."""
    found = read_narrowing(
        {"realm_access": {"roles": ["eng"]}}, None, ["realm_access.roles"]
    )

    assert found == (("realm_access.roles", ("eng",)),)


def test_a_long_group_list_is_bounded():
    """This rides in the access token, and a directory can put somebody in
    hundreds of groups."""
    claims = {"groups": [f"team-{n}" for n in range(200)]}

    ((_, values),) = read_narrowing(claims, None, ["groups"])

    assert len(values) == MAX_CLAIM_VALUES


# --- What the provider may say, and what only we may say --------------------


def test_a_provider_does_not_write_our_markers():
    """A provider's ``amr`` is its own vocabulary. The markers this application
    writes into a session are its own account of the sign-in, so a value
    arriving under one of those prefixes is dropped."""
    claimed = read_assurance({"amr": ["guild:99", "oidc:elsewhere", "mfa"]})
    assert claimed.amr == ("mfa",)


def test_the_drop_survives_being_merged_into_a_session():
    """End to end: the provider sends one, the session carries only the marker
    this application wrote, and the reading is unchanged."""
    assurance = read_assurance({"amr": ["guild:99", "pwd"]})
    amr = session_amr("corp", assurance)
    assert "guild:99" not in amr
    assert set(amr) == {"oidc:corp", "pwd"}


def test_whitespace_does_not_get_a_value_past_the_drop():
    """Values are trimmed before they are judged, so a padded one is judged
    the same as a bare one."""
    assert read_assurance({"amr": ["  guild:99  "]}).amr == ()


@pytest.mark.parametrize("prefix", RESERVED_AMR_PREFIXES)
def test_every_reserved_prefix_is_dropped(prefix):
    """Derived from the list itself, so a marker added later is covered by
    this test on the day it is added."""
    assert read_assurance({"amr": [f"{prefix}anything"]}).amr == ()


def test_an_unreserved_value_that_merely_contains_one_is_kept():
    """The rule is a prefix, not a substring: an IdP's own vocabulary is its
    own, and only the start of a value is ours."""
    assert read_assurance({"amr": ["not-guild:99"]}).amr == ("not-guild:99",)


# --- what a community's rule is allowed to be answered by -------------------


def test_only_this_modules_own_markers_reach_a_rule():
    """The vocabulary is closed, so what a community's rule is answered by is
    named here and not by whoever ran the identity provider."""
    assert policy_markers(["pwd", "mfa", "hwk", "oidc:corp", "otp"]) == frozenset(
        {"mfa", "hwk"}
    )
    assert policy_markers(None) == frozenset()
    assert policy_markers([]) == frozenset()


def test_a_value_shaped_like_two_markers_is_one_value():
    """The set travels onward as one delimited string, so a value carrying the
    delimiter would be two if it got through. It does not get through: it is
    not on the list."""
    assert policy_markers(["mfa,hwk"]) == frozenset()
    assert policy_markers(["hwk,"]) == frozenset()


def test_every_marker_on_the_list_is_answered_for():
    """Derived from the list itself, so a method added later is covered by
    this test on the day it is added."""
    for marker in POLICY_AMR_MARKERS:
        assert policy_markers([marker]) == frozenset({marker})


def test_what_a_passkey_writes_is_all_on_the_list():
    """A ceremony records the key and the factor, and a rule can ask for
    either — so both have to survive the narrowing."""
    for backed_up in (True, False):
        assert policy_markers(passkey_amr(backed_up=backed_up)) == frozenset(
            passkey_amr(backed_up=backed_up)
        )
