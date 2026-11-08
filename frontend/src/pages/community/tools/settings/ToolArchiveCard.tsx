/**
 * Putting a tool away, and taking it back out.
 *
 * One card for every tool, in the settings section they all share, because
 * archiving is one pair of endpoints for every kind — the set of things that
 * can be archived is the `Tool` enum, so anything that grows the enum gets this
 * without being wired up again.
 *
 * The two directions read different flags. Archiving is an ordinary edit.
 * Nothing on an archived entity may be edited, so the way back out is its own
 * answer, `can.unarchive`.
 */

import { Archive, ArchiveRestore } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { ArchivableType, ToolCan } from "@/api/generated/initiativeAPI.schemas";
import { useArchiveEntity, useUnarchiveEntity } from "@/hooks/useArchive";
import { toast } from "@/lib/mascotToast";
import { Button } from "@/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/ui/card";

import { useToolSettings } from "./ToolSettingsContext";

/** Whether this viewer has anything to do here — what gates the card and, in
 *  the layout, the tab that holds it. */
export const canUseArchiveCard = (entity: { can: ToolCan }): boolean =>
  entity.can.edit || entity.can.unarchive;

export const ToolArchiveCard = () => {
  const { t } = useTranslation("common");
  const { tool, entity } = useToolSettings();

  const archive = useArchiveEntity({
    onSuccess: () => toast.success(t("toolSettings.archive.archived", { name: entity.name })),
  });
  const unarchive = useUnarchiveEntity({
    onSuccess: () => toast.success(t("toolSettings.archive.unarchived", { name: entity.name })),
  });

  const isArchived = entity.archived_at !== null;
  const action = isArchived ? unarchive : archive;
  const target = { entityType: tool as ArchivableType, entityId: entity.id };

  if (!canUseArchiveCard(entity)) {
    return null;
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("toolSettings.archive.title")}</CardTitle>
        <CardDescription>
          {isArchived ? t("toolSettings.archive.isArchived") : t("toolSettings.archive.isActive")}
        </CardDescription>
      </CardHeader>
      <CardContent>
        <Button
          type="button"
          variant="outline"
          onClick={() => action.mutate(target)}
          disabled={action.isPending}
        >
          {isArchived ? (
            <>
              <ArchiveRestore className="h-4 w-4" />
              {action.isPending
                ? t("toolSettings.archive.unarchiving")
                : t("toolSettings.archive.unarchive")}
            </>
          ) : (
            <>
              <Archive className="h-4 w-4" />
              {action.isPending
                ? t("toolSettings.archive.archiving")
                : t("toolSettings.archive.archive")}
            </>
          )}
        </Button>
      </CardContent>
    </Card>
  );
};
