import { Pencil, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  PlacementProviderRead,
  ProviderPlacementRuleRead,
} from "@/api/generated/initiativeAPI.schemas";
import {
  useListPlacementRequests,
  useListProviderPlacement,
} from "@/api/generated/provider-placement/provider-placement";
import { ProviderMark } from "@/components/auth/ProviderMark";
import {
  describePlacementMatch,
  NotApplyingBadge,
  placementRoleLabel,
} from "@/components/auth/ProviderPlacementRuleSummary";
import { ProviderPlacementRuleDialog } from "@/components/platform/ProviderPlacementRuleDialog";
import { SettingsRow, SettingsSection } from "@/components/settings/SettingsSection";
import { useAuth } from "@/hooks/useAuth";
import {
  useAgreePlacementRequest,
  useDeletePlacementRule,
  useSetPlacementEverywhere,
} from "@/hooks/useProviderPlacement";
import { toast } from "@/lib/mascotToast";
import { Capability, hasCapability } from "@/lib/permissions";
import { Button } from "@/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/ui/card";
import { ConfirmDialog } from "@/ui/confirm-dialog";
import { SkeletonRegion, TableSkeleton } from "@/ui/page-skeletons";
import { StatusMessage } from "@/ui/status-message";
import { Switch } from "@/ui/switch";

/** The rule dialog's subject: a provider, and the rule on it being edited. */
type Editing = { provider: PlacementProviderRead; rule: ProviderPlacementRuleRead | null };

/**
 * Sign-in placement rules the platform writes on its providers: which of the
 * people a provider signs in land in which community, at what standing, and
 * in which initiative there.
 *
 * A rule takes effect in a community that accepted its provider's rules on
 * that community's own connection, or everywhere once the owner applies them
 * to every community — the switch at the top, recorded on every change.
 */
export const OperatorDashboardPlacementPage = () => {
  const { t } = useTranslation("settings");
  const { user } = useAuth();
  const canManageCommunities = hasCapability(user, Capability.communitiesManage);
  const canSetEverywhere = hasCapability(user, Capability.configManage);

  const placementQuery = useListProviderPlacement({ query: { enabled: canManageCommunities } });

  const [editing, setEditing] = useState<Editing | null>(null);
  const [removing, setRemoving] = useState<ProviderPlacementRuleRead | null>(null);
  const [confirmEverywhere, setConfirmEverywhere] = useState(false);

  const setEverywhere = useSetPlacementEverywhere();
  const deleteRule = useDeletePlacementRule();

  const applyEverywhere = (enabled: boolean) =>
    setEverywhere.mutate(enabled, {
      onSuccess: () =>
        toast.success(
          enabled
            ? t("providerPlacement.everywhere.enabled")
            : t("providerPlacement.everywhere.disabled")
        ),
      // Close the confirm dialog only once the save settles, so its in-flight
      // state shows while it runs.
      onSettled: () => setConfirmEverywhere(false),
    });

  const removeRule = (rule: ProviderPlacementRuleRead) =>
    deleteRule.mutate(rule.id, {
      onSuccess: () => toast.success(t("providerPlacement.removed")),
      onSettled: () => setRemoving(null),
    });

  if (!canManageCommunities) {
    return <p className="text-muted-foreground text-sm">{t("providerPlacement.platformOnly")}</p>;
  }

  if (placementQuery.isLoading) {
    return (
      <SkeletonRegion>
        <TableSkeleton rows={4} columns={3} />
      </SkeletonRegion>
    );
  }

  if (placementQuery.isError || !placementQuery.data) {
    return <StatusMessage onRetry={placementQuery.refetch} />;
  }

  const { placement_everywhere: everywhere, providers, rules } = placementQuery.data;

  const changeEverywhere = (enabled: boolean) => {
    // Turning it on reaches communities that never accepted, so it is
    // confirmed first; turning it off applies at once.
    if (enabled) {
      setConfirmEverywhere(true);
      return;
    }
    applyEverywhere(false);
  };

  return (
    <div className="space-y-6">
      <SettingsSection description={t("providerPlacement.description")}>
        <SettingsRow
          label={t("providerPlacement.everywhere.label")}
          description={
            canSetEverywhere
              ? t("providerPlacement.everywhere.help")
              : `${t("providerPlacement.everywhere.help")} ${t("providerPlacement.everywhere.ownerOnly")}`
          }
        >
          <Switch
            checked={everywhere}
            disabled={!canSetEverywhere || setEverywhere.isPending}
            onCheckedChange={(checked) => changeEverywhere(Boolean(checked))}
          />
        </SettingsRow>
      </SettingsSection>

      <PlacementRequestsCard />

      {providers.length === 0 ? (
        <p className="text-muted-foreground text-sm">{t("providerPlacement.noProviders")}</p>
      ) : (
        providers.map((provider) => (
          <ProviderRulesCard
            key={provider.id}
            provider={provider}
            rules={rules.filter((rule) => rule.provider_id === provider.id)}
            onAdd={() => setEditing({ provider, rule: null })}
            onEdit={(rule) => setEditing({ provider, rule })}
            onRemove={setRemoving}
          />
        ))
      )}

      {editing ? (
        <ProviderPlacementRuleDialog
          key={`${editing.provider.id}-${editing.rule?.id ?? "new"}`}
          provider={editing.provider}
          rule={editing.rule}
          onClose={() => setEditing(null)}
        />
      ) : null}

      <ConfirmDialog
        open={confirmEverywhere}
        onOpenChange={(open) => !open && setConfirmEverywhere(false)}
        title={t("providerPlacement.everywhere.confirmTitle")}
        description={t("providerPlacement.everywhere.confirmDescription")}
        confirmLabel={t("providerPlacement.everywhere.confirm")}
        isLoading={setEverywhere.isPending}
        onConfirm={() => applyEverywhere(true)}
      />

      <ConfirmDialog
        open={removing !== null}
        onOpenChange={(open) => !open && setRemoving(null)}
        title={t("providerPlacement.removeTitle")}
        description={t("providerPlacement.removeDescription", {
          community: removing?.community_name ?? "",
        })}
        confirmLabel={t("providerPlacement.remove")}
        destructive
        isLoading={deleteRule.isPending}
        onConfirm={() => removing && removeRule(removing)}
      />
    </div>
  );
};

