"""Which saves ask the vendor: the values a vendor check reads."""

import pytest

from app.services.marketplace.vendor_check import reads

EVERY = {"app_id", "app_name", "private_key", "hook_secret"}


def _check(*holds: str, url: str = "'https://api.vendor.example/app'") -> dict:
    return {
        "sign": {"iss": "{vendor.app_id}", "key": "{vendor.private_key}"},
        "request": {"method": "GET", "url": url},
        "expect": [
            {"holds": text, "fields": ["app_name"], "message": {"en": "x"}}
            for text in holds
        ],
    }


@pytest.mark.parametrize(
    ("holds", "read"),
    [
        # What it signs with, and the value it names.
        (
            "response.body.name = vendor.app_name",
            {"app_id", "app_name", "private_key"},
        ),
        # Reading vendor any other way reads every value.
        ("response.body.name = $lookup(vendor, 'app_name')", EVERY),
        ("$count($keys(vendor)) > 0", EVERY),
        ("vendor[app_name = 'x'].app_id", EVERY),
        # A value named under another root is not the vendor's.
        ("response.vendor.hook_secret = 'x'", {"app_id", "private_key"}),
    ],
)
def test_a_check_reads_what_it_signs_with_and_names(holds, read):
    assert reads(_check(holds), every=EVERY) == read
