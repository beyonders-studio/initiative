/**
 * The export card every tool's Advanced section carries.
 *
 * An export hands the whole thing over, so it is offered to whoever may also
 * delete it — the owner rung, which the server checks again — and it lives
 * here rather than in the tool's header. It opens the export wizard for this
 * one entity. Everything it needs is derived from the tool: the endpoint, the
 * selector param and the formats. A tool whose formats depend on the entity (a
 * file's type), or whose content the person narrows on its page (a project's
 * tasks), passes that as `exportOptions` on its settings layout.
 */

import { useTranslation } from "react-i18next";

import { EntitiesExportButton } from "@/components/exports/BulkExportButton";
import { TOOL_EXPORT_FORMATS } from "@/components/exports/formats";
import { exportFilenameStem } from "@/lib/exportDownload";
import { toolEnvelopeType, toolKebabSingular } from "@/lib/tools";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/ui/card";

import { useToolSettings } from "./ToolSettingsContext";

export const ToolExportCard = () => {
  const { t } = useTranslation(["common", "exports"]);
  const { tool, entity, exportOptions } = useToolSettings();

  const baseFormats = exportOptions?.formats ?? TOOL_EXPORT_FORMATS[tool] ?? [];
  if (!entity.can.export || baseFormats.length === 0) {
    return null;
  }

  const stem = exportFilenameStem(entity.name, toolKebabSingular(tool));
  // The importable envelope keeps the name the importer answers to.
  const formats = baseFormats.map((option) =>
    option.format === "json" && !option.filenameStem
      ? { ...option, filenameStem: `${stem}.${toolEnvelopeType(tool)}` }
      : option
  );

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("common:toolSettings.export.title")}</CardTitle>
        <CardDescription>{t("common:toolSettings.export.description")}</CardDescription>
      </CardHeader>
      <CardContent>
        <EntitiesExportButton
          tool={tool}
          ids={[entity.id]}
          formats={formats}
          filenameStem={stem}
          extraActions={exportOptions?.extraActions}
          content={exportOptions?.content}
          variant="default"
        />
      </CardContent>
    </Card>
  );
};
