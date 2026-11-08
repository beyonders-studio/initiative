import { ChevronDown, FileDown, Loader2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import { useExportJob } from "@/hooks/useExportJob";
import { Button } from "@/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/ui/dropdown-menu";

export interface ExportFormatOption {
  /** The ``format`` query value ("pdf", "csv", "xlsx", "md", "json"). */
  format: string;
  /** exports-namespace key for the menu entry. */
  labelKey: string;
  /** Extra query params for this entry (e.g. ``{ layout: "checklist" }``). */
  extraParams?: Record<string, string>;
  /** Per-option filename stem override (e.g. the json backup's
   * ``{name}-{date}.initiative-project`` convention). */
  filenameStem?: string;
}

/** A client-side rendering offered beside the engine formats (a whiteboard's
 *  PNG/SVG, which only Excalidraw's own renderer can produce). */
export interface ExportExtraAction {
  labelKey: string;
  onSelect: () => void;
}

export interface ExportButtonProps {
  /** Source create route, e.g. "/exports/tasks" — relative to /c/{communityId}. */
  endpoint: string;
  /** The selector for the snapshot (filters, ids, project id, …). */
  params: Record<string, unknown>;
  /** Format menu entries; a single entry renders a plain button (no menu). */
  formats: ExportFormatOption[];
  /** Filename stem for inline downloads: ``{stem}.{format}``. */
  filenameStem: string;
  /** Idle-state label override; the busy label stays the shared "Exporting…". */
  label?: string;
  /** Adopt a stored pending job on mount — see useExportJob for the
   * one-adopter-per-view rule. */
  resumePending?: boolean;
  variant?: "outline" | "default";
  /** Client-side entries appended to the menu (e.g. whiteboard PNG/SVG,
   * which only Excalidraw's own renderer can produce — the server never
   * renders scenes). Forces the menu even with a single engine format. */
  extraActions?: ExportExtraAction[];
}

export function ExportButton({
  endpoint,
  params,
  formats,
  filenameStem,
  label,
  resumePending,
  variant = "outline",
  extraActions = [],
}: ExportButtonProps) {
  const { t } = useTranslation("exports");
  const { busy, start } = useExportJob({ resumePending });

  const handleExport = (option: ExportFormatOption) =>
    start({
      endpoint,
      params: { ...params, format: option.format, ...option.extraParams },
      fallbackFilename: `${option.filenameStem ?? filenameStem}.${option.format}`,
    });

  const idleLabel = label ?? t("export.button");
  // A single engine format with no extras needs no menu — the button IS the
  // action. In menu mode the trigger must NOT carry an onClick, or opening
  // the menu would also fire an export.
  const menuMode = formats.length > 1 || extraActions.length > 0;
  const trigger = (withChevron: boolean) => (
    <Button
      variant={variant}
      size="sm"
      disabled={busy}
      aria-label={idleLabel}
      title={idleLabel}
      onClick={menuMode ? undefined : () => void handleExport(formats[0])}
    >
      {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileDown className="h-4 w-4" />}
      <span className="hidden sm:inline">{busy ? t("export.preparing") : idleLabel}</span>
      {withChevron && !busy && <ChevronDown className="h-3 w-3 opacity-60" />}
    </Button>
  );

  if (!menuMode) {
    return trigger(false);
  }
  // The menu is organized by intent: the JSON envelope is the importable
  // backup; every other format (and the client-side extras) is a report
  // rendering of the content.
  const backupFormats = formats.filter((option) => option.format === "json");
  const reportFormats = formats.filter((option) => option.format !== "json");
  const hasReports = reportFormats.length > 0 || extraActions.length > 0;
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>{trigger(true)}</DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        {backupFormats.length > 0 && (
          <>
            <DropdownMenuLabel>{t("export.headingBackup")}</DropdownMenuLabel>
            {backupFormats.map((option) => (
              <DropdownMenuItem key={option.labelKey} onSelect={() => void handleExport(option)}>
                {t(option.labelKey as never)}
              </DropdownMenuItem>
            ))}
          </>
        )}
        {backupFormats.length > 0 && hasReports && <DropdownMenuSeparator />}
        {hasReports && (
          <>
            <DropdownMenuLabel>{t("export.headingReport")}</DropdownMenuLabel>
            {reportFormats.map((option) => (
              <DropdownMenuItem key={option.labelKey} onSelect={() => void handleExport(option)}>
                {t(option.labelKey as never)}
              </DropdownMenuItem>
            ))}
            {extraActions.map((action) => (
              <DropdownMenuItem key={action.labelKey} onSelect={action.onSelect}>
                {t(action.labelKey as never)}
              </DropdownMenuItem>
            ))}
          </>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
