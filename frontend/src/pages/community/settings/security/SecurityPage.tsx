import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type { CommunityAuthPolicyRead } from "@/api/generated/initiativeAPI.schemas";
import { SettingsRow, SettingsSection } from "@/components/settings/SettingsSection";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { useAppConfig } from "@/hooks/useAppConfig";
import { useCommunities } from "@/hooks/useCommunities";
import {
  useCommunityAuthSettings,
  useCommunityClaimRules,
  useCommunityProviderConnections,
  useCustomRoleClaimRules,
} from "@/hooks/useCommunityAuthPolicy";
import { Badge } from "@/ui/badge";

import { CommunityAuthProvidersSection } from "./CommunityAuthProvidersSection";
import { CommunityClaimRulesSection } from "./CommunityClaimRulesSection";
import { CommunityOnOffRuleDialog } from "./CommunityOnOffRuleDialog";
import { CommunityPrivacySection } from "./CommunityPrivacySection";
import { CustomRoleClaimRulesSection } from "./CustomRoleClaimRulesSection";
import { GuestStayDialog } from "./GuestStayDialog";
import { SignInRequirementDialog } from "./SignInRequirementDialog";

/** The rules a Sign-in rules row changes, by the setting each one writes. */
type SignInRule =
  | "auth_policy"
  | "require_second_factor"
  | "enforce_compliance_session"
  | "guest_auth_policy"
  | "guest_max_days";

