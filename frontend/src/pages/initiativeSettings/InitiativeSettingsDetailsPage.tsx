/**
 * `/settings` — an initiative's name, description, colour, and which optional
 * tools it offers. How people join it lives with the roster, on
 * `/settings/members`.
 *
 * The name/description/colour form saves on its button; the tool switches are
 * single settings that save on change, each sending only the field that moved.
 */

import { useNavigate } from "@tanstack/react-router";
import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import type { InitiativeUpdate, Tool } from "@/api/generated/initiativeAPI.schemas";
import { InitiativeSettingsDetailsTab } from "@/components/initiatives/settings/InitiativeSettingsDetailsTab";
import {
  type ToolAudience,
  ToolDisableDialog,
  ToolEnableDialog,
} from "@/components/initiatives/ToolAudienceDialogs";
import { SettingsPermissionRequired } from "@/components/settings/SettingsPermissionRequired";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { useGrantToolToRoles, useInitiativeRoles } from "@/hooks/useInitiativeRoles";
import { useInitiativeSettings } from "@/hooks/useInitiativeSettings";
import { useUpdateInitiative } from "@/hooks/useInitiatives";
import { useServerForm } from "@/hooks/useServerForm";
import { DEFAULT_COLOR } from "@/lib/initiativeColors";
import { toast } from "@/lib/mascotToast";
import { isToolEnabled, TOOLS, toolCamelPlural, toolViewPermission } from "@/lib/tools";

export const InitiativeSettingsDetailsPage = () => {
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
