/**
 * Which custom role a group gives whoever signs in carrying it.
 *
 * Beside the rules that place people: those say where somebody lands, these
 * say what part of running the community they hold. A sign-in reads them in
 * order and the first group it carries decides, so the list is ordered and
 * each rule moves up or down. A role somebody gave by hand stays theirs.
 *
 * Shown only where the community has custom roles: with none, there is
 * nothing to give.
 */

import { ArrowDown, ArrowUp, Pencil, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { CustomRoleClaimRuleRead } from "@/api/generated/initiativeAPI.schemas";
import { useCommunities } from "@/hooks/useCommunities";
import {
  useCommunityProviderConnections,
  useCreateCustomRoleClaimRule,
  useCustomRoleClaimRules,
  useDeleteCustomRoleClaimRule,
  useOrderCustomRoleClaimRules,
  useUpdateCustomRoleClaimRule,
} from "@/hooks/useCommunityAuthPolicy";
import { useCustomRoles } from "@/hooks/useCustomRoles";
import { getErrorMessage } from "@/lib/errorMessage";
import { toast } from "@/lib/mascotToast";
import { Button } from "@/ui/button";
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
import { Input } from "@/ui/input";
import { Label } from "@/ui/label";
import { RowActionsMenu } from "@/ui/row-actions-menu";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/ui/select";

/** The dialog's answers, as its fields hold them. A rule being edited keeps
 *  its id; a new one has none. */
interface RoleRuleDraft {
  ruleId: number | null;
  providerId: string;
  claimValue: string;
  roleId: string;
}

const NEW_RULE: RoleRuleDraft = { ruleId: null, providerId: "", claimValue: "", roleId: "" };

export const CustomRoleClaimRulesSection = ({ communityId }: { communityId: number }) => {
  const { t } = useTranslation(["settings", "common"]);
  const { activeCommunity } = useCommunities();
  const rolesQuery = useCustomRoles();
  const rulesQuery = useCustomRoleClaimRules(communityId);
  const connectionsQuery = useCommunityProviderConnections(communityId);
  const createRule = useCreateCustomRoleClaimRule(communityId);
  const updateRule = useUpdateCustomRoleClaimRule(communityId);
  const orderRules = useOrderCustomRoleClaimRules(communityId);
  const deleteRule = useDeleteCustomRoleClaimRule(communityId);

  const [dialogOpen, setDialogOpen] = useState(false);
  // Kept after the dialog closes, so it does not empty while it fades out.
  const [draft, setDraft] = useState<RoleRuleDraft>(NEW_RULE);
  const [removing, setRemoving] = useState<CustomRoleClaimRuleRead | null>(null);

  const roles = rolesQuery.data ?? [];
  if (roles.length === 0) return null;

  const rules = rulesQuery.data ?? [];
  const connections = connectionsQuery.data ?? [];
  // The deployment may close custom roles for the community: the rules keep
  // applying and stay readable, and nobody changes them.
  const closed = Boolean(activeCommunity?.closed_surfaces?.includes("custom_roles"));
  const busy = orderRules.isPending;
  const adding = draft.ruleId === null;
  const roleName = (id: number) => roles.find((role) => role.id === id)?.name ?? "";
  const providerName = (id: number) =>
    connections.find((row) => row.provider_id === id)?.provider_display_name ?? "";

  const edit = (patch: Partial<RoleRuleDraft>) =>
    setDraft((previous) => ({ ...previous, ...patch }));

  /** Add a rule, or edit one: the same dialog, filled in from the rule. */
  const openDialog = (rule?: CustomRoleClaimRuleRead) => {
    setDraft(
      rule
        ? {
            ruleId: rule.id,
            providerId: String(rule.provider_id),
            claimValue: rule.claim_value,
            roleId: String(rule.role_id),
          }
        : NEW_RULE
    );
    setDialogOpen(true);
  };

  const submit = () => {
    const fields = { claim_value: draft.claimValue.trim(), role_id: Number(draft.roleId) };
    const callbacks = {
      onSuccess: () => {
        toast.success(adding ? t("customRoleRules.added") : t("customRoleRules.saved"));
        setDialogOpen(false);
      },
      onError: (error: unknown) =>
        toast.error(
          getErrorMessage(
            error,
            adding ? "settings:customRoleRules.addError" : "settings:customRoleRules.saveError"
          )
        ),
    };
    if (draft.ruleId === null) {
      createRule.mutate({ provider_id: Number(draft.providerId), ...fields }, callbacks);
    } else {
      // The provider and the rule's place in the order stay as they are.
      updateRule.mutate({ ruleId: draft.ruleId, data: fields }, callbacks);
    }
  };

  const move = (index: number, by: -1 | 1) => {
    const ids = rules.map((rule) => rule.id);
    [ids[index], ids[index + by]] = [ids[index + by], ids[index]];
    orderRules.mutate(ids, {
      onError: (error) =>
        toast.error(getErrorMessage(error, "settings:customRoleRules.orderError")),
    });
  };

  const canSubmit =
    draft.providerId !== "" && draft.claimValue.trim() !== "" && draft.roleId !== "";

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="font-medium text-sm">{t("customRoleRules.title")}</h3>
        {closed || connections.length === 0 ? null : (
          <Button
            type="button"
            variant="outline"
            size="sm"
            aria-label={t("customRoleRules.add")}
            onClick={() => openDialog()}
          >
            <Plus className="h-4 w-4" />
            {t("communityAuth.groupRules.add")}
          </Button>
        )}
      </div>
      {closed ? (
        <p className="text-muted-foreground text-sm">{t("customRoleRules.closed")}</p>
      ) : null}
      {rulesQuery.isLoading ? (
        <p className="text-muted-foreground text-sm">{t("customRoleRules.loading")}</p>
      ) : rulesQuery.isError ? (
        <div className="flex flex-wrap items-center gap-3">
          <p className="text-destructive text-sm">{t("customRoleRules.loadError")}</p>
          <Button type="button" variant="outline" size="sm" onClick={() => rulesQuery.refetch()}>
            {t("customRoleRules.retry")}
          </Button>
        </div>
      ) : rules.length === 0 ? (
        <p className="text-muted-foreground text-sm">{t("customRoleRules.empty")}</p>
      ) : (
        <ol className="divide-y rounded-md border">
          {rules.map((rule, index) => (
            <li key={rule.id} className="flex items-center gap-3 px-3 py-3">
              <span className="w-5 shrink-0 text-center text-muted-foreground text-sm tabular-nums">
                {index + 1}
              </span>
              <div className="min-w-0 flex-1">
                <span className="font-medium">{rule.claim_value}</span>
                <p className="text-muted-foreground text-sm">
                  {t("customRoleRules.gives", {
                    provider: providerName(rule.provider_id),
                    role: roleName(rule.role_id),
                  })}
                </p>
              </div>
              {closed ? null : (
                <div className="flex shrink-0 items-center gap-1">
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    aria-label={t("customRoleRules.moveUp", { group: rule.claim_value })}
                    disabled={index === 0 || busy}
                    onClick={() => move(index, -1)}
                  >
                    <ArrowUp className="h-4 w-4" />
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    aria-label={t("customRoleRules.moveDown", { group: rule.claim_value })}
                    disabled={index === rules.length - 1 || busy}
                    onClick={() => move(index, 1)}
                  >
                    <ArrowDown className="h-4 w-4" />
                  </Button>
                  <RowActionsMenu subject={rule.claim_value}>
                    <DropdownMenuItem onSelect={() => openDialog(rule)}>
                      <Pencil className="h-4 w-4" />
                      {t("common:edit")}
                    </DropdownMenuItem>
                    <DropdownMenuSeparator />
                    <DropdownMenuItem
                      className="text-destructive"
                      onSelect={() => setRemoving(rule)}
                    >
                      <Trash2 className="h-4 w-4" />
                      {t("customRoleRules.remove")}
                    </DropdownMenuItem>
                  </RowActionsMenu>
                </div>
              )}
            </li>
          ))}
        </ol>
      )}

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>
              {adding ? t("customRoleRules.add") : t("customRoleRules.editTitle")}
            </DialogTitle>
            <DialogDescription>{t("customRoleRules.dialogDescription")}</DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor={adding ? "role-rule-provider" : undefined}>
                {t("communityAuth.rules.providerLabel")}
              </Label>
              {adding ? (
                <Select
                  value={draft.providerId}
                  onValueChange={(providerId) => edit({ providerId })}
                >
                  <SelectTrigger id="role-rule-provider">
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
                <p className="text-sm">{providerName(Number(draft.providerId))}</p>
              )}
            </div>
            <div className="space-y-2">
              <Label htmlFor="role-rule-group">{t("communityAuth.rules.groupLabel")}</Label>
              <Input
                id="role-rule-group"
                value={draft.claimValue}
                onChange={(event) => edit({ claimValue: event.target.value })}
                placeholder={t("communityAuth.rules.groupPlaceholder")}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="role-rule-role">{t("customRoleRules.roleLabel")}</Label>
              <Select value={draft.roleId} onValueChange={(roleId) => edit({ roleId })}>
                <SelectTrigger id="role-rule-role">
                  <SelectValue placeholder={t("customRoleRules.rolePlaceholder")} />
                </SelectTrigger>
                <SelectContent>
                  {roles.map((role) => (
                    <SelectItem key={role.id} value={String(role.id)}>
                      {role.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
          <DialogFooter
            submitLabel={adding ? t("customRoleRules.add") : t("common:save")}
            pending={createRule.isPending || updateRule.isPending}
            disabled={!canSubmit}
            onSubmit={submit}
          />
        </DialogContent>
      </Dialog>

      <ConfirmDialog
        open={removing !== null}
        onOpenChange={(open) => !open && setRemoving(null)}
        title={t("customRoleRules.removeTitle")}
        description={t("customRoleRules.removeDescription", {
          group: removing?.claim_value ?? "",
        })}
        confirmLabel={t("customRoleRules.remove")}
        destructive
        isLoading={deleteRule.isPending}
        onConfirm={() => {
          if (!removing) return;
          deleteRule.mutate(removing.id, {
            onSuccess: () => setRemoving(null),
            onError: (error) => {
              toast.error(getErrorMessage(error, "settings:customRoleRules.removeError"));
              setRemoving(null);
            },
          });
        }}
      />
    </div>
  );
};
