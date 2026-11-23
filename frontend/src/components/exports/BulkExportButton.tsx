import { FileDown } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { FileType, ToolCan } from "@/api/generated/initiativeAPI.schemas";
import { useReadPluginTool } from "@/api/generated/plugin-tools/plugin-tools";
import { ExportWizard, type ExportWizardScope } from "@/components/exports/ExportWizard";
import { genericFormatOptions, selectionExportFormats } from "@/components/exports/formats";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { exportFilenameStem } from "@/lib/exportDownload";
import { everyCan } from "@/lib/permissions";
import { toolText } from "@/lib/toolPlugins";
import { isBuiltInTool, toolRouteSegment } from "@/lib/tools";
import { Button } from "@/ui/button";

type EntitiesExportButtonProps = Omit<Extract<ExportWizardScope, { kind: "entities" }>, "kind"> & {
  variant?: "outline" | "default";
};

/** Opens the export wizard for named entities of one tool. The wizard stays
 *  mounted while closed, so a job started in it keeps polling (and delivers
 *  its download) after the dialog closes. */
export function EntitiesExportButton({
  variant = "outline",
  ...entities
}: EntitiesExportButtonProps) {
  const { t } = useTranslation("exports");
  const [open, setOpen] = useState(false);
  const label = t("export.button");
  return (
    <>
      <Button
        variant={variant}
        size="sm"
        aria-label={label}
        title={label}
        onClick={() => setOpen(true)}
      >
        <FileDown className="h-4 w-4" />
        <span className="hidden sm:inline">{label}</span>
      </Button>
      <ExportWizard scope={{ kind: "entities", ...entities }} open={open} onOpenChange={setOpen} />
    </>
  );
}

interface BulkExportButtonProps {
  /** The canonical tool — endpoint, selector param, and formats all derive
   * from the registry, so a bulk-export surface can't drift per page — or a
   * tool plug-in's kind, whose formats its read names. */
  tool: string;
  /** The selected entities, with what the viewer may do to each — and, for
   * files, the type that decides which formats they export to. */
  items: { id: number; can: ToolCan; file_type?: FileType }[];
}

/** Bulk-selection export for a tool's list page: one artifact per selected
 * entity in the chosen format, delivered as a zip (a selection of one stays a
 * plain file). Offered only when the viewer may export every one of them — the
 * owner's rung, as deleting is — and in a format every one of them has, and
 * shown disabled otherwise. */
export function BulkExportButton({ tool, items }: BulkExportButtonProps) {
  const { t, i18n } = useTranslation("exports");
  const builtIn = isBuiltInTool(tool) ? tool : null;
  const plugin = useReadPluginTool(useActiveCommunityId(), tool, {
    query: { enabled: builtIn === null },
  }).data;
  const formats = builtIn
    ? selectionExportFormats(builtIn, items)
    : plugin && genericFormatOptions(plugin.export_formats);
  const name = builtIn
    ? toolRouteSegment(builtIn)
    : plugin
      ? toolText(plugin.name, i18n.language)
      : tool;
  if (!formats || items.length === 0) {
    return null;
  }
  if (!everyCan(items, "export")) {
    return <BulkExportUnavailable title={t("export.ownerRequired")} />;
  }
  if (formats.length === 0) {
    return <BulkExportUnavailable title={t("export.noCommonFormat")} />;
  }
  return (
    <EntitiesExportButton
      tool={tool}
      ids={items.map((item) => item.id)}
      formats={formats}
      filenameStem={exportFilenameStem(name, plugin?.key ?? name)}
    />
  );
}

/** The export button a selection cannot use, saying why. */
function BulkExportUnavailable({ title }: { title: string }) {
  const { t } = useTranslation("exports");
  return (
    <Button variant="outline" size="sm" disabled title={title} aria-label={title}>
      <FileDown className="h-4 w-4" />
      <span className="hidden sm:inline">{t("export.button")}</span>
    </Button>
  );
}
