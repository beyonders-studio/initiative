/**
 * Write or change one placement rule for a sign-in provider.
 *
 * A rule says who it matches — a group, a directory (a claim and its value),
 * or a group within a directory — and where they land: a community, at a
 * standing, and optionally an initiative there with a role. Editing keeps the
 * rule's provider and community; a rule pointed elsewhere is a new rule.
 *
 * The community picker searches by name and lists every community, with the
 * ones this provider's rules do not reach shown but not choosable. Initiatives
 * are listed once a community is chosen.
 */

import { useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  PlacementInitiativeRead,
  PlacementProviderRead,
  ProviderPlacementRuleRead,
} from "@/api/generated/initiativeAPI.schemas";
import {
  useCreatePlacementRule,
  usePlacementCommunities,
  usePlacementTargets,
  useUpdatePlacementRule,
} from "@/hooks/useProviderPlacement";
import { getErrorMessage } from "@/lib/errorMessage";
import { toast } from "@/lib/mascotToast";
import { AsyncCombobox } from "@/ui/async-combobox";
import { Button } from "@/ui/button";
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
import { Switch } from "@/ui/switch";

/** Sentinel for "the community itself", which has no initiative id. */
const COMMUNITY_ONLY = "community";

export interface ProviderPlacementRuleDialogProps {
  provider: PlacementProviderRead;
  /** The rule being edited; absent when adding one. */
  rule?: ProviderPlacementRuleRead | null;
  onClose: () => void;
}

