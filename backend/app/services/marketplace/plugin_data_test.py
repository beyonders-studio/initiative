"""The bounds around one upstream call, and the parameter contract.

Everything here is driven by an injected `httpx2.MockTransport`, so nothing
touches the network. What it pins is the part of the proxy that has to hold when
a plug-in misbehaves rather than merely being absent: a response that never ends, a
response far too large, a response that is not JSON, and a response that is JSON
but not data. All four are the *plug-in* failing, and all four have to come back as
one named code — a dashboard tile, not a server fault.

The parameter tests are the other half of the same idea. A source's
``params_schema`` is the whole of what a widget may vary, so anything outside it
is refused here rather than forwarded for the plug-in to puzzle over.
"""

import json

import httpx2
import pytest

from app.core.messages import PluginDataMessages
from app.services.marketplace import plugin_data as service
from app.services.marketplace.registration_lookup import (
    RegistrationSnapshot,
    service_public_id,
)

URL = "http://127.0.0.1:9100/v1/endpoints"

ORDERS = "plugin.acme.shop.orders"

SOURCE = {
    "id": ORDERS,
    "direction": "read",
    "cache_ttl_seconds": 60,
    "params": [
        {"key": "range", "type": "select", "options": ["7d", "30d"], "label": {}},
        {"key": "limit", "type": "int", "label": {}},
        {"key": "team", "type": "string", "label": {}},
        {"key": "detailed", "type": "bool", "label": {}},
        {"key": "callback", "type": "url", "label": {}},
    ],
    "returns": [
        {"key": "ids", "type": "int", "list": True},
        {"key": "titles", "type": "string", "list": True},
        {"key": "count", "type": "int"},
        {"key": "unavailable", "type": "string"},
    ],
}


async def _read(handler, endpoint=SOURCE) -> tuple[list, dict]:
    return await service._read_answer(
        httpx2.Request("POST", URL),
        endpoint=endpoint,
        transport=httpx2.MockTransport(handler),
    )


# --- what a plug-in may answer with --------------------------------------------


def _answer(result) -> dict:
    """What a plug-in answers a call with: what it ran, whose credential ran it,
    and the result. The declared returns are one level in."""
    return {"endpoint": ORDERS, "actor": "member", "result": result}


class TestUpstreamBounds:
    async def test_an_answer_is_read_through_the_endpoints_returns(self):
        rows, values = await _read(
            lambda request: httpx2.Response(
                200,
                json=_answer({"ids": [1, 2], "titles": ["a", "b"], "count": 2}),
            )
        )
        assert rows == [{"ids": 1, "titles": "a"}, {"ids": 2, "titles": "b"}]
        assert values == {"count": 2}

    async def test_an_answer_without_a_result_is_the_plugin_being_unavailable(self):
        # From a dashboard's side "this plug-in is not answering" is true whether
        # the service is down or talking a shape this build does not accept.
        with pytest.raises(service.PluginDataError) as excinfo:
            await _read(
                lambda request: httpx2.Response(200, json={"rows": [{"id": 1}]})
            )
        assert excinfo.value.code == PluginDataMessages.SERVICE_UNAVAILABLE

    async def test_a_response_past_the_ceiling_is_abandoned(self):
        oversized = "x" * (service.MAX_RESPONSE_BYTES + 1024)
        with pytest.raises(service.PluginDataError) as excinfo:
            await _read(
                lambda request: httpx2.Response(
                    200, json=_answer({"titles": [oversized]})
                )
            )
        assert excinfo.value.code == PluginDataMessages.RESPONSE_TOO_LARGE
        assert excinfo.value.status_code == 502

    async def test_a_response_that_never_arrives_is_the_plugin_being_unavailable(self):
        def _stall(request: httpx2.Request) -> httpx2.Response:
            raise httpx2.ReadTimeout("timed out", request=request)

        with pytest.raises(service.PluginDataError) as excinfo:
            await _read(_stall)
        assert excinfo.value.code == PluginDataMessages.SERVICE_UNAVAILABLE
        assert excinfo.value.status_code == 502

    async def test_a_refused_connection_is_the_plugin_being_unavailable(self):
        def _refuse(request: httpx2.Request) -> httpx2.Response:
            raise httpx2.ConnectError("refused", request=request)

        with pytest.raises(service.PluginDataError) as excinfo:
            await _read(_refuse)
        assert excinfo.value.code == PluginDataMessages.SERVICE_UNAVAILABLE

    @pytest.mark.parametrize("status", [400, 401, 404, 500, 503])
    async def test_an_error_status_is_not_passed_through_as_data(self, status):
        with pytest.raises(service.PluginDataError) as excinfo:
            await _read(lambda request: httpx2.Response(status, json=_answer({})))
        assert excinfo.value.code == PluginDataMessages.SERVICE_UNAVAILABLE

    async def test_a_body_that_is_not_json_is_refused(self):
        with pytest.raises(service.PluginDataError) as excinfo:
            await _read(
                lambda request: httpx2.Response(
                    200,
                    text="<html>hello</html>",
                    headers={"content-type": "text/html"},
                )
            )
        assert excinfo.value.code == PluginDataMessages.SERVICE_UNAVAILABLE

    @pytest.mark.parametrize(
        "body", [{"data": []}, {"result": [1, 2]}, [1, 2, 3], "result", 7]
    )
    async def test_json_that_is_not_a_data_response_is_refused(self, body):
        with pytest.raises(service.PluginDataError) as excinfo:
            await _read(lambda request: httpx2.Response(200, json=body))
        assert excinfo.value.code == PluginDataMessages.SERVICE_UNAVAILABLE

    async def test_the_timeout_is_the_documented_budget(self):
        """A dashboard is a display surface: a source that cannot answer in five
        seconds is not going to render usefully."""
        assert service.REQUEST_TIMEOUT_SECONDS == 5.0
        assert service.MAX_RESPONSE_BYTES == 1024 * 1024


