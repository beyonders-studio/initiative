import { FileUp, MoreHorizontal } from "lucide-react";
import type { ReactNode } from "react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { Tool } from "@/api/generated/initiativeAPI.schemas";
import { EnvelopeImportDialog } from "@/components/imports/EnvelopeImportDialog";
import { NON_EXPORTABLE_TOOLS } from "@/lib/tools";
import { Button } from "@/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/ui/dropdown-menu";

export interface ToolImportActionProps {
  tool: Tool;
  /** Whether the user can create this tool's content in reach — the same gate
   * the page's create button uses. When false, the control renders nothing. */
  canImport: boolean;
  /** Set inside an initiative tab: the import target is fixed and the dialog
   * hides its initiative picker. */
  fixedInitiativeId?: number;
  /** "menu" (header kebab) or "button" (empty-state, beside Create). */
  variant?: "menu" | "button";
  onImported?: () => void;
}

/** The list-page import affordance for a single tool: a header overflow menu
 * item or an empty-state button, both opening the shared EnvelopeImportDialog.
 * Registry-gated (``importable``) and permission-gated, so a tool without an
 * import surface or a user without create rights sees nothing. */
export function ToolImportAction({
  tool,
  canImport,
  fixedInitiativeId,
  variant = "menu",
  onImported,
}: ToolImportActionProps) {
  const { t } = useTranslation("imports");
  const [dialogOpen, setDialogOpen] = useState(false);

  if (NON_EXPORTABLE_TOOLS.has(tool) || !canImport) {
    return null;
  }

  return (
    <>
      {variant === "menu" ? (
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="sm" aria-label={t("entry.menuLabel")}>
              <MoreHorizontal className="h-4 w-4" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem onSelect={() => setDialogOpen(true)}>
              <FileUp className="h-4 w-4" />
              {t("entry.importBackup")}
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      ) : (
        <Button variant="outline" size="sm" onClick={() => setDialogOpen(true)}>
          <FileUp className="h-4 w-4" />
          {t("entry.import")}
        </Button>
      )}
      <EnvelopeImportDialog
        tool={tool}
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        fixedInitiativeId={fixedInitiativeId}
        onImported={onImported}
      />
    </>
  );
}

/**
 * The same import affordance, split so it can live in a toolbar's *shared*
 * overflow menu: the entry goes inside the menu, the dialog must not — a
 * dropdown unmounts its content on close, taking a nested dialog with it.
 *
 * Returns `null` for both when the tool has no import surface or the user
 * can't create here, so a caller can spread them in unconditionally.
 */
export function useToolImportAction({
  tool,
  canImport,
  fixedInitiativeId,
  onImported,
}: Omit<ToolImportActionProps, "variant">): { menuItem: ReactNode; dialog: ReactNode } {
  const { t } = useTranslation("imports");
  const [dialogOpen, setDialogOpen] = useState(false);
  const available = !NON_EXPORTABLE_TOOLS.has(tool) && canImport;

  if (!available) {
    return { menuItem: null, dialog: null };
  }

  return {
    menuItem: (
      <DropdownMenuItem onSelect={() => setDialogOpen(true)}>
        <FileUp className="h-4 w-4" />
        {t("entry.importBackup")}
      </DropdownMenuItem>
    ),
    dialog: (
      <EnvelopeImportDialog
        tool={tool}
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        fixedInitiativeId={fixedInitiativeId}
        onImported={onImported}
      />
    ),
  };
}
