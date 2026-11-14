import { useNavigate } from "@tanstack/react-router";
import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  InitiativeRoleRead,
  InitiativeUpdate,
  Tool,
} from "@/api/generated/initiativeAPI.schemas";
import { ToolsSection } from "@/components/initiatives/ToolsToggles";
import { SettingsPermissionRequired } from "@/components/settings/SettingsPermissionRequired";
import { SettingsSection } from "@/components/settings/SettingsSection";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import {
  useGrantToolToRoles,
  useInitiativeDefaults,
  useInitiativeRoles,
} from "@/hooks/useInitiativeRoles";
import { useInitiativeSettings } from "@/hooks/useInitiativeSettings";
import { useUpdateInitiative } from "@/hooks/useInitiatives";
import { useServerForm } from "@/hooks/useServerForm";
import { DEFAULT_COLOR } from "@/lib/initiativeColors";
import { toast } from "@/lib/mascotToast";
import { isToolEnabled, TOOLS, toolCamelPlural, toolViewPermission } from "@/lib/tools";
import { Button } from "@/ui/button";
import { ColorPickerPopover } from "@/ui/color-picker-popover";
import { Field } from "@/ui/field";
import { Input } from "@/ui/input";
import { Textarea } from "@/ui/textarea";

import { type ToolAudience, ToolDisableDialog, ToolEnableDialog } from "./ToolAudienceDialogs";

interface InitiativeSettingsDetailsTabProps {
  name: string;
  setName: (value: string) => void;
  description: string;
  setDescription: (value: string) => void;
  color: string;
  setColor: (value: string) => void;
  /** Master-switch value per toggleable tool. */
  toolSwitches: Partial<Record<Tool, boolean>>;
  onToggleTool: (tool: Tool, value: boolean) => void;
  canManageMembers: boolean;
  isSaving: boolean;
  onSaveDetails: (event: FormEvent<HTMLFormElement>) => void;
  /** The initiative's roles, so each enabled tool can say who can see it. */
  roles?: InitiativeRoleRead[];
  /** Grant a tool's view permission to every non-manager role. */
  onGrantToEveryone?: (tool: Tool) => void;
  /** Send the reader to the roles screen. */
  onManageRoles?: () => void;
}

const InitiativeSettingsDetailsTab = ({
  name,
  setName,
  description,
  setDescription,
  color,
  setColor,
  toolSwitches,
  onToggleTool,
  canManageMembers,
  isSaving,
  onSaveDetails,
  roles,
  onGrantToEveryone,
  onManageRoles,
}: InitiativeSettingsDetailsTabProps) => {
  const { t } = useTranslation(["initiatives", "common"]);
  // The switches the community set for every initiative are shown, not changed.
  const defaults = useInitiativeDefaults().data;

  return (
    <div className="space-y-6">
      <SettingsSection description={t("settings.detailsDescription")}>
        <form className="space-y-4" onSubmit={onSaveDetails}>
          <div className="grid grid-cols-pair gap-4">
            <Field label={t("settings.nameLabel")}>
              <Input
                value={name}
                onChange={(event) => setName(event.target.value)}
                maxLength={255}
                disabled={!canManageMembers || isSaving}
                required
              />
            </Field>
            <Field label={t("settings.colorLabel")}>
              <ColorPickerPopover
                value={color}
                onChange={setColor}
                disabled={!canManageMembers || isSaving}
              />
            </Field>
          </div>
          <Field label={t("settings.descriptionLabel")}>
            <Textarea
              rows={4}
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              placeholder={t("settings.descriptionPlaceholder")}
              disabled={!canManageMembers || isSaving}
            />
          </Field>
          {canManageMembers ? (
            <Button type="submit" pending={isSaving}>
              {isSaving ? t("settings.saving") : t("settings.saveChanges")}
            </Button>
          ) : (
            <p className="text-muted-foreground text-sm">{t("settings.editPermissionNote")}</p>
          )}
        </form>
      </SettingsSection>
      {/* Saves on change, unlike the details form above: each switch is a
          single setting, not a field waiting on a Save button. */}
      <ToolsSection
        layout="card"
        canManage={canManageMembers}
        isSaving={isSaving}
        values={toolSwitches}
        onToggle={onToggleTool}
        idPrefix="settings"
        roles={roles}
        onGrantToEveryone={onGrantToEveryone}
        onManageRoles={onManageRoles}
        setByCommunity={defaults?.tools}
      />
    </div>
  );
};

