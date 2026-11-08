/**
 * The two questions the tool master switch used to skip.
 *
 * Turning an opt-in tool ON is two decisions, not one: the initiative offers
 * the tool, and each role is granted the permission to see it. The switch only
 * ever made the first, which left the manager who flipped it looking at a tool
 * nobody else could find. `ToolEnableDialog` asks the second decision at the
 * moment it is being made.
 *
 * Turning it OFF hides everything in it from everyone at once, which is worth
 * saying out loud before it happens — `ToolDisableDialog` says it, and says
 * that nothing is deleted.
 */

import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { Tool } from "@/api/generated/initiativeAPI.schemas";
import { toolCamelPlural } from "@/lib/tools";
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
import { Label } from "@/ui/label";
import { RadioGroup, RadioGroupItem } from "@/ui/radio-group";

/** Who a tool is being turned on for. */
export type ToolAudience = "everyone" | "managers";

export interface ToolEnableDialogProps {
  /** The tool being turned on, or null when the dialog is closed. */
  tool: Tool | null;
  onOpenChange: (open: boolean) => void;
  onConfirm: (tool: Tool, audience: ToolAudience) => void;
  isSaving: boolean;
}

export const ToolEnableDialog = ({
  tool,
  onOpenChange,
  onConfirm,
  isSaving,
}: ToolEnableDialogProps) => {
  const { t } = useTranslation(["initiatives", "common"]);
  const [audience, setAudience] = useState<ToolAudience>("everyone");

  // Each tool is its own question; don't carry the last answer into the next.
  const [prevTool, setPrevTool] = useState(tool);
  if (prevTool !== tool) {
    setPrevTool(tool);
    if (tool) setAudience("everyone");
  }

  const toolName = tool ? t(`${toolCamelPlural(tool)}Feature` as never) : "";

  return (
    <Dialog open={tool !== null} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("settings.toolAudience.enableTitle", { tool: toolName })}</DialogTitle>
          <DialogDescription>{t("settings.toolAudience.enableDescription")}</DialogDescription>
        </DialogHeader>
        <RadioGroup
          value={audience}
          onValueChange={(value) => setAudience(value as ToolAudience)}
          className="gap-3"
        >
          <div className="flex items-start gap-3 rounded-md border p-3">
            <RadioGroupItem value="everyone" id="tool-audience-everyone" className="mt-1" />
            <div className="space-y-0.5">
              <Label htmlFor="tool-audience-everyone" className="font-medium">
                {t("settings.toolAudience.everyoneLabel")}
              </Label>
              <p className="text-muted-foreground text-xs">
                {t("settings.toolAudience.everyoneDescription")}
              </p>
            </div>
          </div>
          <div className="flex items-start gap-3 rounded-md border p-3">
            <RadioGroupItem value="managers" id="tool-audience-managers" className="mt-1" />
            <div className="space-y-0.5">
              <Label htmlFor="tool-audience-managers" className="font-medium">
                {t("settings.toolAudience.managersLabel")}
              </Label>
              <p className="text-muted-foreground text-xs">
                {t("settings.toolAudience.managersDescription")}
              </p>
            </div>
          </div>
        </RadioGroup>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={isSaving}>
            {t("common:cancel")}
          </Button>
          <Button onClick={() => tool && onConfirm(tool, audience)} disabled={isSaving}>
            {t("settings.toolAudience.enableConfirm")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};

export interface ToolDisableDialogProps {
  tool: Tool | null;
  onOpenChange: (open: boolean) => void;
  onConfirm: (tool: Tool) => void;
  isSaving: boolean;
}

export const ToolDisableDialog = ({
  tool,
  onOpenChange,
  onConfirm,
  isSaving,
}: ToolDisableDialogProps) => {
  const { t } = useTranslation(["initiatives", "common"]);
  const toolName = tool ? t(`${toolCamelPlural(tool)}Feature` as never) : "";

  return (
    <ConfirmDialog
      open={tool !== null}
      onOpenChange={onOpenChange}
      title={t("settings.toolAudience.disableTitle", { tool: toolName })}
      description={t("settings.toolAudience.disableDescription", { tool: toolName })}
      confirmLabel={t("settings.toolAudience.disableConfirm")}
      cancelLabel={t("common:cancel")}
      loadingLabel={t("settings.saving")}
      isLoading={isSaving}
      destructive
      onConfirm={() => tool && onConfirm(tool)}
    />
  );
};