export const ProviderPlacementRuleDialog = ({
  provider,
  rule = null,
  onClose,
}: ProviderPlacementRuleDialogProps) => {
  const { t } = useTranslation("settings");
  const editing = rule !== null;

  const [group, setGroup] = useState(rule?.claim_value ?? "");
  const [scoped, setScoped] = useState(Boolean(rule?.scope_claim || rule?.scope_value));
  const [scopeClaim, setScopeClaim] = useState(rule?.scope_claim ?? "");
  const [scopeValue, setScopeValue] = useState(rule?.scope_value ?? "");
  const [community, setCommunity] = useState<{ id: number; name: string } | null>(
    rule ? { id: rule.community_id, name: rule.community_name } : null
  );
  const [communityRole, setCommunityRole] = useState(rule?.community_role ?? "member");
  const [initiativeId, setInitiativeId] = useState(
    rule?.initiative_id != null ? String(rule.initiative_id) : COMMUNITY_ONLY
  );
  const [initiativeRoleId, setInitiativeRoleId] = useState(
    rule?.initiative_role_id != null ? String(rule.initiative_role_id) : ""
  );

  const [pickerOpen, setPickerOpen] = useState(false);
  const [search, setSearch] = useState("");
  const communitiesQuery = usePlacementCommunities(provider.id, search, {
    enabled: !editing && pickerOpen,
  });
  const communityItems = (communitiesQuery.data ?? []).map((row) => ({
    value: String(row.id),
    label: row.name,
    hint: row.placeable ? undefined : t("providerPlacement.notAccepted"),
    disabled: !row.placeable,
  }));

  const targetsQuery = usePlacementTargets(provider.id, community?.id ?? null);
  // An edited rule keeps its current initiative and role on offer even when
  // the list cannot be read, so the form shows what the rule says.
  const loadedInitiatives = targetsQuery.data ?? [];
  const initiatives: PlacementInitiativeRead[] =
    rule?.initiative_id != null &&
    !loadedInitiatives.some((initiative) => initiative.id === rule.initiative_id)
      ? [
          ...loadedInitiatives,
          {
            id: rule.initiative_id,
            name: rule.initiative_name ?? "",
            roles:
              rule.initiative_role_id != null
                ? [
                    {
                      id: rule.initiative_role_id,
                      name: rule.initiative_role_name ?? "",
                      is_manager: false,
                    },
                  ]
                : [],
          },
        ]
      : loadedInitiatives;
  const chosenInitiative = initiativeId === COMMUNITY_ONLY ? null : Number(initiativeId);
  const roles = initiatives.find((initiative) => initiative.id === chosenInitiative)?.roles ?? [];

  const createRule = useCreatePlacementRule();
  const updateRule = useUpdatePlacementRule();
  const saving = createRule.isPending || updateRule.isPending;

  const trimmedGroup = group.trim();
  const trimmedClaim = scopeClaim.trim();
  const trimmedValue = scopeValue.trim();
  const directoryComplete = scoped && trimmedClaim !== "" && trimmedValue !== "";
  const directoryHalfSet = scoped && (trimmedClaim !== "") !== (trimmedValue !== "");
  const hasMatch = trimmedGroup !== "" || directoryComplete;

  const canSubmit =
    hasMatch &&
    !directoryHalfSet &&
    community !== null &&
    (chosenInitiative === null || initiativeRoleId !== "") &&
    !saving;

  const submit = () => {
    if (!canSubmit || community === null) return;
    const fields = {
      claim_value: trimmedGroup || null,
      scope_claim: directoryComplete ? trimmedClaim : null,
      scope_value: directoryComplete ? trimmedValue : null,
      community_role: communityRole,
      // Both halves or neither: somebody placed in an initiative needs the
      // role to hold there.
      initiative_id: chosenInitiative,
      initiative_role_id: chosenInitiative !== null ? Number(initiativeRoleId) : null,
    };
    if (rule) {
      updateRule.mutate(
        { ruleId: rule.id, data: fields },
        {
          onSuccess: () => {
            toast.success(t("providerPlacement.saved"));
            onClose();
          },
          onError: (error) =>
            toast.error(getErrorMessage(error, "settings:providerPlacement.saveError")),
        }
      );
      return;
    }
    createRule.mutate(
      { ...fields, provider_id: provider.id, community_id: community.id },
      {
        onSuccess: () => {
          toast.success(t("providerPlacement.added"));
          onClose();
        },
        onError: (error) =>
          toast.error(getErrorMessage(error, "settings:providerPlacement.addError")),
      }
    );
  };

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>
            {editing ? t("providerPlacement.editTitle") : t("providerPlacement.addTitle")}
          </DialogTitle>
          <DialogDescription>
            {rule
              ? t("providerPlacement.editDescription", {
                  provider: provider.display_name,
                  community: rule.community_name,
                })
              : t("providerPlacement.addDescription", { provider: provider.display_name })}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="placement-group">{t("providerPlacement.groupLabel")}</Label>
            <Input
              id="placement-group"
              value={group}
              onChange={(event) => setGroup(event.target.value)}
              placeholder={t("providerPlacement.groupPlaceholder")}
            />
            <p className="text-muted-foreground text-xs">{t("providerPlacement.groupHelp")}</p>
          </div>

          <div className="space-y-3 rounded-md border px-4 py-3">
            <div className="flex items-start justify-between gap-4">
              <div className="space-y-1">
                <Label htmlFor="placement-scoped">{t("providerPlacement.directoryLabel")}</Label>
                <p className="text-muted-foreground text-xs">
                  {t("providerPlacement.directoryHelp")}
                </p>
              </div>
              <Switch id="placement-scoped" checked={scoped} onCheckedChange={setScoped} />
            </div>
            {scoped && (
              <div className="grid grid-cols-pair gap-3">
                <div className="space-y-2">
                  <Label htmlFor="placement-scope-claim">
                    {t("providerPlacement.directoryClaimLabel")}
                  </Label>
                  <Input
                    id="placement-scope-claim"
                    value={scopeClaim}
                    onChange={(event) => setScopeClaim(event.target.value)}
                    placeholder={t("providerPlacement.directoryClaimPlaceholder")}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="placement-scope-value">
                    {t("providerPlacement.directoryValueLabel")}
                  </Label>
                  <Input
                    id="placement-scope-value"
                    value={scopeValue}
                    onChange={(event) => setScopeValue(event.target.value)}
                    placeholder={t("providerPlacement.directoryValuePlaceholder")}
                  />
                </div>
              </div>
            )}
          </div>
          {!hasMatch && (
            <p className="text-muted-foreground text-xs">{t("providerPlacement.needsMatch")}</p>
          )}

          <div className="space-y-2">
            {/* The picker names itself; this heads the row. */}
            <p className="font-medium text-sm leading-none">
              {t("providerPlacement.communityLabel")}
            </p>
            {editing ? (
              <p className="font-medium text-sm">{community?.name}</p>
            ) : (
              <>
                <AsyncCombobox
                  aria-label={t("providerPlacement.communityLabel")}
                  items={communityItems}
                  value={community ? String(community.id) : null}
                  selectedLabel={community?.name ?? null}
                  onValueChange={(value) => {
                    const picked = communitiesQuery.data?.find((row) => String(row.id) === value);
                    if (!picked?.placeable) return;
                    setCommunity({ id: picked.id, name: picked.name });
                    setInitiativeId(COMMUNITY_ONLY);
                    setInitiativeRoleId("");
                  }}
                  onSearchChange={setSearch}
                  onOpenChange={setPickerOpen}
                  loading={communitiesQuery.isLoading}
                  placeholder={t("providerPlacement.communityPlaceholder")}
                  searchPlaceholder={t("providerPlacement.communitySearch")}
                  emptyMessage={t("providerPlacement.communityEmpty")}
                />
                <p className="text-muted-foreground text-xs">
                  {t("providerPlacement.communityHelp")}
                </p>
              </>
            )}
          </div>

          <div className="space-y-2">
            <Label htmlFor="placement-role">{t("communityAuth.rules.standingLabel")}</Label>
            <Select value={communityRole} onValueChange={setCommunityRole}>
              <SelectTrigger id="placement-role">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="member">{t("communityAuth.rules.role.member")}</SelectItem>
                <SelectItem value="admin">{t("communityAuth.rules.role.admin")}</SelectItem>
              </SelectContent>
            </Select>
          </div>

          {community !== null && (
            <div className="space-y-2">
              <Label htmlFor="placement-initiative">
                {t("communityAuth.rules.initiativeLabel")}
              </Label>
              <Select
                value={initiativeId}
                onValueChange={(value) => {
                  setInitiativeId(value);
                  setInitiativeRoleId("");
                }}
              >
                <SelectTrigger id="placement-initiative">
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
              {targetsQuery.isError && (
                <p className="text-muted-foreground text-xs">
                  {t("providerPlacement.targetsUnavailable")}
                </p>
              )}
            </div>
          )}

          {chosenInitiative !== null && (
            <div className="space-y-2">
              <Label htmlFor="placement-initiative-role">
                {t("communityAuth.rules.initiativeRoleLabel")}
              </Label>
              <Select value={initiativeRoleId} onValueChange={setInitiativeRoleId}>
                <SelectTrigger id="placement-initiative-role">
                  <SelectValue placeholder={t("communityAuth.rules.initiativeRolePlaceholder")} />
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
          )}
        </div>

        <DialogFooter>
          <Button type="button" variant="outline" onClick={onClose}>
            {t("authProviders.cancel")}
          </Button>
          <Button type="button" onClick={submit} disabled={!canSubmit}>
            {editing ? t("providerPlacement.save") : t("providerPlacement.add")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};