export const SecurityPage = () => {
  const { t } = useTranslation(["settings", "common"]);
  const communityId = useActiveCommunityId();

  // What the operator has granted this community. The sections hang off their
  // own grant and are independent of each other: the providers, the groups
  // and the requirements naming them need ``providers``, the other rules and
  // privacy need ``restrictions``. Outside both the tab is hidden and a direct
  // URL renders nothing (fail closed while still loading).
  const { activeCommunity } = useCommunities();
  // The seat above admin holds a community's sign-in configuration, and this
  // page is all of it — so it is theirs to reach, not only theirs to write.
  // The tab is gated the same way; this is the direct-URL half.
  const isSuperadmin = Boolean(activeCommunity?.can.seat);
  // Every control on the page reads from this one answer.
  const authSettings = useCommunityAuthSettings(communityId, {
    enabled: communityId > 0 && isSuperadmin,
  }).data;
  const grantedOptions = authSettings?.auth_options ?? [];
  const mayConfigureProviders = grantedOptions.includes("providers");
  const mayConfigureRestrictions = grantedOptions.includes("restrictions");
  // Where the deployment allows guests and the community takes them.
  const { guestsEnabled, secondFactorAvailable } = useAppConfig();
  const takesGuests = guestsEnabled && activeCommunity?.max_guests !== 0;
  // A requirement names a provider this community connects to, so the picker
  // reads the same list the providers section edits.
  const connectionsQuery = useCommunityProviderConnections(communityId, {
    enabled: communityId > 0 && mayConfigureProviders,
  });
  const connections = connectionsQuery.data ?? [];
  // A group rule names a provider, so until one is connected there is nothing
  // to write one against; rules already written stay readable regardless,
  // and so do the server's, which can apply with no connection.
  const claimRules = useCommunityClaimRules(communityId, {
    enabled: communityId > 0 && mayConfigureProviders,
  }).data;
  const roleRules = useCustomRoleClaimRules(communityId, {
    enabled: communityId > 0 && mayConfigureProviders,
  }).data;
  const showsGroupRules =
    connections.length > 0 ||
    Boolean(claimRules?.rules.length) ||
    Boolean(claimRules?.provider_rules.length) ||
    Boolean(roleRules?.length);
  // Only a live connection can be required. A disconnected or switched-off
  // one cannot serve a sign-in, and neither can one whose provider the
  // operator has since withdrawn.
  const eligibleProviders = useMemo(
    () =>
      (connectionsQuery.data ?? [])
        .filter((row) => row.enabled && row.login_ready)
        .map((row) => ({
          id: row.provider_id,
          slug: row.provider_slug,
          display_name: row.provider_display_name,
        })),
    [connectionsQuery.data]
  );
  const [changing, setChanging] = useState<SignInRule | null>(null);

  // The page waits for its settings rather than reading "granted nothing" off
  // an answer that has not come back yet.
  if (
    !isSuperadmin ||
    authSettings == null ||
    (!mayConfigureProviders && !mayConfigureRestrictions)
  ) {
    return null;
  }

  const communityName = activeCommunity?.name ?? "";
  // What whoever runs the server sets for this community is shown, not offered.
  const setByDeployment = new Set(authSettings.set_by_deployment);
  // Where the deployment already asks everybody for a second factor, this
  // community's rule has nothing to add. A rule already written stays and
  // comes back into force if the deployment lowers its answer.
  const factorAskedByPlatform = authSettings.auth_policy.factor_required_by_platform;
  const factorRequired = authSettings.require_second_factor || factorAskedByPlatform;
  const sessionLimit = authSettings.enforce_compliance_session;
  const ceiling = authSettings.guest_max_days_by_platform;

  const describePolicy = (policy: CommunityAuthPolicyRead): string => {
    if (policy.policy === "open") return t("communityAuth.policy.openLabel");
    const passkey = policy.require_methods.includes("passkey");
    const provider = policy.provider_display_name ?? policy.provider_slug;
    if (provider) {
      return passkey
        ? t("communityAuth.policy.value.throughWithPasskey", { provider })
        : t("communityAuth.policy.value.through", { provider });
    }
    if (policy.require_methods.includes("sso")) {
      return passkey
        ? t("communityAuth.policy.value.anyWithPasskey")
        : t("communityAuth.policy.value.any");
    }
    return t("communityAuth.policy.value.passkey");
  };

  const rules: {
    key: SignInRule;
    shown: boolean;
    label: string;
    value: string;
    detail?: string | null;
    fixed?: boolean;
  }[] = [
    {
      key: "auth_policy",
      shown: mayConfigureProviders,
      label: t("communityAuth.signInRules.members"),
      value: describePolicy(authSettings.auth_policy),
    },
    {
      key: "require_second_factor",
      shown: mayConfigureRestrictions && secondFactorAvailable,
      label: t("communityAuth.secondFactor.title"),
      value: factorRequired
        ? t("communityAuth.secondFactor.onLabel")
        : t("communityAuth.secondFactor.offLabel"),
      detail: factorRequired && takesGuests ? t("communityAuth.secondFactor.guestsToo") : null,
      fixed: factorAskedByPlatform,
    },
    {
      key: "enforce_compliance_session",
      shown: mayConfigureRestrictions,
      label: t("communityAuth.sessionLimit.title"),
      value: sessionLimit ? t("settingsSection.on") : t("settingsSection.off"),
      detail: sessionLimit
        ? t("communityAuth.sessionLimit.onDetail")
        : t("communityAuth.sessionLimit.offDetail"),
    },
    {
      key: "guest_auth_policy",
      shown: mayConfigureProviders && takesGuests,
      label: t("communityAuth.signInRules.guests"),
      value: describePolicy(authSettings.guest_auth_policy),
    },
    {
      key: "guest_max_days",
      shown: mayConfigureRestrictions && takesGuests,
      label: t("communityAuth.guestStay.title"),
      value: t("communityAuth.guestStay.value", { count: authSettings.guest_max_days ?? ceiling }),
      detail:
        authSettings.guest_max_days == null
          ? t("communityAuth.guestStay.defaultDetail")
          : t("communityAuth.guestStay.ceilingDetail", { days: ceiling }),
    },
  ];

  // Everybody who opens the community, guests included, is asked for a factor.
  const withoutFactor =
    authSettings.member_figures.without_factor + authSettings.guest_figures.without_factor;
  const people = authSettings.member_figures.total + authSettings.guest_figures.total;
  const closeDialog = (open: boolean) => {
    if (!open) setChanging(null);
  };

  return (
    <div className="space-y-6">
      <p className="text-muted-foreground text-sm">
        {t("communityAuth.intro", { community: communityName })}
      </p>

      <SettingsSection
        title={t("communityAuth.signInRules.title")}
        description={t("communityAuth.signInRules.description", { community: communityName })}
      >
        {rules
          .filter((rule) => rule.shown)
          .map((rule) => {
            const fixed = rule.fixed || setByDeployment.has(rule.key);
            return (
              <SettingsRow
                key={rule.key}
                label={rule.label}
                value={rule.value}
                description={rule.detail}
                action={
                  fixed ? (
                    <Badge variant="secondary">{t("communityAuth.setByServer")}</Badge>
                  ) : undefined
                }
                onChange={fixed ? undefined : () => setChanging(rule.key)}
              />
            );
          })}
      </SettingsSection>

      <SignInRequirementDialog
        communityId={communityId}
        communityName={communityName}
        open={changing === "auth_policy"}
        onOpenChange={closeDialog}
        savedPolicy={authSettings.auth_policy}
        eligibleProviders={eligibleProviders}
        figures={authSettings.member_figures}
      />
      <SignInRequirementDialog
        communityId={communityId}
        communityName={communityName}
        open={changing === "guest_auth_policy"}
        onOpenChange={closeDialog}
        savedPolicy={authSettings.guest_auth_policy}
        eligibleProviders={eligibleProviders}
        figures={authSettings.guest_figures}
        guest
      />
      <CommunityOnOffRuleDialog
        communityId={communityId}
        rule="require_second_factor"
        saved={authSettings.require_second_factor}
        impact={[
          t("communityAuth.secondFactor.impact", { community: communityName }),
          withoutFactor > 0 &&
            t("communityAuth.secondFactor.withoutFactor", { count: withoutFactor, total: people }),
        ]}
        open={changing === "require_second_factor"}
        onOpenChange={closeDialog}
      />
      <CommunityOnOffRuleDialog
        communityId={communityId}
        rule="enforce_compliance_session"
        saved={sessionLimit}
        impact={[t("communityAuth.sessionLimit.impact")]}
        open={changing === "enforce_compliance_session"}
        onOpenChange={closeDialog}
      />
      <GuestStayDialog
        communityId={communityId}
        authSettings={authSettings}
        open={changing === "guest_max_days"}
        onOpenChange={closeDialog}
      />

      {mayConfigureProviders ? (
        <CommunityAuthProvidersSection communityId={communityId} communityName={communityName} />
      ) : null}

      {mayConfigureProviders && showsGroupRules ? (
        <SettingsSection
          title={t("communityAuth.groupRules.title")}
          description={t("communityAuth.groupRules.description")}
        >
          <CommunityClaimRulesSection communityId={communityId} />
          <CustomRoleClaimRulesSection communityId={communityId} />
        </SettingsSection>
      ) : null}

      {mayConfigureRestrictions ? (
        <CommunityPrivacySection
          communityId={communityId}
          communityName={communityName}
          settings={authSettings}
        />
      ) : null}
    </div>
  );
};