export const DetailsPage = () => {
  const { t } = useTranslation(["initiatives", "common"]);
  const { initiativeId, initiative, canManageMembers } = useInitiativeSettings();

  const communityId = useActiveCommunityId();
  const navigate = useNavigate();
  // Only once the roster has actually landed: an empty list while it loads (or
  // after it fails) would read as "no role can see this", which is the very
  // claim this screen exists to make trustworthy.
  const rolesQuery = useInitiativeRoles(initiativeId || null);
  const roles = rolesQuery.isSuccess ? rolesQuery.data : undefined;
  const grantToolToRoles = useGrantToolToRoles(initiativeId);

  // The tool a confirmation dialog is currently open for, per direction.
  const [toolToEnable, setToolToEnable] = useState<Tool | null>(null);
  const [toolToDisable, setToolToDisable] = useState<Tool | null>(null);

  // All three wait for Save, so a refetch mid-sentence must not take the
  // sentence away.
  const details = useServerForm(
    initiative,
    (loaded) => ({
      name: loaded?.name ?? "",
      description: loaded?.description ?? "",
      color: loaded?.color ?? DEFAULT_COLOR,
    }),
    initiative?.id
  );
  const { name, description, color } = details.values;
  const setName = (next: string) => details.set({ name: next });
  const setDescription = (next: string) => details.set({ description: next });
  const setColor = (next: string) => details.set({ color: next });

  // Shared with the tool switches, which write one field each — so settling the
  // details form belongs to the details save, not here, or a switch would mark
  // somebody's half-written description saved.
  const updateInitiative = useUpdateInitiative({
    onSuccess: () => {
      toast.success(t("settings.updated"));
    },
  });

  const handleSaveDetails = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const trimmedName = name.trim();
    if (!trimmedName) {
      toast.error(t("settings.nameRequired"));
      return;
    }
    const sent = details.values;
    updateInitiative.mutate(
      {
        initiativeId,
        data: {
          name: trimmedName,
          description: sent.description.trim() || undefined,
          color: sent.color,
        },
      },
      { onSuccess: () => details.settle(sent) }
    );
  };

  // The switch asks before it acts, because flipping it is only half of what
  // it looks like it does: the initiative offering a tool and a role being
  // allowed to see it are two separate gates, and answering only the first is
  // what left members staring at a sidebar the manager could see past. Both
  // directions go through a dialog — on to settle the audience, off to say
  // what it hides.
  const handleToggleTool = (tool: Tool, value: boolean) => {
    if (value) setToolToEnable(tool);
    else setToolToDisable(tool);
  };

  const setMasterSwitch = (tool: Tool, value: boolean, onSuccess?: () => void) =>
    updateInitiative.mutate(
      {
        initiativeId,
        data: { [toolViewPermission(tool)]: value } as InitiativeUpdate,
      },
      onSuccess ? { onSuccess } : undefined
    );

  // Granting always reports both ways. A grant that failed quietly would leave
  // exactly the state this whole screen exists to make visible: a tool that is
  // on and that nobody but a manager can see.
  const grantToEveryone = (tool: Tool) =>
    grantToolToRoles.mutate(
      { tool },
      {
        onSuccess: () =>
          toast.success(
            t("initiatives:settings.toolAudience.granted", {
              tool: t(`initiatives:${toolCamelPlural(tool)}Feature` as never),
            })
          ),
      }
    );

  const handleConfirmEnable = (tool: Tool, audience: ToolAudience) => {
    setToolToEnable(null);
    setMasterSwitch(tool, true, () => {
      if (audience === "everyone") grantToEveryone(tool);
    });
  };

  const handleConfirmDisable = (tool: Tool) => {
    setToolToDisable(null);
    setMasterSwitch(tool, false);
  };

  if (!canManageMembers) {
    return <SettingsPermissionRequired scope="initiative" />;
  }

  if (!initiative) {
    return null;
  }

  const isSaving = updateInitiative.isPending || grantToolToRoles.isPending;

  return (
    <>
      <InitiativeSettingsDetailsTab
        name={name}
        setName={setName}
        description={description}
        setDescription={setDescription}
        color={color}
        setColor={setColor}
        toolSwitches={Object.fromEntries(
          TOOLS.map((tool) => [tool, Boolean(isToolEnabled(tool, initiative))])
        )}
        onToggleTool={handleToggleTool}
        canManageMembers={canManageMembers}
        isSaving={isSaving}
        onSaveDetails={handleSaveDetails}
        roles={roles}
        onGrantToEveryone={grantToEveryone}
        onManageRoles={() =>
          navigate({
            to: "/c/$communityId/i/$initiativeId/settings/roles",
            params: { communityId: String(communityId), initiativeId: String(initiativeId) },
          })
        }
      />
      <ToolEnableDialog
        tool={toolToEnable}
        onOpenChange={(open) => !open && setToolToEnable(null)}
        onConfirm={handleConfirmEnable}
        isSaving={isSaving}
      />
      <ToolDisableDialog
        tool={toolToDisable}
        onOpenChange={(open) => !open && setToolToDisable(null)}
        onConfirm={handleConfirmDisable}
        isSaving={isSaving}
      />
    </>
  );
};
