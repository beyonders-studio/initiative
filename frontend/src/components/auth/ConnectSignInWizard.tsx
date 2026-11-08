/**
 * Connecting a sign-in provider, asked one question at a time.
 *
 * A community answers four things, and they are four different kinds of
 * question. Which provider is a recognition — the name is the answer, so it
 * is a grid of marks rather than a dropdown. Which of its accounts are ours
 * is the only one that needs a word from the provider's own vocabulary. Where
 * arrivals land is a pair of defaults somebody may want to change. And
 * whether we insist on it is a decision about everybody else, which is why it
 * comes last and starts off.
 *
 *   1. Which way in    — the providers on offer, marks and names
 *   2. Whose people    — the narrowing, or skip it
 *   3. Where they land — joining on arrival, and a first group rule
 *   4. Do we insist    — only where the reader may set the requirement
 *
 * Editing a connection comes through here too. It opens on the narrowing with
 * the connection's own answers and asks only the two questions that belong to
 * the connection: whose people, and whether they join on arrival.
 */

import { useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  CommunityProviderConnectionRead,
  ConnectableProviderRead,
} from "@/api/generated/initiativeAPI.schemas";
import { ProviderMark } from "@/components/auth/ProviderMark";
import {
  useCommunityProviderConnections,
  useConnectableProviders,
  useConnectProvider,
  useCreateClaimRule,
  useUpdateCommunityAuthSettings,
  useUpdateProviderConnection,
} from "@/hooks/useCommunityAuthPolicy";
import { useWizard } from "@/hooks/useWizard";
import { getErrorMessage } from "@/lib/errorMessage";
import { toast } from "@/lib/mascotToast";
import { Badge } from "@/ui/badge";
import { Button } from "@/ui/button";
import { Field } from "@/ui/field";
import { Input } from "@/ui/input";
import { Label } from "@/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/ui/select";
import { Switch } from "@/ui/switch";
import { WizardDialog } from "@/ui/wizard-dialog";

/** Which claim narrows which provider. Each one spells "our tenant"
 *  differently, and only the provider knows which word it uses. */
export const NARROWING_CLAIMS = ["hd", "tid", "groups", "domain"] as const;

/** The server takes any claim name (``guild_provider_connections.claim`` is a
 *  64-character string), so the four above are shortcuts rather than the whole
 *  vocabulary, and this is how somebody reaches the rest. */
const OTHER_CLAIM = "__other__";

type Step = "provider" | "narrowing" | "landing" | "insist";

/** Comma- or space-separated, the way a list of domains gets typed. */
const splitValues = (raw: string): string[] =>
  raw
    .split(/[\s,]+/)
    .map((value) => value.trim())
    .filter(Boolean);

export interface ConnectSignInWizardProps {
  communityId: number;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Whether this reader may also make the provider the way in. */
  canRequire: boolean;
  /** Open on this connection's narrowing rather than on the picker. One the
   *  deployment answers for is taken over: the provider is already decided,
   *  and saving writes a connection of the community's own from its answers.
   *  One of the community's own is edited. */
  connection?: CommunityProviderConnectionRead | null;
}