# --- reading an answer through what was declared ------------------------------


def _returns(*declared) -> dict:
    return {"id": ORDERS, "direction": "read", "returns": list(declared)}


class TestReadingAnAnswerThroughItsReturns:
    """The manifest says what an endpoint hands back; that is how it is read.

    A widget binds a return before the endpoint has ever run, so the declaration
    and the projection are the same document — a plug-in sends the keys it named,
    and these pin what each kind of return becomes.
    """

    def test_lists_are_read_side_by_side(self):
        """The third entry of each list describes the same third thing."""
        rows, _ = service.project_returns(
            {"ids": [1, 2, 3], "titles": ["a", "b", "c"]},
            _returns(
                {"key": "ids", "type": "int", "list": True},
                {"key": "titles", "type": "string", "list": True},
            ),
        )
        assert rows == [
            {"ids": 1, "titles": "a"},
            {"ids": 2, "titles": "b"},
            {"ids": 3, "titles": "c"},
        ]

    def test_a_single_value_describes_the_answer_rather_than_an_item(self):
        rows, values = service.project_returns(
            {"ids": [1, 2], "total": 97},
            _returns(
                {"key": "ids", "type": "int", "list": True},
                {"key": "total", "type": "int"},
            ),
        )
        assert rows == [{"ids": 1}, {"ids": 2}]
        assert values == {"total": 97}

    def test_an_empty_set_still_carries_what_the_answer_says_about_itself(self):
        """No rows and a total of nought are both true at once, and a tile
        drawing the number needs the second one."""
        rows, values = service.project_returns(
            {"ids": [], "total": 0, "unavailable": "no account connected"},
            _returns(
                {"key": "ids", "type": "int", "list": True},
                {"key": "total", "type": "int"},
                {"key": "unavailable", "type": "string"},
            ),
        )
        assert rows == []
        assert values == {"total": 0, "unavailable": "no account connected"}

    def test_a_key_the_endpoint_does_not_declare_is_left_out(self):
        rows, values = service.project_returns(
            {"ids": [1], "secrets": ["shh"], "note": "hello"},
            _returns({"key": "ids", "type": "int", "list": True}),
        )
        assert rows == [{"ids": 1}]
        assert values == {}

    def test_a_declared_key_the_plugin_did_not_send_is_simply_absent(self):
        rows, values = service.project_returns(
            {"ids": [1]},
            _returns(
                {"key": "ids", "type": "int", "list": True},
                {"key": "titles", "type": "string", "list": True},
                {"key": "total", "type": "int"},
            ),
        )
        assert rows == [{"ids": 1}]
        assert values == {}

    def test_columns_of_different_lengths_do_not_invent_entries(self):
        """The longest list decides how many things were answered about; a
        shorter one runs out rather than padding."""
        rows, _ = service.project_returns(
            {"ids": [1, 2, 3], "titles": ["a"]},
            _returns(
                {"key": "ids", "type": "int", "list": True},
                {"key": "titles", "type": "string", "list": True},
            ),
        )
        assert rows == [{"ids": 1, "titles": "a"}, {"ids": 2}, {"ids": 3}]

    def test_a_declared_list_that_arrived_as_one_value_describes_no_set(self):
        rows, values = service.project_returns(
            {"ids": 7, "total": 1},
            _returns(
                {"key": "ids", "type": "int", "list": True},
                {"key": "total", "type": "int"},
            ),
        )
        assert rows == []
        assert values == {"total": 1}

    def test_an_endpoint_declaring_nothing_hands_a_widget_nothing(self):
        rows, values = service.project_returns(
            {"anything": [1, 2], "at": "all"}, {"id": ORDERS, "direction": "read"}
        )
        assert rows == []
        assert values == {}

    def test_values_are_carried_as_the_plugin_sent_them(self):
        """Read by name, never interpreted: a nested value is data on its way to
        a sandbox that is handed it as data."""
        nested = {"deep": [1, {"deeper": True}]}
        rows, values = service.project_returns(
            {"blobs": [nested], "shape": nested},
            _returns(
                {"key": "blobs", "type": "string", "list": True},
                {"key": "shape", "type": "string"},
            ),
        )
        assert rows == [{"blobs": nested}]
        assert values == {"shape": nested}


