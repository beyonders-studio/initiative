import { useGetAppConfig } from "@/api/generated/config/config";
import type { OptionalConsentCategory } from "@/lib/consent";

/**
 * Runtime config fetched once at boot.
 *
 * The backend serves deployment-specific values (like the optional captcha
 * or billing portal) here because Vite vars are baked into the static
 * bundle at build time and can't change between deployments. One image,
 * many envs.
 *
 * Cached hard, but not forever. Most of these only change when the operator
 * restarts the backend with new env vars, at which point a page reload
 * re-fetches. The community directory is the exception: it is a database
 * setting an owner can change while people are using the app, and everyone
 * else's client has to arrive at the same answer.
 *
 * So the owner's own write invalidates this query (immediate for them), and
 * every other client re-checks when it next comes back to the tab or mounts a
 * consumer — at most once per CONFIG_STALE_MS. That is one small request on
 * returning to a tab, against a config that would otherwise stay wrong until
 * the page was reloaded.
 */
/** How long a client may go on believing what it was told. Long enough that
 *  this is not a poll, short enough that the community directory being
 *  switched on or off reaches an open tab on its own. */
const CONFIG_STALE_MS = 5 * 60 * 1000;

export const useAppConfig = () => {
  const query = useGetAppConfig({
    query: { staleTime: CONFIG_STALE_MS, gcTime: Infinity, retry: 1 },
  });

  return {
    config: query.data,
    isLoading: query.isLoading,
    /** When this is null the deployment has no captcha configured —
     *  the SPA must skip the widget on registration. */
    captcha: query.data?.captcha ?? null,
    /** When this is null the deployment has no billing portal configured —
     *  the SPA hides every tier/upgrade/manage surface (the usage panel,
     *  which shows operator-set caps + usage, renders regardless). */
    billing: query.data?.billing ?? null,
    /** Server-enforced upload size cap, for pre-flight checks. Null until the
     *  config loads — skip the client-side check then; the server still
     *  rejects oversized uploads. */
    maxUploadBytes: query.data?.max_upload_bytes ?? null,
    /** Whether this deployment runs a community directory. False until the
     *  config loads, and false is also the default — every way into the
     *  directory stays hidden unless the platform owner turned it on. */
    communityDirectoryEnabled: query.data?.community_directory_enabled ?? false,
    /** Whether this deployment asks an account to confirm it is 16 or older
     *  before it joins a listed community. True until the config loads, and true is
     *  also the default — the question is the safe thing to ask when we do not
     *  yet know, and the server refuses the join either way. */
    communityAgeGateEnabled: query.data?.community_age_gate_enabled ?? true,
    /** Whether an arriving visitor is asked what this deployment may keep in
     *  their browser. False until the config loads, and false is also the
     *  default — it is a question an owner turns on, not one every deployment
     *  inherits, and a chooser that appears a moment after the page would read
     *  as something having gone wrong. */
    cookieConsentEnabled: query.data?.cookie_consent_enabled ?? false,
    /** The optional cookie categories this deployment actually uses, which is
     *  what the chooser offers a switch for. Empty until the config loads, and
     *  empty is also the common answer — a deployment that uses none of them
     *  asks about none of them. */
    cookieCategories: (query.data?.cookie_categories ?? []) as OptionalConsentCategory[],
    /** Whether this deployment offers direct messages at all. True until the
     *  config loads, and true is also the default — messaging is what most
     *  deployments have, and hiding My Messages for a moment on every boot
     *  would read as it having been taken away. */
    directMessagesEnabled: query.data?.direct_messages_enabled ?? true,
    /** Whether this deployment lets communities have guests. False until the
     *  config loads, and false is also the default: guests are something an
     *  owner turns on. */
    guestsEnabled: query.data?.guests_enabled ?? false,
    /** Whether this deployment orders search by engagement. True until the
     *  config loads, and true is also the default. */
    engagementRankingEnabled: query.data?.engagement_ranking_enabled ?? true,
    /** Whether this deployment permits signing in with a password. True until
     *  the config loads: the form is the thing most deployments have, and the
     *  server refuses either way, so showing it briefly costs nothing while
     *  hiding it briefly would look like an outage. */
    passwordLoginEnabled: query.data?.login_methods?.includes("password") ?? true,
    /** Whether this deployment permits single sign-on at all. The provider
     *  listing is already empty when it does not, so this is for copy that has
     *  to explain the absence rather than for hiding buttons. */
    ssoLoginEnabled: query.data?.login_methods?.includes("sso") ?? true,
    /** Whether this deployment permits signing in with a passkey. False until
     *  the config loads, and the other way round from the password form: a
     *  button that turns up a moment late reads better than one that was there
     *  and then vanished, and the browser has its own say besides. */
    passkeyLoginEnabled: query.data?.login_methods?.includes("passkey") ?? false,
    /** Whether this deployment offers a second factor of any kind. What a
     *  community's own requirement is offered against: with none permitted
     *  here there is nothing to be asked to hold, so the question is not put. */
    secondFactorAvailable:
      (query.data?.login_methods?.includes("totp") ?? false) ||
      (query.data?.login_methods?.includes("passkey") ?? false),
    /** Whether this deployment permits a one-time code sent to an address.
     *  False until the config loads, like the passkey button and for the same
     *  reason — and false is the default here too: it is the one way in an
     *  operator turns on rather than one they inherit. */
    emailOtpLoginEnabled: query.data?.login_methods?.includes("email_otp") ?? false,
    /** Whether signing in here ever asks for an authenticator code. It is
     *  asked after a password or an emailed code, and only while the
     *  authenticator app is permitted; a passkey or single sign-on never asks
     *  for it. False until the config loads, so staff are not offered to clear
     *  a code nothing is asking for. */
    authenticatorAskedAtSignIn:
      (query.data?.login_methods?.includes("totp") ?? false) &&
      ((query.data?.login_methods?.includes("password") ?? false) ||
        (query.data?.login_methods?.includes("email_otp") ?? false)),
  };
};