/** One provider and the rules written on it. */
const ProviderRulesCard = ({
  provider,
  rules,
  onAdd,
  onEdit,
  onRemove,
}: {
  provider: PlacementProviderRead;
  rules: ProviderPlacementRuleRead[];
  onAdd: () => void;
  onEdit: (rule: ProviderPlacementRuleRead) => void;
  onRemove: (rule: ProviderPlacementRuleRead) => void;
}) => {
  const { t } = useTranslation("settings");
  return (
    <Card>
      <CardHeader className="flex flex-row items-start justify-between gap-4 space-y-0">
        <div className="flex min-w-0 items-start gap-3">
          <ProviderMark icon={provider.icon} className="mt-1" />
          <div className="min-w-0 space-y-1.5">
            <CardTitle>{provider.display_name}</CardTitle>
            {!provider.reports_groups && (
              <CardDescription>{t("providerPlacement.noGroups")}</CardDescription>
            )}
          </div>
        </div>
        <Button
          type="button"
          onClick={onAdd}
          aria-label={t("providerPlacement.addFor", { provider: provider.display_name })}
        >
          <Plus className="h-4 w-4" />
          {t("providerPlacement.add")}
        </Button>
      </CardHeader>
      <CardContent>
        {rules.length === 0 ? (
          <p className="text-muted-foreground text-sm">{t("providerPlacement.empty")}</p>
        ) : (
          <ul className="divide-y rounded-md border">
            {rules.map((rule) => (
              <li key={rule.id} className="flex items-center justify-between gap-4 px-3 py-3">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-medium">{describePlacementMatch(rule, t)}</span>
                    {!rule.applies && <NotApplyingBadge />}
                  </div>
                  <p className="text-muted-foreground text-sm">
                    {rule.initiative_name
                      ? t("providerPlacement.landsInInitiative", {
                          community: rule.community_name,
                          role: placementRoleLabel(rule.community_role, t),
                          initiative: rule.initiative_name,
                          initiativeRole: rule.initiative_role_name ?? "",
                        })
                      : t("providerPlacement.landsInCommunity", {
                          community: rule.community_name,
                          role: placementRoleLabel(rule.community_role, t),
                        })}
                  </p>
                </div>
                <div className="flex shrink-0 items-center gap-1">
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    aria-label={t("providerPlacement.editLabel")}
                    onClick={() => onEdit(rule)}
                  >
                    <Pencil className="h-4 w-4" />
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className="text-destructive"
                    aria-label={t("providerPlacement.remove")}
                    onClick={() => onRemove(rule)}
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
};

/**
 * Communities waiting for somebody to agree that the domain or tenant they
 * named on a connection is theirs. Shown only while there are any.
 */
const PlacementRequestsCard = () => {
  const { t } = useTranslation("settings");
  const requests = useListPlacementRequests();
  const agree = useAgreePlacementRequest();
  const rows = requests.data ?? [];
  if (rows.length === 0) return null;

  return (
    <SettingsSection
      title={t("providerPlacement.requests.title")}
      description={t("providerPlacement.requests.help")}
    >
      <ul className="space-y-3">
        {rows.map((row) => (
          <li
            key={row.connection_id}
            className="flex items-start justify-between gap-3 rounded-md border px-4 py-3"
          >
            <div className="min-w-0 space-y-1">
              <p className="font-medium text-sm">{row.community_name}</p>
              <p className="text-sm">
                {t("communities.sheet.narrowings.claims", {
                  provider: row.provider_display_name,
                  claim: row.claim,
                  values: row.claim_values.join(", "),
                })}
              </p>
              <p className="text-muted-foreground text-xs">
                {row.auto_join
                  ? t("communities.sheet.narrowings.joinsOnArrival")
                  : t("communities.sheet.narrowings.admitsOnly")}
              </p>
            </div>
            <Button
              size="sm"
              disabled={agree.isPending}
              onClick={() =>
                agree.mutate(
                  { communityId: row.community_id, connectionId: row.connection_id },
                  {
                    onSuccess: () =>
                      toast.success(
                        t("providerPlacement.requests.agreed", { community: row.community_name })
                      ),
                  }
                )
              }
            >
              {t("communities.sheet.narrowings.agree")}
            </Button>
          </li>
        ))}
      </ul>
    </SettingsSection>
  );
};
