import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import {
  AUTH_FACTOR_REQUIRED_EVENT,
  type CommunityFactorKind,
  type FactorChallengeDetail,
} from "@/api/client";
import { useCommunityLoginProviders } from "@/hooks/useCommunityAuthPolicy";
import { providerSignInHref } from "@/lib/returnPath";
import { Alert, AlertDescription } from "@/ui/alert";
import { Button } from "@/ui/button";

export type EligibleProvider = { id: number; slug: string; display_name: string };

/**
 * What this admin's own session is missing, when saving a rule is refused
 * because it does not meet the rule itself. The server names it; a provider is
 * answered by signing in again, a factor of the account's own by presenting it
 * here.
 */
export type Unmet =
  | { kind: "provider"; slug: string; name: string }
  | { kind: CommunityFactorKind };

/** The two lines each factor needs: what to do, and the button that does it. */
const FACTOR_COPY = {
  totp: {
    line: "communityAuth.policy.unmetFactor",
    button: "communityAuth.policy.presentFactor",
  },
  passkey: {
    line: "communityAuth.policy.unmetPasskey",
    button: "communityAuth.policy.presentPasskey",
  },
} as const;

/**
 * What a refused save says this session is missing, or null when the refusal
 * is about something else. A provider (or "any of ours") is answered by
 * `provider`; a server that names no method, or a provider this page has no
 * name for, leaves the refusal its own line to stand on.
 */
export const readUnmet = (err: unknown, provider?: EligibleProvider): Unmet | null => {
  const response = (
    err as {
      response?: { data?: { detail?: string }; headers?: Record<string, unknown> };
    }
  ).response;
  if (response?.data?.detail !== "AUTH_RULE_SELF_UNSATISFIED") return null;
  // Axios lower-cases header keys.
  const method = response.headers?.["x-auth-policy-unmet"];
  if (method === "totp" || method === "passkey") return { kind: method };
  if ((method === "provider" || method === "sso") && provider) {
    return { kind: "provider", slug: provider.slug, name: provider.display_name };
  }
  return null;
};

/** The way to meet a refused rule from here: sign in through the provider it
 *  names, or present a factor without leaving the page. */
export const UnmetAlert = ({ communityId, unmet }: { communityId: number; unmet: Unmet }) => {
  const { t } = useTranslation("settings");
  // The public listing carries the community-addressed login URLs.
  const loginProviders = useCommunityLoginProviders(communityId, {
    enabled: communityId > 0 && unmet.kind === "provider",
  });

  let line: string;
  let action: ReactNode = null;
  if (unmet.kind === "provider") {
    line = t("communityAuth.policy.selfUnsatisfied", { providerName: unmet.name });
    const entry = loginProviders.data?.providers.find((row) => row.slug === unmet.slug);
    if (entry) {
      // Completing the provider's sign-in adds it to this session, after
      // which saving the rule succeeds.
      action = (
        <Button
          size="sm"
          onClick={() => {
            window.location.href = providerSignInHref(
              entry.login_url,
              `${window.location.pathname}${window.location.search}`
            );
          }}
        >
          {t("communityAuth.policy.signInWith", { providerName: unmet.name })}
        </Button>
      );
    }
  } else {
    const kind = unmet.kind;
    line = t(FACTOR_COPY[kind].line);
    // The same dialog every refused request opens, asked for here so a
    // factor is presented without leaving the rule being written.
    action = (
      <Button
        size="sm"
        onClick={() =>
          window.dispatchEvent(
            new CustomEvent<FactorChallengeDetail>(AUTH_FACTOR_REQUIRED_EVENT, {
              detail: { communityId, kind },
            })
          )
        }
      >
        {t(FACTOR_COPY[kind].button)}
      </Button>
    );
  }

  return (
    <Alert>
      <AlertDescription className="flex flex-wrap items-center justify-between gap-2">
        <span>{line}</span>
        {action}
      </AlertDescription>
    </Alert>
  );
};
