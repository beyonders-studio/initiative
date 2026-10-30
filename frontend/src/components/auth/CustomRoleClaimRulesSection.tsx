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

import { ArrowDown, ArrowUp, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { CustomRoleClaimRuleRead } from "@/api/generated/initiativeAPI.schemas";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  useCommunityProviderConnections,
  useCreateCustomRoleClaimRule,
  useCustomRoleClaimRules,
  useDeleteCustomRoleClaimRule,
  useOrderCustomRoleClaimRules,
} from "@/hooks/useCommunityAuthPolicy";
import { useCustomRoles } from "@/hooks/useCustomRoles";
import { getErrorMessage } from "@/lib/errorMessage";
import { toast } from "@/lib/mascotToast";

export const CustomRoleClaimRulesSection = ({ communityId }: { communityId: number }) => {
  const { t } = useTranslation("settings");
  const rolesQuery = useCustomRoles();
  const rulesQuery = useCustomRoleClaimRules(communityId);
  const connectionsQuery = useCommunityProviderConnections(communityId);
  const createRule = useCreateCustomRoleClaimRule(communityId);
  const orderRules = useOrderCustomRoleClaimRules(communityId);
  const deleteRule = useDeleteCustomRoleClaimRule(communityId);

  const [dialogOpen, setDialogOpen] = useState(false);
  const [providerId, setProviderId] = useState("");
  const [claimValue, setClaimValue] = useState("");
  const [roleId, setRoleId] = useState("");
  const [removing, setRemoving] = useState<CustomRoleClaimRuleRead | null>(null);

  const roles = rolesQuery.data ?? [];
  if (roles.length === 0) return null;

  const rules = rulesQuery.data ?? [];
  const connections = connectionsQuery.data ?? [];
  const roleName = (id: number) => roles.find((role) => role.id === id)?.name ?? "";
  const providerName = (id: number) =>
    connections.find((row) => row.provider_id === id)?.provider_display_name ?? "";

  const closeDialog = () => {
    setDialogOpen(false);
    setProviderId("");
    setClaimValue("");
    setRoleId("");
  };

  const submit = () => {
    createRule.mutate(
      {
        provider_id: Number(providerId),
        claim_value: claimValue.trim(),
        role_id: Number(roleId),
      },
      {
        onSuccess: () => {
          toast.success(t("customRoleRules.added"));
          closeDialog();
        },
        onError: (error) =>
          toast.error(getErrorMessage(error, "settings:customRoleRules.addError")),
      }
    );
  };

  const move = (index: number, by: -1 | 1) => {
    const ids = rules.map((rule) => rule.id);
    [ids[index], ids[index + by]] = [ids[index + by], ids[index]];
    orderRules.mutate(ids, {
      onError: (error) =>
        toast.error(getErrorMessage(error, "settings:customRoleRules.orderError")),
    });
  };

  const canSubmit = providerId !== "" && claimValue.trim() !== "" && roleId !== "";

  return (
    <Card>
      <CardHeader className="flex flex-row items-start justify-between gap-4 space-y-0">
        <div>
          <CardTitle>{t("customRoleRules.title")}</CardTitle>
          <CardDescription>{t("customRoleRules.description")}</CardDescription>
        </div>
        <Button
          type="button"
          onClick={() => setDialogOpen(true)}
          disabled={connections.length === 0}
        >
          <Plus className="h-4 w-4" />
          {t("customRoleRules.add")}
        </Button>
      </CardHeader>
      <CardContent>
        {rules.length === 0 ? (
          <p className="text-muted-foreground text-sm">{t("customRoleRules.empty")}</p>
        ) : (
          <ol className="divide-y rounded-md border">
            {rules.map((rule, index) => (
              <li key={rule.id} className="flex items-center justify-between gap-4 px-3 py-3">
                <div className="min-w-0">
                  <span className="font-medium">{rule.claim_value}</span>
                  <p className="text-muted-foreground text-sm">
                    {t("customRoleRules.gives", {
                      provider: providerName(rule.provider_id),
                      role: roleName(rule.role_id),
                    })}
                  </p>
                </div>
                <div className="flex shrink-0 items-center gap-1">
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    aria-label={t("customRoleRules.moveUp", { group: rule.claim_value })}
                    disabled={index === 0 || orderRules.isPending}
                    onClick={() => move(index, -1)}
                  >
                    <ArrowUp className="h-4 w-4" />
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    aria-label={t("customRoleRules.moveDown", { group: rule.claim_value })}
                    disabled={index === rules.length - 1 || orderRules.isPending}
                    onClick={() => move(index, 1)}
                  >
                    <ArrowDown className="h-4 w-4" />
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className="text-destructive"
                    aria-label={t("customRoleRules.remove")}
                    onClick={() => setRemoving(rule)}
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </div>
              </li>
            ))}
          </ol>
        )}
      </CardContent>

      <Dialog
        open={dialogOpen}
        onOpenChange={(open) => (open ? setDialogOpen(true) : closeDialog())}
      >
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>{t("customRoleRules.add")}</DialogTitle>
            <DialogDescription>{t("customRoleRules.dialogDescription")}</DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="role-rule-provider">{t("communityAuth.rules.providerLabel")}</Label>
              <Select value={providerId} onValueChange={setProviderId}>
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
            </div>
            <div className="space-y-2">
              <Label htmlFor="role-rule-group">{t("communityAuth.rules.groupLabel")}</Label>
              <Input
                id="role-rule-group"
                value={claimValue}
                onChange={(event) => setClaimValue(event.target.value)}
                placeholder={t("communityAuth.rules.groupPlaceholder")}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="role-rule-role">{t("customRoleRules.roleLabel")}</Label>
              <Select value={roleId} onValueChange={setRoleId}>
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
          <DialogFooter>
            <Button type="button" variant="outline" onClick={closeDialog}>
              {t("authProviders.cancel")}
            </Button>
            <Button type="button" onClick={submit} disabled={!canSubmit || createRule.isPending}>
              {t("customRoleRules.add")}
            </Button>
          </DialogFooter>
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
        cancelLabel={t("authProviders.cancel")}
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
    </Card>
  );
};
