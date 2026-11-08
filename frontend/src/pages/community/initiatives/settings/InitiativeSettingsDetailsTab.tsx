import type { FormEvent } from "react";
import { useTranslation } from "react-i18next";

import type { InitiativeRoleRead, Tool } from "@/api/generated/initiativeAPI.schemas";
import { ToolsSection } from "@/components/initiatives/ToolsToggles";
import { SettingsSection } from "@/components/settings/SettingsSection";
import { useInitiativeDefaults } from "@/hooks/useInitiativeRoles";
import { Button } from "@/ui/button";
import { ColorPickerPopover } from "@/ui/color-picker-popover";
import { Field } from "@/ui/field";
import { Input } from "@/ui/input";
import { Textarea } from "@/ui/textarea";

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

export const InitiativeSettingsDetailsTab = ({
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
