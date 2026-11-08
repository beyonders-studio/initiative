/**
 * How community members may enter this initiative.
 *
 * The policy governs only how a membership row comes to exist — never what a
 * member may then see, which stays with initiative membership and per-resource
 * sharing. Three ways in: closed, open to any community member, or open to anyone
 * who asks and a manager lets in.
 *
 * Auto-join — enrolling every future community member on arrival — is a fourth way
 * in, and it lives here because it is not independent of the policy: it is only
 * valid alongside "anyone can join", and the server refuses the other pairs. It
 * is also a community admin's decision rather than a manager's, since it shapes what
 * the whole community's onboarding does, so it is offered only when the caller
 * passes a handler for it.
 */

import { useTranslation } from "react-i18next";

import { InitiativeJoinPolicy } from "@/api/generated/initiativeAPI.schemas";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/ui/card";
import { Label } from "@/ui/label";
import { RadioGroup, RadioGroupItem } from "@/ui/radio-group";
import { Switch } from "@/ui/switch";

/** Every policy, from the most closed to the most open. */
const SELECTABLE_POLICIES: readonly InitiativeJoinPolicy[] = [
  InitiativeJoinPolicy.private,
  InitiativeJoinPolicy.request,
  InitiativeJoinPolicy.open,
];

export const POLICY_LABEL_KEY: Record<InitiativeJoinPolicy, string> = {
  [InitiativeJoinPolicy.private]: "settings.joinPolicy.privateLabel",
  [InitiativeJoinPolicy.request]: "settings.joinPolicy.requestLabel",
  [InitiativeJoinPolicy.open]: "settings.joinPolicy.openLabel",
};

const POLICY_HELP_KEY: Record<InitiativeJoinPolicy, string> = {
  [InitiativeJoinPolicy.private]: "settings.joinPolicy.privateHelp",
  [InitiativeJoinPolicy.request]: "settings.joinPolicy.requestHelp",
  [InitiativeJoinPolicy.open]: "settings.joinPolicy.openHelp",
};

export interface JoinPolicySectionProps {
  value: InitiativeJoinPolicy;
  onChange: (value: InitiativeJoinPolicy) => void;
  canManage: boolean;
  isSaving: boolean;
  /** "card" (settings, the default) or "plain" for embedding in a form. */
  layout?: "card" | "plain";
  /** Keeps radio ids unique when more than one instance is mounted. */
  idPrefix?: string;
  /** Whether every new community member is enrolled in this initiative on arrival. */
  autoJoin?: boolean;
  /**
   * Change auto-join. Community admins only — omit it for anyone else, who may
   * still set the policy but never this.
   */
  onChangeAutoJoin?: (next: boolean) => void;
}

export const JoinPolicySection = ({
  value,
  onChange,
  canManage,
  isSaving,
  layout = "card",
  idPrefix,
  autoJoin = false,
  onChangeAutoJoin,
}: JoinPolicySectionProps) => {
  const { t } = useTranslation("initiatives");
  const disabled = !canManage || isSaving;
  const radioId = (policy: InitiativeJoinPolicy) =>
    `${idPrefix ? `${idPrefix}-` : ""}join-policy-${policy}`;
  const autoJoinId = `${idPrefix ? `${idPrefix}-` : ""}auto-join`;

  const canSetAutoJoin = Boolean(onChangeAutoJoin);
  const autoJoinAllowed = value === InitiativeJoinPolicy.open;
  // A manager who cannot turn auto-join off is not offered the policies that
  // would be refused while it is on — the server rejects the pair, so the
  // choice would be a save that could only fail.
  const policyLocked = autoJoin && !canSetAutoJoin;

  const radios = (
    <RadioGroup
      value={value}
      onValueChange={(next) => onChange(next as InitiativeJoinPolicy)}
      disabled={disabled}
      className="gap-3"
      aria-label={t("settings.joinPolicy.title")}
    >
      {SELECTABLE_POLICIES.map((policy) => (
        <div key={policy} className="flex items-start gap-3 rounded-md border px-4 py-3">
          <RadioGroupItem
            id={radioId(policy)}
            value={policy}
            disabled={disabled || (policyLocked && policy !== InitiativeJoinPolicy.open)}
            className="mt-1"
          />
          <div className="min-w-0 space-y-0.5">
            <Label htmlFor={radioId(policy)} className="font-medium">
              {t(POLICY_LABEL_KEY[policy] as never)}
            </Label>
            <p className="text-muted-foreground text-xs">{t(POLICY_HELP_KEY[policy] as never)}</p>
          </div>
        </div>
      ))}
    </RadioGroup>
  );

  if (layout === "plain") {
    return radios;
  }

  const autoJoinBlock = canSetAutoJoin ? (
    <div className="mt-4 space-y-2 border-t pt-4">
      <div className="flex items-start gap-3">
        <Switch
          id={autoJoinId}
          checked={autoJoin}
          disabled={disabled || !autoJoinAllowed}
          onCheckedChange={(next) => onChangeAutoJoin?.(next)}
          className="mt-0.5"
        />
        <Label htmlFor={autoJoinId} className="font-medium">
          {t("settings.autoJoin.label")}
        </Label>
      </div>
      {autoJoinAllowed ? (
        <>
          <p className="text-muted-foreground text-sm">{t("settings.autoJoin.help")}</p>
          {/* The thing everyone assumes and nobody is told: it starts from here. */}
          <p className="text-muted-foreground text-sm">{t("settings.autoJoin.notRetroactive")}</p>
        </>
      ) : (
        <p className="text-muted-foreground text-sm">{t("settings.autoJoin.requiresOpen")}</p>
      )}
    </div>
  ) : policyLocked ? (
    <p className="mt-4 border-t pt-4 text-muted-foreground text-sm">
      {t("settings.autoJoin.lockedNote")}
    </p>
  ) : null;

  return (
    <Card className="mt-4">
      <CardHeader>
        <CardTitle>{t("settings.joinPolicy.title")}</CardTitle>
        <CardDescription>{t("settings.joinPolicy.description")}</CardDescription>
      </CardHeader>
      <CardContent>
        {radios}
        {autoJoinBlock}
        {canManage ? null : (
          <p className="mt-3 text-muted-foreground text-sm">{t("settings.editPermissionNote")}</p>
        )}
      </CardContent>
    </Card>
  );
};
