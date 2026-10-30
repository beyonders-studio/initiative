"""The families in ``app.db.user_columns`` describe the real table.

Cheap, catalog-free checks: the registry is the thing the migrations and the
invariant tests are compared against, so it has to name columns that exist and
keep the account's own half out by construction.
"""

from app.db.user_columns import (
    PRIVATE_COLUMNS,
    PUBLISHED_COLUMNS,
    all_user_columns,
)


def test_every_named_column_exists_on_the_model():
    """A family that names a column the table does not have would render a
    view that cannot be created."""
    unknown = PUBLISHED_COLUMNS - all_user_columns()
    assert not unknown, f"user_columns names columns users does not have: {unknown}"


def test_the_families_do_not_publish_the_account():
    """The canary. Credentials, addresses, the session counter and the
    notification settings are the account rather than the person, and a family
    that grew to include one would publish it everywhere both views are read.
    """
    account_only = {
        "hashed_password",
        "token_version",
        "role",
        "age_confirmed_at",
        "locale",
        "timezone",
    }
    published = account_only & PUBLISHED_COLUMNS
    assert not published, f"these are not public: {sorted(published)}"
    assert account_only <= PRIVATE_COLUMNS


def test_a_new_column_is_private_until_it_is_named():
    """``PRIVATE_COLUMNS`` is derived, not listed, so the default for anything
    added to the model is 'not published'."""
    assert PRIVATE_COLUMNS == all_user_columns() - PUBLISHED_COLUMNS
    assert not PRIVATE_COLUMNS & PUBLISHED_COLUMNS
