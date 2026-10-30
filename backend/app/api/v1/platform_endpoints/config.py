"""Runtime configuration endpoint.

The SPA fetches this on boot to learn deployment-specific settings that
can't be baked into the static build (Vite vars are compile-time). The
response is intentionally narrow — only public-safe values that affect
UI surfacing.

Unauthenticated: the SPA needs this before any user is logged in.
"""

import json
import secrets
from string import Template
from typing import Optional

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from app.api.deps import SessionDep
from app.core.cookie_categories import active_cookie_categories
from app.core.config import (
    CAPACITOR_NATIVE_ORIGINS,
    captcha_frame_content_security_policy,
    settings,
)
from app.core.security import (
    billing_insights_handoff_enabled,
    billing_support_handoff_enabled,
)
from app.services.platform.billing import billing_managed
from app.core.version import get_min_desktop_version, get_min_native_version
from app.services import captcha as captcha_service
from app.services.platform import app_settings as app_settings_service
from app.services.platform import rules
from app.services.platform import auth_posture
from app.services.tenant.attachments import MAX_FILE_SIZE

router = APIRouter()


class CaptchaConfig(BaseModel):
    """Public-safe captcha settings the SPA needs to render a widget.

    Only the provider name and the (public) site key are exposed —
    the secret key stays server-side. ``None`` (i.e. the surrounding
    ``AppConfig.captcha`` field is null) means the deployment has no
    captcha configured and the SPA shouldn't render a widget at all.
    Mirrors the silent-disable behaviour of the verifier in
    ``app.services.captcha``.
    """

    provider: str  # "hcaptcha" | "turnstile" | "recaptcha"
    site_key: str


class BillingConfig(BaseModel):
    """Public link-out to an external billing portal.

    When ``BILLING_URL`` is unset on the backend (the default) this whole
    field is ``None`` and the SPA shows no tier label, upgrade, or
    manage-billing UI. The usage panel (caps + usage, all operator-set
    numbers) renders regardless. Only the base URL crosses.
    """

    url: str
    # Whether the operator route into the portal is wired up. The operator
    # dashboard's Communities tab hides its billing control when false rather
    # than offering one whose every click fails. Independent of ``url`` — the
    # guild-admin link-out works without it.
    operator_handoff: bool = False
    # Whether the billing service sets each community's caps and
    # entitlements. The Guilds tab then shows them read-only and offers only
    # a suspension as a status change.
    manages_plans: bool = False
    # Whether the billing service's insights page can be opened from here:
    # the operator dashboard's Billing tab shows its button only then.
    insights: bool = False
    # The same for its contracts console, its owner directory and Control:
    # the same key opens them.
    contracts: bool = False
    directory: bool = False
    control: bool = False


class AppConfig(BaseModel):
    """Public, runtime-injected configuration consumed by the SPA at boot."""

    captcha: Optional[CaptchaConfig] = None
    billing: Optional[BillingConfig] = None
    # Where the SPA sends page views, errors and Web Vitals, once a browser
    # has granted the ``analytics`` category. ``None`` (the default) ⇒ the SPA
    # loads no measurement at all.
    faro_collector_url: Optional[str] = None
    # Whether the SPA reports each page it opens to ``/page-views``. True only
    # where Prometheus reads the counts (``METRICS_TOKEN`` is set).
    count_page_views: bool = False
    # The most a file sent with one request may be. The SPA reads it before
    # reading an import file in the browser; a file sent in pieces has no cap
    # but the community's storage.
    max_upload_bytes: int
    # Whether this deployment runs a community directory (owner-set, default
    # off). The SPA hides every way into it when false — the way in from the
    # guild rail, the directory page itself, and a guild admin's listing
    # control. Unlike the fields above this one is a database setting rather
    # than an env var, so it changes without a redeploy.
    community_directory_enabled: bool
    # Whether this deployment asks an account to confirm it is 16 or older
    # before it joins a listed guild. The SPA reads it to decide whether the
    # directory's Join button asks first; the server refuses either way, so
    # this is which question gets asked and not whether the rule applies.
    community_age_gate_enabled: bool
    # Whether this deployment offers direct messages at all. The SPA hides My
    # Messages and every way into it when false -- the rail, the bottom bar, the
    # command palette and the per-person message controls. A database setting
    # like the two above, so it changes without a redeploy.
    direct_messages_enabled: bool
    # Whether this deployment lets communities have guests at all. The SPA
    # shows nothing about guests when false. A database setting like the ones
    # above.
    guests_enabled: bool
    # Whether this deployment orders search by engagement at all. The SPA
    # offers a person the switch to leave their own activity out only while
    # this is on: off, there is nothing for it to leave out of. A database
    # setting like the ones above.
    engagement_ranking_enabled: bool
    # Whether an arriving visitor is asked what this deployment may keep in
    # their browser. Off by default, and unauthenticated by necessity -- the
    # question is put to somebody who has not signed in and may never do so. A
    # database setting like the three above, so it changes without a redeploy.
    cookie_consent_enabled: bool
    # The deployment's accent colours, owner-set on the branding page. Public
    # because the SPA paints them before anybody signs in.
    light_accent_color: str
    dark_accent_color: str
    # The optional cookie categories this deployment actually uses, which is
    # what the chooser offers a switch for. Empty where it uses none, and the
    # chooser then states what is essential rather than asking about nothing.
    # Derived from configuration at request time, not stored -- see
    # ``app.core.cookie_categories``.
    cookie_categories: list[str]
    # The ways in this deployment permits. The login page reads it to decide
    # whether to render the password form at all; the server refuses either
    # way, so this only decides what is offered. Unauthenticated by necessity —
    # it is needed before anybody can sign in.
    login_methods: list[str]
    # The newest native app (APK) release this server's web bundle runs on —
    # the release CI attached an APK to, so the landing page can offer that
    # download by version without asking anybody's release listing.
    min_native_version: str
    # The same for the desktop app: the release its installers are attached to.
    min_desktop_version: str


