/**
 * `/settings/advanced` — the tool's own extra operations, duplicating,
 * archiving, exporting, and deletion.
 *
 * Exporting and deleting are the owner's alone, so those cards are absent for
 * everyone else however they reached the address — and when that leaves the
 * section with nothing at all, it says so rather than rendering a blank page. The tab
 * bar hides the link on the same condition; this is the answer for the address
 * someone typed or bookmarked.
 */

import { useRouter } from "@tanstack/react-router";
import { Trash2 } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { SettingsPermissionRequired } from "@/components/settings/SettingsPermissionRequired";
import { useCommunityPath } from "@/lib/communityUrl";
import { toast } from "@/lib/mascotToast";
import { toolListRoute } from "@/lib/tools";
import {
  canUseArchiveCard,
  ToolArchiveCard,
} from "@/pages/community/tools/settings/ToolArchiveCard";
import {
  canUseDuplicateCard,
  ToolDuplicateCard,
} from "@/pages/community/tools/settings/ToolDuplicateCard";
import { ToolExportCard } from "@/pages/community/tools/settings/ToolExportCard";
import { useToolSettings } from "@/pages/community/tools/settings/ToolSettingsContext";
import { Button } from "@/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/ui/card";
import { ConfirmDialog } from "@/ui/confirm-dialog";

export const AdvancedPage = () => {
  const { t } = useTranslation("common");
  const router = useRouter();
  const gp = useCommunityPath();
  const { tool, entity, remove } = useToolSettings();

  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);

  const canArchive = canUseArchiveCard(entity);
  const hasAnything =
    entity.can.export || entity.can.delete || canArchive || canUseDuplicateCard(tool, entity);

  const handleDelete = () => {
    remove.mutate(entity.id, {
      onSuccess: () => {
        toast.success(t("toolSettings.deleted", { name: entity.name }));
        setDeleteDialogOpen(false);
        // Back to the tool's tab in the initiative this entity belonged to, or
        // to the community's own list for a community-level one (a plug-in's calendar).
        router.navigate({ to: gp(toolListRoute(tool, entity.initiative_id ?? null)) });
      },
    });
  };

  if (!hasAnything) {
    return <SettingsPermissionRequired scope="tool" />;
  }

  return (
    <div className="space-y-6">
      <ToolDuplicateCard />

      <ToolExportCard />

      <ToolArchiveCard />

      {entity.can.delete && (
        <Card className="border-destructive/50">
          <CardHeader>
            <CardTitle>{t("toolSettings.dangerZone")}</CardTitle>
            <CardDescription>{t("toolSettings.dangerZoneDescription")}</CardDescription>
          </CardHeader>
          <CardContent>
            <Button type="button" variant="destructive" onClick={() => setDeleteDialogOpen(true)}>
              <Trash2 className="h-4 w-4" />
              {t("delete")}
            </Button>
          </CardContent>
        </Card>
      )}

      <ConfirmDialog
        open={deleteDialogOpen}
        onOpenChange={setDeleteDialogOpen}
        title={t("toolSettings.deleteConfirmTitle", { name: entity.name })}
        description={t("toolSettings.deleteConfirmDescription")}
        confirmLabel={t("delete")}
        onConfirm={handleDelete}
        isLoading={remove.isPending}
        destructive
      />
    </div>
  );
};
