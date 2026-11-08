import { Lock, Pencil, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { useListAllAnnouncements } from "@/api/generated/announcements/announcements";
import type { AnnouncementOperatorRead } from "@/api/generated/initiativeAPI.schemas";
import { SettingsSection } from "@/components/settings/SettingsSection";
import { useDeleteAnnouncement } from "@/hooks/usePlatformAnnouncements";
import { toast } from "@/lib/mascotToast";
import { AnnouncementEditorDialog } from "@/pages/operator/AnnouncementEditorDialog";
import { Badge } from "@/ui/badge";
import { Button } from "@/ui/button";
import { ConfirmDialog } from "@/ui/confirm-dialog";
import { formatDateTime } from "@/ui/lib/formatDate";
import { Skeleton } from "@/ui/skeleton";

type Status = "draft" | "scheduled" | "live" | "expired";

const statusOf = (announcement: AnnouncementOperatorRead, now: number): Status => {
  if (!announcement.published_at) return "draft";
  if (new Date(announcement.published_at).getTime() > now) return "scheduled";
  if (announcement.expires_at && new Date(announcement.expires_at).getTime() <= now) {
    return "expired";
  }
  return "live";
};

const STATUS_VARIANT: Record<Status, "default" | "secondary" | "outline"> = {
  draft: "outline",
  scheduled: "secondary",
  live: "default",
  expired: "outline",
};

/**
 * Where the deployment's notices are written.
 *
 * Both kinds are listed: the ones authored here, and the ones compiled into
 * this build (shown read-only — they are changed by shipping a release).
 */
export const AnnouncementsPage = () => {
  const { t } = useTranslation(["announcements", "common"]);
  const { data, isLoading } = useListAllAnnouncements();
  const remove = useDeleteAnnouncement();

  const [editing, setEditing] = useState<AnnouncementOperatorRead | null>(null);
  const [editorOpen, setEditorOpen] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<AnnouncementOperatorRead | null>(null);

  const items = data?.items ?? [];
  const now = Date.now();

  const handleDelete = () => {
    if (!pendingDelete?.id) return;
    remove.mutate(pendingDelete.id, {
      onSuccess: () => toast.success(t("operator.deleted")),
      onSettled: () => setPendingDelete(null),
    });
  };

  return (
    <div className="space-y-6">
      <SettingsSection
        description={t("operator.subtitle")}
        action={
          <Button
            onClick={() => {
              setEditing(null);
              setEditorOpen(true);
            }}
          >
            <Plus className="h-4 w-4" />
            {t("operator.new")}
          </Button>
        }
        contentClassName="space-y-3"
      >
        {isLoading ? (
          <>
            <Skeleton className="h-16 w-full" />
            <Skeleton className="h-16 w-full" />
          </>
        ) : items.length === 0 ? (
          <p className="text-muted-foreground text-sm">{t("operator.empty")}</p>
        ) : (
          items.map((announcement) => {
            const status = statusOf(announcement, now);
            return (
              <div
                key={announcement.key}
                className="flex flex-wrap items-center justify-between gap-3 rounded-md border p-3"
              >
                <div className="min-w-0 space-y-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-medium">{announcement.title}</span>
                    <Badge variant={STATUS_VARIANT[status]}>{t(`operator.status.${status}`)}</Badge>
                    <Badge variant="secondary">{t(`category.${announcement.category}`)}</Badge>
                    {announcement.is_builtin ? (
                      <Badge variant="outline" className="gap-1">
                        <Lock className="h-3 w-3" />
                        {t("operator.builtin")}
                      </Badge>
                    ) : null}
                  </div>
                  <p className="text-muted-foreground text-xs">
                    {announcement.published_at
                      ? t("operator.publishedOn", {
                          date: formatDateTime(announcement.published_at),
                        })
                      : t("operator.notPublished")}
                    {" · "}
                    {t("operator.audience", {
                      role: t(`operator.roles.${announcement.min_platform_role ?? "member"}`),
                    })}
                    {announcement.community_admins_only
                      ? ` · ${t("operator.communityAdminsOnly")}`
                      : ""}
                    {announcement.audience_accounts && announcement.audience_accounts !== "everyone"
                      ? ` · ${t(`operator.accounts.${announcement.audience_accounts}`)}`
                      : ""}
                  </p>
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={announcement.is_builtin}
                    onClick={() => {
                      setEditing(announcement);
                      setEditorOpen(true);
                    }}
                  >
                    <Pencil className="h-4 w-4" />
                    {t("common:edit")}
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon"
                    disabled={announcement.is_builtin}
                    aria-label={t("common:delete")}
                    onClick={() => setPendingDelete(announcement)}
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </div>
              </div>
            );
          })
        )}
      </SettingsSection>

      <AnnouncementEditorDialog
        open={editorOpen}
        announcement={editing}
        onOpenChange={setEditorOpen}
      />

      <ConfirmDialog
        open={pendingDelete !== null}
        onOpenChange={(open) => {
          if (!open) setPendingDelete(null);
        }}
        title={t("operator.deleteTitle")}
        description={t("operator.deleteDescription", { title: pendingDelete?.title ?? "" })}
        confirmLabel={t("common:delete")}
        onConfirm={handleDelete}
      />
    </div>
  );
};
