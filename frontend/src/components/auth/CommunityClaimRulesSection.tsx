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
 * Below the community's own rules, folded under their count, sit the ones the
 * deployment wrote for its providers that name this community. They are shown,
 * not changed, here, and each says whether it applies: it does once this
 * community's connection accepts its provider's rules, or everywhere once the
 * deployment applies them to every community.
 */

import { ChevronRight, Pencil, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  CommunityClaimRuleRead,
  ProviderPlacementRuleRead,
} from "@/api/generated/initiativeAPI.schemas";
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
  useUpdateClaimRule,
} from "@/hooks/useCommunityAuthPolicy";
import { useInitiativeRoles } from "@/hooks/useInitiativeRoles";
import { useInitiativesForCommunity } from "@/hooks/useInitiatives";
import { getErrorMessage } from "@/lib/errorMessage";
import { toast } from "@/lib/mascotToast";
import { Badge } from "@/ui/badge";
import { Button } from "@/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/ui/collapsible";
import { ConfirmDialog } from "@/ui/confirm-dialog";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/ui/dialog";
import { DropdownMenuItem, DropdownMenuSeparator } from "@/ui/dropdown-menu";
import { Field } from "@/ui/field";
import { Input } from "@/ui/input";
import { ListSkeleton, SkeletonRegion } from "@/ui/page-skeletons";
import { RowActionsMenu } from "@/ui/row-actions-menu";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/ui/select";

/** Sentinel for "the community itself", which has no initiative id. */
const COMMUNITY_ONLY = "community";

/** The dialog's answers, as its fields hold them. A rule being edited keeps
 *  its id; a new one has none. */
interface RuleDraft {
  ruleId: number | null;
  providerId: string;
  claimValue: string;
  communityRole: string;
  initiativeId: string;
  initiativeRoleId: string;
}

const NEW_RULE: RuleDraft = {
  ruleId: null,
  providerId: "",
  claimValue: "",
  communityRole: "member",
  initiativeId: COMMUNITY_ONLY,
  initiativeRoleId: "",
};

