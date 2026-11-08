import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import type { CaptchaConfig } from "@/api/generated/initiativeAPI.schemas";
import { useServer } from "@/hooks/useServer";
import { captchaProvider } from "@/lib/captchaProviders";
import { useFrameMessages } from "@/ui/lib/useFrameMessages";

/**
 * Single captcha widget that swaps between hCaptcha, Cloudflare
 * Turnstile and Google reCAPTCHA based on the runtime config served
 * by ``GET /api/v1/config``. Only one provider is active per
 * deployment — the one the operator configured via
 * ``CAPTCHA_PROVIDER``.
 *
 * The provider's JS is loaded on demand (a single ``<script>`` tag
 * appended to ``<head>`` once per page load, deduped by URL) so the
 * default OSS deployment with no captcha never pulls vendor JS.
 *
 * On a successful solve the widget calls ``onToken(token)``; on
 * expiry / error / reset it calls ``onToken("")`` so the parent form
 * can re-disable submit. The parent owns the token state — this
 * component is a pure render adapter.
 *
 * In the phone and desktop apps the page is served from the device, an
 * address no provider's site key names, so there the widget is drawn by a
 * page the server serves (``/config/captcha``) and framed here.
 */

interface CaptchaWidgetProps {
  config: CaptchaConfig;
  onToken: (token: string) => void;
}

interface ProviderRenderApi {
  /** Each SDK exposes a ``render(container, opts)`` that returns an
   *  opaque widget id; we hold on to it for the cleanup path. */
  render: (
    container: HTMLElement,
    opts: {
      sitekey: string;
      callback: (token: string) => void;
      "expired-callback"?: () => void;
      "error-callback"?: () => void;
    }
  ) => string | number;
  /** Reset the rendered widget by id. All three SDKs ship this. */
  reset: (widgetId?: string | number) => void;
}

type WindowWithCaptchas = Window & {
  hcaptcha?: ProviderRenderApi;
  turnstile?: ProviderRenderApi;
  grecaptcha?: ProviderRenderApi;
};

const getProviderApi = (provider: string): ProviderRenderApi | undefined => {
  const w = window as WindowWithCaptchas;
  if (provider === "hcaptcha") return w.hcaptcha;
  if (provider === "turnstile") return w.turnstile;
  if (provider === "recaptcha") return w.grecaptcha;
  return undefined;
};

/** Inject the provider script once per page-load. Subsequent calls
 *  resolve immediately if the SDK global is already present.
 *
 *  On a network failure we remove the failed ``<script>`` element so
 *  a re-mount (e.g. after the user navigates away and back, or
 *  after a CDN blip clears) re-attempts the fetch. Without that
 *  cleanup the dedup check below would short-circuit and the poll
 *  loop would spend its 5 s window waiting for a global that's
 *  never going to attach. */
const loadScript = (url: string): Promise<void> =>
  new Promise((resolve, reject) => {
    if (document.querySelector(`script[data-captcha-src="${url}"]`)) {
      resolve();
      return;
    }
    const el = document.createElement("script");
    el.src = url;
    el.async = true;
    el.defer = true;
    el.dataset.captchaSrc = url;
    el.onload = () => resolve();
    el.onerror = () => {
      el.remove();
      reject(new Error(`Failed to load captcha script: ${url}`));
    };
    document.head.appendChild(el);
  });