# --- parameters --------------------------------------------------------------


class TestParams:
    def test_no_parameters_is_an_empty_canonical_form(self):
        for raw in (None, "", "   ", "{}"):
            values, canonical = service.validate_params(SOURCE, raw)
            assert values == {}
            assert canonical == "{}"

    def test_declared_values_are_rendered_for_the_wire(self):
        values, _ = service.validate_params(
            SOURCE,
            json.dumps(
                {
                    "range": "30d",
                    "limit": 5,
                    "team": " platform ",
                    "detailed": True,
                    "callback": "https://example.test/hook",
                }
            ),
        )
        assert values == {
            "range": "30d",
            "limit": "5",
            "team": "platform",
            "detailed": "true",
            "callback": "https://example.test/hook",
        }

    def test_the_canonical_form_is_order_independent(self):
        _, first = service.validate_params(
            SOURCE, json.dumps({"range": "7d", "limit": 1})
        )
        _, second = service.validate_params(
            SOURCE, json.dumps({"limit": 1, "range": "7d"})
        )
        assert first == second

    @pytest.mark.parametrize(
        "raw",
        [
            '{"unknown": "x"}',
            '{"range": "90d"}',
            '{"range": 7}',
            '{"limit": "5"}',
            '{"limit": true}',
            '{"detailed": "yes"}',
            '{"callback": "javascript:alert(1)"}',
            '{"callback": "ftp://example.test"}',
            '{"team": ""}',
            "[]",
            "null",
            "not json",
        ],
    )
    def test_anything_outside_the_schema_is_refused(self, raw):
        with pytest.raises(service.PluginDataError) as excinfo:
            service.validate_params(SOURCE, raw)
        assert excinfo.value.code == PluginDataMessages.INVALID_PARAMS
        assert excinfo.value.status_code == 400

    def test_a_required_parameter_left_out_is_refused(self):
        source = {
            **SOURCE,
            "params": [
                {"key": "shop", "type": "string", "required": True, "label": {}}
            ],
        }
        with pytest.raises(service.PluginDataError):
            service.validate_params(source, None)
        values, _ = service.validate_params(source, '{"shop": "acme"}')
        assert values == {"shop": "acme"}

    def test_an_oversized_parameter_object_is_refused_before_parsing(self):
        raw = json.dumps({"team": "x" * (service.MAX_PARAMS_BYTES + 10)})
        with pytest.raises(service.PluginDataError) as excinfo:
            service.validate_params(SOURCE, raw)
        assert excinfo.value.code == PluginDataMessages.INVALID_PARAMS


# --- reading the pinned definition -------------------------------------------


class TestDefinitionReading:
    def test_a_read_is_found_on_the_pinned_definition(self):
        definition = {"plugin_kind": "service", "endpoints": [SOURCE]}
        assert service.find_read_endpoint(definition, ORDERS) == SOURCE
        assert service.find_read_endpoint(definition, "plugin.acme.shop.other") is None

    def test_only_a_read_is_reachable_from_here(self):
        """A write and an emission are both real endpoints and neither belongs
        on the fetch path: rendering a dashboard must not be a way to make a
        plug-in act."""
        for direction in ("write", "emit"):
            definition = {
                "plugin_kind": "service",
                "endpoints": [{**SOURCE, "direction": direction}],
            }
            assert service.find_read_endpoint(definition, ORDERS) is None

    def test_a_plugin_is_called_over_the_wire_surface(self):
        """A registration may carry two addresses. This one is Initiative's own
        server calling the plug-in, so it uses the address meant for that — the
        browser address is for what a browser opens."""
        registration = RegistrationSnapshot(
            public_id="acme.shop",
            listing_uid=None,
            base_url="http://acme-shop:8200",
            page_origin="https://shop.example.com",
            allowed_origins=(),
            keys={},
            mandatory=False,
            enabled=True,
            live=True,
        )

        assert service._endpoints_url(registration) == (
            "http://acme-shop:8200/v1/endpoints"
        )

    def test_only_a_service_plugin_has_a_backing_service(self):
        assert (
            service_public_id(
                {"plugin_kind": "service", "service": {"public_id": "acme.shop"}}
            )
            == "acme.shop"
        )
        assert service_public_id({"plugin_kind": "tool_instance"}) is None
        assert service_public_id({"plugin_kind": "service"}) is None
        assert service_public_id(None) is None

    def test_the_deployments_ceiling_outranks_the_manifests_request(self):
        """A listing asks for freshness; it does not get to decide it."""
        assert service._effective_ttl({"cache_ttl_seconds": 60}) == 60
        assert (
            service._effective_ttl({"cache_ttl_seconds": 86_400})
            == service.MAX_CACHE_TTL_SECONDS
        )
        assert service._effective_ttl({"cache_ttl_seconds": -5}) == 0
        assert service._effective_ttl({"cache_ttl_seconds": True}) == 0
        assert service._effective_ttl({}) == 0