export const CommunityClaimRulesSection = ({ communityId }: { communityId: number }) => {
  const { t } = useTranslation(["settings", "common"]);
  const rulesQuery = useCommunityClaimRules(communityId);
  const connectionsQuery = useCommunityProviderConnections(communityId);
  const initiativesQuery = useInitiativesForCommunity(communityId);
  const createRule = useCreateClaimRule(communityId);
  const updateRule = useUpdateClaimRule(communityId);
  const deleteRule = useDeleteClaimRule(communityId);

  const [dialogOpen, setDialogOpen] = useState(false);
  // Kept after the dialog closes, so it does not empty while it fades out.
  const [draft, setDraft] = useState<RuleDraft>(NEW_RULE);
  const [removing, setRemoving] = useState<CommunityClaimRuleRead | null>(null);

  const rules = rulesQuery.data?.rules ?? [];
  const providerRules = rulesQuery.data?.provider_rules ?? [];
  const placementEverywhere = rulesQuery.data?.placement_everywhere ?? false;
  const reporting = new Set(rulesQuery.data?.reporting_provider_ids ?? []);
  const connections = connectionsQuery.data ?? [];
  const initiatives = initiativesQuery.data ?? [];
  const chosenInitiative =
    draft.initiativeId === COMMUNITY_ONLY ? null : Number(draft.initiativeId);
  const rolesQuery = useInitiativeRoles(chosenInitiative);
  const roles = rolesQuery.data ?? [];
  const adding = draft.ruleId === null;

  const edit = (patch: Partial<RuleDraft>) => setDraft((previous) => ({ ...previous, ...patch }));

  /** Add a rule, or edit one: the same dialog, filled in from the rule. */
  const openDialog = (rule?: CommunityClaimRuleRead) => {
    setDraft(
      rule
        ? {
            ruleId: rule.id,
            providerId: String(rule.provider_id),
            claimValue: rule.claim_value,
            communityRole: rule.community_role,
            initiativeId: rule.initiative_id == null ? COMMUNITY_ONLY : String(rule.initiative_id),
            initiativeRoleId:
              rule.initiative_role_id == null ? "" : String(rule.initiative_role_id),
          }
        : NEW_RULE
    );
    setDialogOpen(true);
  };

  const submit = () => {
    const fields = {
      claim_value: draft.claimValue.trim(),
      community_role: draft.communityRole,
      // Both halves or neither: somebody placed in an initiative needs the
      // standing to hold there.
      initiative_id: chosenInitiative,
      initiative_role_id: chosenInitiative ? Number(draft.initiativeRoleId) : null,
    };
    const callbacks = {
      onSuccess: () => {
        toast.success(adding ? t("communityAuth.rules.added") : t("communityAuth.rules.saved"));
        setDialogOpen(false);
      },
      onError: (error: unknown) =>
        toast.error(
          getErrorMessage(
            error,
            adding
              ? "settings:communityAuth.rules.addError"
              : "settings:communityAuth.rules.saveError"
          )
        ),
    };
    if (draft.ruleId === null) {
      createRule.mutate({ provider_id: Number(draft.providerId), ...fields }, callbacks);
    } else {
      // The provider stays: a rule pointed elsewhere is a different rule.
      updateRule.mutate({ ruleId: draft.ruleId, data: fields }, callbacks);
    }
  };

  /** Where somebody a rule matches lands, the community's own or the server's. */
  const landing = (rule: CommunityClaimRuleRead | ProviderPlacementRuleRead) =>
    rule.initiative_name
      ? t("communityAuth.rules.landsInInitiative", {
          provider: rule.provider_display_name,
          role: placementRoleLabel(rule.community_role, t),
          initiative: rule.initiative_name,
          initiativeRole: rule.initiative_role_name ?? "",
        })
      : t("communityAuth.rules.landsInCommunity", {
          provider: rule.provider_display_name,
          role: placementRoleLabel(rule.community_role, t),
        });

  const canSubmit =
    draft.providerId !== "" &&
    draft.claimValue.trim() !== "" &&
    (chosenInitiative === null || draft.initiativeRoleId !== "");

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="font-medium text-sm">{t("communityAuth.rules.title")}</h3>
        {/* A rule names a provider this community is connected to. */}
        {connections.length > 0 && (
          <Button
            type="button"
            variant="outline"
            size="sm"
            aria-label={t("communityAuth.rules.add")}
            onClick={() => openDialog()}
          >
            <Plus className="h-4 w-4" />
            {t("communityAuth.groupRules.add")}
          </Button>
        )}
      </div>

      {rulesQuery.isLoading ? (
        <SkeletonRegion>
          <ListSkeleton rows={3} />
        </SkeletonRegion>
      ) : rules.length === 0 ? (
        <p className="text-muted-foreground text-sm">{t("communityAuth.rules.empty")}</p>
      ) : (
        <ul className="divide-y rounded-md border">
          {rules.map((rule) => (
            <li key={rule.id} className="flex items-center gap-3 px-3 py-3">
              <ProviderMark icon={rule.provider_icon} />
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium">{rule.claim_value}</span>
                  {!reporting.has(rule.provider_id) && (
                    <Badge variant="outline">{t("communityAuth.rules.noGroupsBadge")}</Badge>
                  )}
                </div>
                <p className="text-muted-foreground text-sm">{landing(rule)}</p>
              </div>
              <RowActionsMenu subject={rule.claim_value}>
                <DropdownMenuItem onSelect={() => openDialog(rule)}>
                  <Pencil className="h-4 w-4" />
                  {t("common:edit")}
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem className="text-destructive" onSelect={() => setRemoving(rule)}>
                  <Trash2 className="h-4 w-4" />
                  {t("communityAuth.rules.remove")}
                </DropdownMenuItem>
              </RowActionsMenu>
            </li>
          ))}
        </ul>
      )}

      {providerRules.length > 0 && (
        <Collapsible>
          <CollapsibleTrigger className="group flex items-center gap-2 font-medium text-muted-foreground text-sm">
            <ChevronRight
              className="h-4 w-4 shrink-0 transition-transform group-data-[state=open]:rotate-90"
              aria-hidden="true"
            />
            {t("communityAuth.rules.deployment.count", { count: providerRules.length })}
          </CollapsibleTrigger>
          <CollapsibleContent className="space-y-2 pt-3">
            <p className="text-muted-foreground text-sm">
              {t("communityAuth.rules.deployment.description")}
            </p>
            {placementEverywhere && (
              <p className="text-muted-foreground text-sm">
                {t("communityAuth.rules.deployment.everywhere")}
              </p>
            )}
            <ul className="divide-y rounded-md border">
              {providerRules.map((rule) => (
                <li key={rule.id} className="flex items-center gap-3 px-3 py-3">
                  <ProviderMark icon={rule.provider_icon} />
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-medium">{describePlacementMatch(rule, t)}</span>
                      {!rule.applies && <NotApplyingBadge />}
                    </div>
                    <p className="text-muted-foreground text-sm">{landing(rule)}</p>
                  </div>
                </li>
              ))}
            </ul>
          </CollapsibleContent>
        </Collapsible>
      )}

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>
              {adding ? t("communityAuth.rules.add") : t("communityAuth.rules.editTitle")}
            </DialogTitle>
            <DialogDescription>{t("communityAuth.rules.dialogDescription")}</DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <Field
              label={t("communityAuth.rules.providerLabel")}
              hint={
                draft.providerId !== "" &&
                !reporting.has(Number(draft.providerId)) &&
                t("communityAuth.rules.noGroupsHint")
              }
            >
              {adding ? (
                <Select
                  value={draft.providerId}
                  onValueChange={(providerId) => edit({ providerId })}
                >
                  <SelectTrigger>
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
              ) : (
                <p className="text-sm">
                  {rules.find((rule) => rule.id === draft.ruleId)?.provider_display_name}
                </p>
              )}
            </Field>

            <Field
              label={t("communityAuth.rules.groupLabel")}
              hint={t("communityAuth.rules.groupHint")}
            >
              <Input
                value={draft.claimValue}
                onChange={(event) => edit({ claimValue: event.target.value })}
                placeholder={t("communityAuth.rules.groupPlaceholder")}
              />
            </Field>

            <Field label={t("communityAuth.rules.standingLabel")}>
              <Select
                value={draft.communityRole}
                onValueChange={(communityRole) => edit({ communityRole })}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="member">{t("communityAuth.rules.role.member")}</SelectItem>
                  <SelectItem value="admin">{t("communityAuth.rules.role.admin")}</SelectItem>
                </SelectContent>
              </Select>
            </Field>

            <Field label={t("communityAuth.rules.initiativeLabel")}>
              <Select
                value={draft.initiativeId}
                onValueChange={(initiativeId) => edit({ initiativeId, initiativeRoleId: "" })}
              >
                <SelectTrigger>
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
            </Field>

            {chosenInitiative !== null && (
              <Field label={t("communityAuth.rules.initiativeRoleLabel")}>
                <Select
                  value={draft.initiativeRoleId}
                  onValueChange={(initiativeRoleId) => edit({ initiativeRoleId })}
                >
                  <SelectTrigger>
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
              </Field>
            )}
          </div>
          <DialogFooter
            submitLabel={adding ? t("communityAuth.rules.add") : t("common:save")}
            pending={createRule.isPending || updateRule.isPending}
            disabled={!canSubmit}
            onSubmit={submit}
          />
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
    </div>
  );
};