const InlineCaptcha = ({ config, onToken }: CaptchaWidgetProps) => {
  const { t } = useTranslation("auth");
  const containerRef = useRef<HTMLDivElement | null>(null);
  const widgetIdRef = useRef<string | number | null>(null);
  const [error, setError] = useState<"loadFailed" | "timeout" | null>(null);

  useEffect(() => {
    let cancelled = false;
    const scriptUrl = captchaProvider(config.provider)?.scriptUrl;
    if (!scriptUrl) {
      // Unknown provider name — should be impossible because the
      // backend filters to the supported list, but bail out cleanly.
      console.error(`Unknown captcha provider: ${config.provider}`);
      setError("loadFailed");
      return;
    }

    loadScript(scriptUrl)
      .then(() => {
        // Poll for the SDK to finish initialising. ``script.onload``
        // can fire a tick before the global is observable, and for
        // Google reCAPTCHA there's a longer gap: ``window.grecaptcha``
        // is set to a small bootstrap object with only ``.ready``
        // before the rest of the SDK loads, and ``.render`` only
        // attaches once initialisation finishes. Wait for ``.render``
        // specifically so we don't race that gap.
        const start = Date.now();
        const poll = () => {
          if (cancelled) return;
          const api = getProviderApi(config.provider);
          if (api && typeof api.render === "function") {
            if (!containerRef.current) return;
            try {
              widgetIdRef.current = api.render(containerRef.current, {
                sitekey: config.site_key,
                callback: (token: string) => onToken(token),
                "expired-callback": () => onToken(""),
                "error-callback": () => onToken(""),
              });
            } catch (renderErr) {
              console.error(renderErr);
              setError("loadFailed");
            }
            return;
          }
          if (Date.now() - start > 5000) {
            setError("timeout");
            return;
          }
          window.setTimeout(poll, 50);
        };
        poll();
      })
      .catch((scriptErr: Error) => {
        if (cancelled) return;
        console.error(scriptErr);
        setError("loadFailed");
      });

    return () => {
      cancelled = true;
      const api = getProviderApi(config.provider);
      if (api && widgetIdRef.current !== null) {
        try {
          api.reset(widgetIdRef.current);
        } catch {
          // Best effort — provider SDKs sometimes throw on reset of
          // an already-removed widget. Nothing actionable for the user.
        }
      }
      widgetIdRef.current = null;
    };
  }, [config.provider, config.site_key, onToken]);

  if (error) {
    return <p className="text-destructive text-sm">{t(`captcha.${error}`)}</p>;
  }

  return <div ref={containerRef} />;
};

/** How long the server's captcha page has to draw its widget. */
const FRAME_TIMEOUT_MS = 10_000;

/** The tallest the captcha frame grows to fit what its page reports. */
const MAX_FRAME_HEIGHT = 800;

interface CaptchaFrameProps {
  src: string;
  /** The server's origin, the only one whose messages are read. */
  origin: string;
  onToken: (token: string) => void;
}

const CaptchaFrame = ({ src, origin, onToken }: CaptchaFrameProps) => {
  const { t } = useTranslation("auth");
  const frameRef = useRef<HTMLIFrameElement | null>(null);
  const [height, setHeight] = useState<number | null>(null);
  const [timedOut, setTimedOut] = useState(false);

  useFrameMessages(frameRef, origin, (data) => {
    const message = data as { type?: unknown; height?: unknown; token?: unknown } | null;
    if (message?.type !== "initiative-captcha") return;
    if (typeof message.height === "number") setHeight(Math.min(message.height, MAX_FRAME_HEIGHT));
    if (typeof message.token === "string") onToken(message.token);
  });

  useEffect(() => {
    if (height !== null) return;
    const timer = window.setTimeout(() => setTimedOut(true), FRAME_TIMEOUT_MS);
    return () => window.clearTimeout(timer);
  }, [height]);

  if (timedOut && height === null) {
    return <p className="text-destructive text-sm">{t("captcha.timeout")}</p>;
  }

  return (
    <iframe
      ref={frameRef}
      src={src}
      title={t("captcha.frameTitle")}
      className="w-full border-0"
      style={{ height: height ?? 0 }}
    />
  );
};

export const CaptchaWidget = ({ config, onToken }: CaptchaWidgetProps) => {
  const { isNativePlatform, serverUrl, getServerOrigin } = useServer();
  const origin = getServerOrigin();
  if (isNativePlatform && serverUrl && origin) {
    return <CaptchaFrame src={`${serverUrl}/config/captcha`} origin={origin} onToken={onToken} />;
  }
  return <InlineCaptcha config={config} onToken={onToken} />;
};
