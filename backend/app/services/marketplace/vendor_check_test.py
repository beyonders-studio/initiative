"""Which saves ask the vendor: the values a vendor check reads."""

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


def test_a_check_reads_what_it_signs_with_and_names():
    assert reads(_check("response.body.name = vendor.app_name"), every=EVERY) == {
        "app_id",
        "app_name",
        "private_key",
    }


def test_a_check_that_reads_vendor_any_other_way_reads_every_value():
    for holds in (
        "response.body.name = $lookup(vendor, 'app_name')",
        "$count($keys(vendor)) > 0",
        "vendor[app_name = 'x'].app_id",
    ):
        assert reads(_check(holds), every=EVERY) == EVERY, holds


def test_a_value_named_under_another_root_is_not_the_vendors():
    assert reads(_check("response.vendor.hook_secret = 'x'"), every=EVERY) == {
        "app_id",
        "private_key",
    }