export const ConnectSignInWizard = ({
  communityId,
  open,
  onOpenChange,
  canRequire,
  connection = null,
}: ConnectSignInWizardProps) => {
  const { t } = useTranslation(["settings", "common"]);
  const { step, go, back, canGoBack, reset, commit } = useWizard<Step>("provider");

  const availableQuery = useConnectableProviders(communityId);
  const connectionsQuery = useCommunityProviderConnections(communityId);
  const connect = useConnectProvider(communityId);
  const createRule = useCreateClaimRule(communityId);
  const updatePolicy = useUpdateCommunityAuthSettings(communityId);
  const updateConnection = useUpdateProviderConnection(communityId);

  // The connection being edited, when it is one of the community's own.
  const editingId = connection && !connection.inherited ? connection.id : null;

  const [providerId, setProviderId] = useState<number | null>(null);
  const [claim, setClaim] = useState("");
  // Whether the claim is being typed rather than picked from the shortcuts.
  const [customClaim, setCustomClaim] = useState(false);
  const [claimValues, setClaimValues] = useState("");
  const [autoJoin, setAutoJoin] = useState(false);
  const [ruleGroup, setRuleGroup] = useState("");
  const [ruleRole, setRuleRole] = useState("member");
  const [insist, setInsist] = useState(false);
  const [saving, setSaving] = useState(false);

  /** Fill in the narrowing and joining from a connection already in force. A
   *  claim that is not one of the shortcuts is shown as typed. */
  const seed = (
    row: Pick<
      CommunityProviderConnectionRead,
      "provider_id" | "claim" | "claim_values" | "auto_join"
    >
  ) => {
    setProviderId(row.provider_id);
    setCustomClaim(
      Boolean(row.claim) && !(NARROWING_CLAIMS as readonly string[]).includes(row.claim ?? "")
    );
    setClaim(row.claim ?? "");
    setClaimValues(row.claim_values.join(", "));
    setAutoJoin(row.auto_join);
  };

  // The wizard stays mounted between openings, so a connection it is opened
  // on has to land each time it opens, the first mount included.
  const [prev, setPrev] = useState<{
    open: boolean;
    connection: CommunityProviderConnectionRead | null;
  }>({ open: false, connection: null });
  if (prev.open !== open || prev.connection !== connection) {
    setPrev({ open, connection });
    if (open && connection) {
      seed(connection);
      commit("narrowing");
    }
  }

  const connections: CommunityProviderConnectionRead[] = connectionsQuery.data ?? [];
  // A provider the community merely inherits stays choosable: connecting to it
  // is how the deployment's arrangement is taken over. Only what the community
  // said itself leaves the grid.
  const ownIds = new Set(connections.filter((row) => !row.inherited).map((row) => row.provider_id));
  const inheritedByProvider = new Map(
    connections.filter((row) => row.inherited).map((row) => [row.provider_id, row])
  );
  const choosable = (availableQuery.data ?? []).filter(
    (row: ConnectableProviderRead) => !ownIds.has(row.id)
  );

  // The requirement is a question only somebody who may answer it is asked,
  // so the wizard is three steps long for everybody else, and an edit asks
  // only the connection's own two.
  const steps: Step[] =
    editingId !== null
      ? ["narrowing", "landing"]
      : canRequire
        ? ["provider", "narrowing", "landing", "insist"]
        : ["provider", "narrowing", "landing"];
  const landingIsLast = editingId !== null || !canRequire;

  const values = splitValues(claimValues);
  const narrowed = claim !== "" && values.length > 0;
  // Both halves or neither: a claim with nothing to match on, or values with
  // no claim to match them against, is half an answer.
  // A connection says who on the provider counts as this community's own.
  // There is no longer an "everybody" to fall back to, so both halves are
  // needed before the wizard goes on — the server refuses the other shape.
  const narrowingReady = narrowed;

  const closeWizard = () => {
    onOpenChange(false);
    reset();
    setProviderId(null);
    setCustomClaim(false);
    setClaim("");
    setClaimValues("");
    setAutoJoin(false);
    setRuleGroup("");
    setRuleRole("member");
    setInsist(false);
    setSaving(false);
  };

  /** Choosing a provider carries the deployment's answer forward where there
   *  is one, so taking an arrangement over starts from it rather than blank. */
  const chooseProvider = (row: ConnectableProviderRead) => {
    seed(
      inheritedByProvider.get(row.id) ?? {
        provider_id: row.id,
        claim: null,
        claim_values: [],
        auto_join: false,
      }
    );
    go("narrowing");
  };

  const finish = async () => {
    if (providerId === null) return;
    setSaving(true);
    try {
      if (editingId !== null) {
        await updateConnection.mutateAsync({
          connectionId: editingId,
          data: { claim, claim_values: values, auto_join: autoJoin },
        });
        toast.success(t("settings:communityAuth.connections.saved"));
        closeWizard();
        return;
      }
      await connect.mutateAsync({
        provider_id: providerId,
        claim: narrowed ? claim : null,
        claim_values: narrowed ? values : null,
        auto_join: autoJoin,
        enabled: true,
      });
      const group = ruleGroup.trim();
      if (group !== "") {
        await createRule.mutateAsync({
          provider_id: providerId,
          claim_value: group,
          community_role: ruleRole,
        });
      }
      if (insist) {
        await updatePolicy.mutateAsync({
          auth_policy: { policy: "required", provider_id: providerId, require_methods: [] },
        });
      }
      toast.success(t("settings:communityAuth.connections.connected"));
      closeWizard();
    } catch (error) {
      // The answers stay on screen: whichever call failed, the step somebody
      // is standing on is the one to try again from.
      toast.error(getErrorMessage(error, "settings:communityAuth.connections.connectError"));
      setSaving(false);
    }
  };

  const stepTitle: Record<Step, string> = {
    provider: t("settings:communityAuth.wizard.steps.provider.title"),
    narrowing: t("settings:communityAuth.wizard.steps.narrowing.title"),
    landing: t("settings:communityAuth.wizard.steps.landing.title"),
    insist: t("settings:communityAuth.wizard.steps.insist.title"),
  };

  const stepDescription: Record<Step, string> = {
    provider: t("settings:communityAuth.wizard.steps.provider.prompt"),
    narrowing: t("settings:communityAuth.wizard.steps.narrowing.prompt"),
    landing: t("settings:communityAuth.wizard.steps.landing.prompt"),
    insist: t("settings:communityAuth.wizard.steps.insist.prompt"),
  };

  return (
    <WizardDialog
      open={open}
      onOpenChange={(next) => (next ? onOpenChange(true) : closeWizard())}
      className="max-h-[85vh] overflow-y-auto sm:max-w-lg"
      title={stepTitle[step]}
      description={stepDescription[step]}
      progress={{ current: steps.indexOf(step) + 1, total: steps.length }}
      onBack={canGoBack ? back : undefined}
      backLabel={t("common:back")}
      backDisabled={saving}
    >
      {step === "provider" &&
        (choosable.length === 0 ? (
          <p className="text-muted-foreground text-sm">
            {t("settings:communityAuth.connections.noneOffered")}
          </p>
        ) : (
          <div className="grid grid-cols-2 gap-2">
            {choosable.map((row) => (
              <button
                key={row.id}
                type="button"
                disabled={!row.login_ready}
                className="flex items-start gap-3 rounded-lg border p-3 text-left transition-colors hover:bg-accent disabled:cursor-not-allowed disabled:opacity-60 disabled:hover:bg-transparent"
                onClick={() => chooseProvider(row)}
              >
                <ProviderMark icon={row.icon} className="mt-0.5" />
                <div className="min-w-0 space-y-1">
                  <div className="truncate font-medium text-sm">{row.display_name}</div>
                  {!row.login_ready && (
                    <Badge variant="outline">
                      {t("settings:communityAuth.connections.notReady")}
                    </Badge>
                  )}
                  {row.login_ready && inheritedByProvider.has(row.id) && (
                    <Badge variant="outline">
                      {t("settings:communityAuth.connections.inherited")}
                    </Badge>
                  )}
                </div>
              </button>
            ))}
          </div>
        ))}

      {step === "narrowing" && (
        <div className="space-y-4">
          <div className="space-y-2 rounded-md border bg-muted/40 p-3">
            <Label htmlFor="wizard-claim">
              {t("settings:communityAuth.connections.claimLabel")}
            </Label>
            <p className="text-muted-foreground text-xs">
              {t("settings:communityAuth.connections.claimHelp")}
            </p>
            <Select
              value={customClaim ? OTHER_CLAIM : claim}
              onValueChange={(choice) => {
                setCustomClaim(choice === OTHER_CLAIM);
                setClaim(choice === OTHER_CLAIM ? "" : choice);
              }}
            >
              <SelectTrigger id="wizard-claim">
                <SelectValue
                  placeholder={t("settings:communityAuth.connections.claimPlaceholder")}
                />
              </SelectTrigger>
              <SelectContent>
                {NARROWING_CLAIMS.map((name) => (
                  <SelectItem key={name} value={name}>
                    {t(`settings:communityAuth.connections.claimOptions.${name}`)}
                  </SelectItem>
                ))}
                <SelectItem value={OTHER_CLAIM}>
                  {t("settings:communityAuth.connections.claimOptions.other")}
                </SelectItem>
              </SelectContent>
            </Select>
            {customClaim && (
              <Input
                aria-label={t("settings:communityAuth.connections.claimNameLabel")}
                placeholder={t("settings:communityAuth.connections.claimNamePlaceholder")}
                value={claim}
                onChange={(event) => setClaim(event.target.value)}
              />
            )}
            {/* Values only matter once a claim is being read; asking for them
                beside "anyone" would be asking which of nobody counts. */}
            {(customClaim || claim !== "") && (
              <Input
                aria-label={t("settings:communityAuth.connections.claimValuesLabel")}
                placeholder={t("settings:communityAuth.connections.claimValuesPlaceholder")}
                value={claimValues}
                onChange={(event) => setClaimValues(event.target.value)}
              />
            )}
          </div>

          <div className="flex items-center gap-2">
            <Button
              className="flex-1"
              type="button"
              disabled={!narrowingReady}
              onClick={() => go("landing")}
            >
              {t("common:next")}
            </Button>
          </div>
        </div>
      )}

      {step === "landing" && (
        <div className="space-y-4">
          <div className="flex items-start justify-between gap-3 rounded-md border p-3">
            <div className="space-y-1">
              <Label htmlFor="wizard-auto-join">
                {t("settings:communityAuth.connections.autoJoinLabel")}
              </Label>
              <p className="text-muted-foreground text-xs">
                {t("settings:communityAuth.connections.autoJoinHelp")}
              </p>
            </div>
            <Switch
              id="wizard-auto-join"
              checked={autoJoin}
              onCheckedChange={(checked) => setAutoJoin(Boolean(checked))}
            />
          </div>

          {editingId === null && (
            <div className="space-y-3 rounded-md border bg-muted/40 p-3">
              <div className="space-y-1">
                <Label htmlFor="wizard-rule-group">
                  {t("settings:communityAuth.wizard.ruleTitle")}
                </Label>
                <p className="text-muted-foreground text-xs">
                  {t("settings:communityAuth.wizard.ruleHelp")}
                </p>
              </div>
              <Input
                id="wizard-rule-group"
                value={ruleGroup}
                placeholder={t("settings:communityAuth.rules.groupPlaceholder")}
                onChange={(event) => setRuleGroup(event.target.value)}
              />
              <Field label={t("settings:communityAuth.rules.standingLabel")}>
                <Select value={ruleRole} onValueChange={setRuleRole}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="member">
                      {t("settings:communityAuth.rules.role.member")}
                    </SelectItem>
                    <SelectItem value="admin">
                      {t("settings:communityAuth.rules.role.admin")}
                    </SelectItem>
                  </SelectContent>
                </Select>
              </Field>
            </div>
          )}

          <Button
            className="w-full"
            type="button"
            pending={saving}
            onClick={() => (landingIsLast ? void finish() : go("insist"))}
          >
            {saving
              ? t("settings:authProviders.saving")
              : editingId !== null
                ? t("common:save")
                : landingIsLast
                  ? t("settings:authProviders.wizard.connect")
                  : t("common:next")}
          </Button>
        </div>
      )}

      {step === "insist" && (
        <div className="space-y-4">
          <div className="flex items-start justify-between gap-3 rounded-md border p-3">
            <div className="space-y-1">
              <Label htmlFor="wizard-require">
                {t("settings:communityAuth.wizard.requireLabel")}
              </Label>
              <p className="text-muted-foreground text-xs">
                {t("settings:communityAuth.wizard.requireHelp")}
              </p>
            </div>
            <Switch
              id="wizard-require"
              checked={insist}
              onCheckedChange={(checked) => setInsist(Boolean(checked))}
            />
          </div>

          <Button className="w-full" type="button" pending={saving} onClick={() => void finish()}>
            {saving
              ? t("settings:authProviders.saving")
              : t("settings:authProviders.wizard.connect")}
          </Button>
        </div>
      )}
    </WizardDialog>
  );
};
