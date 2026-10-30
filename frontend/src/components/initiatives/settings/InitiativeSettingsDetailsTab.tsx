import { Loader2 } from "lucide-react";
import type { FormEvent } from "react";
import { useTranslation } from "react-i18next";

import type { InitiativeRoleRead, Tool } from "@/api/generated/initiativeAPI.schemas";
import { ToolsSection } from "@/components/initiatives/ToolsToggles";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader } from "@/components/ui/card";
import { ColorPickerPopover } from "@/components/ui/color-picker-popover";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { useInitiativeDefaults } from "@/hooks/useInitiativeRoles";

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
      <Card>
        <CardHeader>
          <CardDescription>{t("settings.detailsDescription")}</CardDescription>
        </CardHeader>
        <CardContent>
          <form className="space-y-4" onSubmit={onSaveDetails}>
            <div className="grid grid-cols-pair gap-4">
              <div className="space-y-2">
                <Label htmlFor="initiative-name">{t("settings.nameLabel")}</Label>
                <Input
                  id="initiative-name"
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  maxLength={255}
                  disabled={!canManageMembers || isSaving}
                  required
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="initiative-color">{t("settings.colorLabel")}</Label>
                <ColorPickerPopover
                  id="initiative-color"
                  value={color}
                  onChange={setColor}
                  disabled={!canManageMembers || isSaving}
                  triggerLabel="Adjust"
                />
              </div>
            </div>
            <div className="space-y-2">
              <Label htmlFor="initiative-description">{t("settings.descriptionLabel")}</Label>
              <Textarea
                id="initiative-description"
                rows={4}
                value={description}
                onChange={(event) => setDescription(event.target.value)}
                placeholder={t("settings.descriptionPlaceholder")}
                disabled={!canManageMembers || isSaving}
              />
            </div>
            {canManageMembers ? (
              <Button type="submit" disabled={isSaving}>
                {isSaving ? (
                  <>
                    <Loader2 className="h-4 w-4 animate-spin" />
                    {t("settings.saving")}
                  </>
                ) : (
                  t("settings.saveChanges")
                )}
              </Button>
            ) : (
              <p className="text-muted-foreground text-sm">{t("settings.editPermissionNote")}</p>
            )}
          </form>
        </CardContent>
      </Card>
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
