/**
 * Where this community places the people its providers vouch for.
 *
 * The other half of a connection. A connection says which arrivals count as
 * ours; a rule says where one of them lands — as a member or an admin, and in
 * an initiative if we say so. A community says both in one breath, so they sit
 * on one page: our people come in through this, and these of them belong here.
 *
 * Which claim carries groups is the operator's to set on the provider, so a
 * connection they have not set it on is offered with a note rather than
 * hidden: the rule would be written correctly and simply never match.
 *
 * Below the community's own rules sit the ones the deployment wrote for its
 * providers that name this community. They are read-only here, and each says
 * whether it applies: it does once this community's connection accepts its
 * provider's rules, or everywhere once the deployment applies them to every
 * community.
 */

import { Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { CommunityClaimRuleRead } from "@/api/generated/initiativeAPI.schemas";
import { ProviderMark } from "@/components/auth/ProviderMark";
import {
  describePlacementMatch,
  NotApplyingBadge,
  placementRoleLabel,
} from "@/components/auth/ProviderPlacementRuleSummary";
import {
  useCommunityClaimRules,
  useCommunityProviderConnections,
  useCreateClaimRule,
  useDeleteClaimRule,
} from "@/hooks/useCommunityAuthPolicy";
import { useInitiativeRoles } from "@/hooks/useInitiativeRoles";
import { useInitiativesForCommunity } from "@/hooks/useInitiatives";
import { getErrorMessage } from "@/lib/errorMessage";
import { toast } from "@/lib/mascotToast";
import { Badge } from "@/ui/badge";
import { Button } from "@/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/ui/card";
import { ConfirmDialog } from "@/ui/confirm-dialog";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/ui/dialog";
import { Input } from "@/ui/input";
import { Label } from "@/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/ui/select";

/** Sentinel for "the community itself", which has no initiative id. */
const COMMUNITY_ONLY = "community";

export const CommunityClaimRulesSection = ({ communityId }: { communityId: number }) => {
  const { t } = useTranslation("settings");
  const rulesQuery = useCommunityClaimRules(communityId);
  const connectionsQuery = useCommunityProviderConnections(communityId);
  const initiativesQuery = useInitiativesForCommunity(communityId);
  const createRule = useCreateClaimRule(communityId);
  const deleteRule = useDeleteClaimRule(communityId);

  const [dialogOpen, setDialogOpen] = useState(false);
  const [providerId, setProviderId] = useState("");
  const [claimValue, setClaimValue] = useState("");
  const [communityRole, setCommunityRole] = useState("member");
  const [initiativeId, setInitiativeId] = useState<string>(COMMUNITY_ONLY);
  const [initiativeRoleId, setInitiativeRoleId] = useState("");
  const [removing, setRemoving] = useState<CommunityClaimRuleRead | null>(null);

  const rules = rulesQuery.data?.rules ?? [];
  const providerRules = rulesQuery.data?.provider_rules ?? [];
  const placementEverywhere = rulesQuery.data?.placement_everywhere ?? false;
  const reporting = new Set(rulesQuery.data?.reporting_provider_ids ?? []);
  const connections = connectionsQuery.data ?? [];
  const initiatives = initiativesQuery.data ?? [];
  const chosenInitiative = initiativeId === COMMUNITY_ONLY ? null : Number(initiativeId);
  const rolesQuery = useInitiativeRoles(chosenInitiative);
  const roles = rolesQuery.data ?? [];

  const closeDialog = () => {
    setDialogOpen(false);
    setProviderId("");
    setClaimValue("");
    setCommunityRole("member");
    setInitiativeId(COMMUNITY_ONLY);
    setInitiativeRoleId("");
  };

  const submit = () => {
    createRule.mutate(
      {
        provider_id: Number(providerId),
        claim_value: claimValue.trim(),
        community_role: communityRole,
        // Both halves or neither: somebody placed in an initiative needs the
        // standing to hold there.
        initiative_id: chosenInitiative,
        initiative_role_id: chosenInitiative ? Number(initiativeRoleId) : null,
      },
      {
        onSuccess: () => {
          toast.success(t("communityAuth.rules.added"));
          closeDialog();
        },
        onError: (error) =>
          toast.error(getErrorMessage(error, "settings:communityAuth.rules.addError")),
      }
    );
  };

  const roleLabel = (role: string) => placementRoleLabel(role, t);

  const canSubmit =
    providerId !== "" &&
    claimValue.trim() !== "" &&
    (chosenInitiative === null || initiativeRoleId !== "");

  return (
    <Card>
      <CardHeader className="flex flex-row items-start justify-between gap-4 space-y-0">
        <div>
          <CardTitle>{t("communityAuth.rules.title")}</CardTitle>
          <CardDescription>{t("communityAuth.rules.description")}</CardDescription>
        </div>
        <Button
          type="button"
          onClick={() => setDialogOpen(true)}
          disabled={connections.length === 0}
        >
          <Plus className="h-4 w-4" />
          {t("communityAuth.rules.add")}
        </Button>
      </CardHeader>
      <CardContent className="space-y-6">
        {rulesQuery.isLoading ? (
          <p className="text-muted-foreground text-sm">{t("authProviders.loading")}</p>
        ) : rules.length === 0 ? (
          <p className="text-muted-foreground text-sm">
            {connections.length === 0
              ? t("communityAuth.rules.connectFirst")
              : t("communityAuth.rules.empty")}
          </p>
        ) : (
          <ul className="divide-y rounded-md border">
            {rules.map((rule) => (
              <li key={rule.id} className="flex items-center justify-between gap-4 px-3 py-3">
                <div className="flex min-w-0 items-start gap-3">
                  <ProviderMark icon={rule.provider_icon} className="mt-0.5" />
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-medium">{rule.claim_value}</span>
                      {!reporting.has(rule.provider_id) && (
                        <Badge variant="outline">{t("communityAuth.rules.noGroupsBadge")}</Badge>
                      )}
                    </div>
                    <p className="text-muted-foreground text-sm">
                      {rule.initiative_name
                        ? t("communityAuth.rules.landsInInitiative", {
                            provider: rule.provider_display_name,
                            role: roleLabel(rule.community_role),
                            initiative: rule.initiative_name,
                            initiativeRole: rule.initiative_role_name ?? "",
                          })
                        : t("communityAuth.rules.landsInCommunity", {
                            provider: rule.provider_display_name,
                            role: roleLabel(rule.community_role),
                          })}
                    </p>
                  </div>
                </div>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="shrink-0 text-destructive"
                  aria-label={t("communityAuth.rules.remove")}
                  onClick={() => setRemoving(rule)}
                >
                  <Trash2 className="h-4 w-4" />
                </Button>
              </li>
            ))}
          </ul>
        )}

        {providerRules.length > 0 && (
          <section className="space-y-2" aria-labelledby="deployment-rules-title">
            <div className="space-y-1">
              <h3 id="deployment-rules-title" className="font-semibold text-sm">
                {t("communityAuth.rules.deployment.title")}
              </h3>
              <p className="text-muted-foreground text-sm">
                {t("communityAuth.rules.deployment.description")}
              </p>
              {placementEverywhere && (
                <p className="text-muted-foreground text-sm">
                  {t("communityAuth.rules.deployment.everywhere")}
                </p>
              )}
            </div>
            <ul className="divide-y rounded-md border">
              {providerRules.map((rule) => (
                <li key={rule.id} className="flex items-start gap-3 px-3 py-3">
                  <ProviderMark icon={rule.provider_icon} className="mt-0.5" />
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-medium">{describePlacementMatch(rule, t)}</span>
                      {!rule.applies && <NotApplyingBadge />}
                    </div>
                    <p className="text-muted-foreground text-sm">
                      {rule.initiative_name
                        ? t("communityAuth.rules.landsInInitiative", {
                            provider: rule.provider_display_name,
                            role: roleLabel(rule.community_role),
                            initiative: rule.initiative_name,
                            initiativeRole: rule.initiative_role_name ?? "",
                          })
                        : t("communityAuth.rules.landsInCommunity", {
                            provider: rule.provider_display_name,
                            role: roleLabel(rule.community_role),
                          })}
                    </p>
                  </div>
                </li>
              ))}
            </ul>
          </section>
        )}
      </CardContent>

      <Dialog
        open={dialogOpen}
        onOpenChange={(open) => (open ? setDialogOpen(true) : closeDialog())}
      >
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>{t("communityAuth.rules.add")}</DialogTitle>
            <DialogDescription>{t("communityAuth.rules.dialogDescription")}</DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="rule-provider">{t("communityAuth.rules.providerLabel")}</Label>
              <Select value={providerId} onValueChange={setProviderId}>
                <SelectTrigger id="rule-provider">
                  <SelectValue placeholder={t("communityAuth.rules.providerPlaceholder")} />
                </SelectTrigger>
                <SelectContent>
                  {connections.map((row) => (
                    <SelectItem key={row.provider_id} value={String(row.provider_id)}>
                      {row.provider_display_name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {providerId !== "" && !reporting.has(Number(providerId)) && (
                <p className="text-muted-foreground text-xs">
                  {t("communityAuth.rules.noGroupsHint")}
                </p>
              )}
            </div>

            <div className="space-y-2">
              <Label htmlFor="rule-group">{t("communityAuth.rules.groupLabel")}</Label>
              <Input
                id="rule-group"
                value={claimValue}
                onChange={(event) => setClaimValue(event.target.value)}
                placeholder={t("communityAuth.rules.groupPlaceholder")}
              />
              <p className="text-muted-foreground text-xs">{t("communityAuth.rules.groupHint")}</p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="rule-role">{t("communityAuth.rules.standingLabel")}</Label>
              <Select value={communityRole} onValueChange={setCommunityRole}>
                <SelectTrigger id="rule-role">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="member">{t("communityAuth.rules.role.member")}</SelectItem>
                  <SelectItem value="admin">{t("communityAuth.rules.role.admin")}</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-2">
              <Label htmlFor="rule-initiative">{t("communityAuth.rules.initiativeLabel")}</Label>
              <Select
                value={initiativeId}
                onValueChange={(value) => {
                  setInitiativeId(value);
                  setInitiativeRoleId("");
                }}
              >
                <SelectTrigger id="rule-initiative">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={COMMUNITY_ONLY}>
                    {t("communityAuth.rules.communityOnly")}
                  </SelectItem>
                  {initiatives.map((initiative) => (
                    <SelectItem key={initiative.id} value={String(initiative.id)}>
                      {initiative.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            {chosenInitiative !== null && (
              <div className="space-y-2">
                <Label htmlFor="rule-initiative-role">
                  {t("communityAuth.rules.initiativeRoleLabel")}
                </Label>
                <Select value={initiativeRoleId} onValueChange={setInitiativeRoleId}>
                  <SelectTrigger id="rule-initiative-role">
                    <SelectValue placeholder={t("communityAuth.rules.initiativeRolePlaceholder")} />
                  </SelectTrigger>
                  <SelectContent>
                    {roles.map((role) => (
                      <SelectItem key={role.id} value={String(role.id)}>
                        {role.display_name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            )}
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={closeDialog}>
              {t("authProviders.cancel")}
            </Button>
            <Button type="button" onClick={submit} disabled={!canSubmit || createRule.isPending}>
              {t("communityAuth.rules.add")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <ConfirmDialog
        open={removing !== null}
        onOpenChange={(open) => !open && setRemoving(null)}
        title={t("communityAuth.rules.removeTitle")}
        description={t("communityAuth.rules.removeDescription", {
          group: removing?.claim_value ?? "",
        })}
        confirmLabel={t("communityAuth.rules.remove")}
        destructive
        isLoading={deleteRule.isPending}
        onConfirm={() => {
          if (!removing) return;
          deleteRule.mutate(removing.id, {
            onSuccess: () => {
              toast.success(t("communityAuth.rules.removed"));
              setRemoving(null);
            },
            onError: (error) => {
              toast.error(getErrorMessage(error, "settings:communityAuth.rules.removeError"));
              setRemoving(null);
            },
          });
        }}
      />
    </Card>
  );
};