@router.get("/config", response_model=AppConfig)
async def get_app_config(session: SessionDep) -> AppConfig:
    # Captcha: exposed only when provider, site key and secret are all
    # present and the provider is one we recognise. The SPA treats a missing
    # ``captcha`` field as "no captcha for this deployment" and skips the
    # widget.
    #
    # Asked of ``app.services.captcha`` rather than answered again here. The
    # predicate used to be duplicated in this endpoint, which is how the
    # config half and the verifier half could disagree -- a widget rendered
    # against a secret that no longer verifies, or none rendered while
    # registration demands one. One function, one answer, and it reads the
    # settings row rather than the environment.
    captcha: Optional[CaptchaConfig] = None
    public_captcha = await captcha_service.public_config()
    if public_captcha is not None:
        captcha = CaptchaConfig(provider=public_captcha[0], site_key=public_captcha[1])

    # Billing portal link-out: exposed only when the operator configured a
    # billing URL. Absent ⇒ the SPA hides every tier/upgrade/manage surface.
    billing = (
        BillingConfig(
            url=settings.BILLING_URL,
            operator_handoff=billing_support_handoff_enabled(),
            manages_plans=billing_managed(),
            insights=billing_insights_handoff_enabled(),
            contracts=billing_insights_handoff_enabled(),
            directory=billing_insights_handoff_enabled(),
            control=billing_insights_handoff_enabled(),
        )
        if settings.BILLING_URL
        else None
    )

    app_settings = await app_settings_service.get_app_settings(session)
    stored = await rules.platform_values(session)

    return AppConfig(
        captcha=captcha,
        billing=billing,
        faro_collector_url=settings.FARO_COLLECTOR_URL,
        count_page_views=settings.METRICS_TOKEN is not None,
        max_upload_bytes=MAX_FILE_SIZE,
        community_directory_enabled=stored["community_directory_enabled"],
        community_age_gate_enabled=stored["community_age_gate_enabled"],
        direct_messages_enabled=stored["direct_messages_enabled"],
        guests_enabled=stored["guests_enabled"],
        engagement_ranking_enabled=stored["engagement_ranking_enabled"],
        cookie_consent_enabled=stored["cookie_consent_enabled"],
        light_accent_color=app_settings.light_accent_color,
        dark_accent_color=app_settings.dark_accent_color,
        cookie_categories=[c.value for c in active_cookie_categories(settings)],
        login_methods=sorted(
            m.value for m in auth_posture.methods_from_row(app_settings)
        ),
        min_native_version=get_min_native_version(),
        min_desktop_version=get_min_desktop_version(),
    )


#: The page the phone and desktop apps frame to show the captcha. Their own
#: pages are served from the device, which no provider's site key names, so
#: the widget is drawn here, on this server's own address, and hands its token
#: up to the app.
_CAPTCHA_FRAME = Template("""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>html, body { margin: 0; background: transparent; }</style>
</head>
<body>
<div id="widget"></div>
<script type="application/json" id="captcha">$config</script>
<script nonce="$nonce">
(function () {
  var config = JSON.parse(document.getElementById("captcha").textContent);
  var send = function (message) {
    message.type = "initiative-captcha";
    config.parents.forEach(function (origin) {
      window.parent.postMessage(message, origin);
    });
  };
  var height = 0;
  // The lowest edge of what the page holds, so the frame shrinks again once
  // a challenge closes. A provider hides a closed one above the page.
  var measure = function () {
    var next = 0;
    Array.prototype.forEach.call(document.body.children, function (element) {
      next = Math.max(next, Math.ceil(element.getBoundingClientRect().bottom));
    });
    if (next !== height) {
      height = next;
      send({ height: height });
    }
  };
  var token = function (value) {
    send({ token: value });
  };
  var render = function () {
    var api = {
      hcaptcha: window.hcaptcha,
      turnstile: window.turnstile,
      recaptcha: window.grecaptcha
    }[config.provider];
    if (!api || typeof api.render !== "function") {
      window.setTimeout(render, 50);
      return;
    }
    api.render(document.getElementById("widget"), {
      sitekey: config.siteKey,
      callback: token,
      "expired-callback": function () { token(""); },
      "error-callback": function () { token(""); }
    });
    new MutationObserver(measure).observe(document.body, {
      childList: true,
      subtree: true,
      attributes: true
    });
    measure();
  };
  render();
})();
</script>
<script src="$script" async nonce="$nonce"></script>
</body>
</html>
""")


@router.get("/config/captcha", include_in_schema=False)
async def get_captcha_frame() -> HTMLResponse:
    public_captcha = await captcha_service.public_config()
    if public_captcha is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    provider, site_key = public_captcha
    nonce = secrets.token_urlsafe(16)
    config = json.dumps(
        {"provider": provider, "siteKey": site_key, "parents": CAPACITOR_NATIVE_ORIGINS}
    ).replace("<", "\\u003c")
    page = _CAPTCHA_FRAME.substitute(
        config=config, nonce=nonce, script=captcha_service.SCRIPT_URLS[provider]
    )
    return HTMLResponse(
        page,
        headers={
            "Content-Security-Policy": captcha_frame_content_security_policy(
                provider, nonce
            ),
            "Cache-Control": "no-store",
        },
    )
