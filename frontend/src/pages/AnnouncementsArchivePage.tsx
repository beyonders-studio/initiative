import { Check } from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type { AnnouncementRead } from "@/api/generated/initiativeAPI.schemas";
import { AnnouncementDialog } from "@/components/announcements/AnnouncementDialog";
import { useAnnouncementArchive } from "@/hooks/useAnnouncements";
import { formatDate } from "@/lib/formatDate";
import { Badge } from "@/ui/badge";
import { Button } from "@/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/ui/card";
import { Skeleton } from "@/ui/skeleton";
import { ToggleGroup, ToggleGroupItem } from "@/ui/toggle-group";

/**
 * Unread means never acknowledged.
 *
 * Being *shown* a notice is recorded too, but it is not the same claim — a
 * dialog that appeared while someone was reaching for the close button is not
 * something they have read. Dismissing it is the deliberate act, so that is
 * what this counts.
 */
const isUnread = (announcement: AnnouncementRead): boolean =>
  (announcement.dismiss_count ?? 0) === 0;

type Filter = "all" | "unread";

/**
 * Everything this deployment has announced to the reader, still readable.
 *
 * A notice is shown once and then dismissed, which is right for a dialog and
 * wrong for the only copy — "what was that thing about the filters?" needs
 * somewhere to go. Reached from the sidebar footer, beside the docs link.
 */
export const AnnouncementsArchivePage = () => {
  const { t } = useTranslation("announcements");
  const { data, isLoading } = useAnnouncementArchive();
  const [reading, setReading] = useState<AnnouncementRead | null>(null);
  const [filter, setFilter] = useState<Filter>("all");

  const items = useMemo(() => data?.items ?? [], [data]);
  const unreadCount = useMemo(() => items.filter(isUnread).length, [items]);
  const visible = filter === "unread" ? items.filter(isUnread) : items;

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <h1 className="font-semibold text-3xl tracking-tight">{t("archive.title")}</h1>
        {items.length > 0 ? (
          <ToggleGroup
            type="single"
            value={filter}
            // A toggle group can be cleared by re-pressing the active item;
            // there is no "neither" here, so an empty value keeps what it had.
            onValueChange={(value) => value && setFilter(value as Filter)}
            variant="outline"
            size="sm"
          >
            <ToggleGroupItem value="all">
              {t("archive.filter.all", { count: items.length })}
            </ToggleGroupItem>
            <ToggleGroupItem value="unread">
              {t("archive.filter.unread", { count: unreadCount })}
            </ToggleGroupItem>
          </ToggleGroup>
        ) : null}
      </div>

      {isLoading ? (
        <div className="space-y-3">
          <Skeleton className="h-24 w-full" />
          <Skeleton className="h-24 w-full" />
        </div>
      ) : visible.length === 0 ? (
        <Card>
          <CardContent className="py-10 text-center text-muted-foreground text-sm">
            {filter === "unread" ? t("archive.allCaughtUp") : t("archive.empty")}
          </CardContent>
        </Card>
      ) : (
        visible.map((announcement) => (
          <Card key={announcement.key}>
            <CardHeader className="space-y-2">
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant="secondary">{t(`category.${announcement.category}`)}</Badge>
                {announcement.published_at ? (
                  <span className="text-muted-foreground text-xs">
                    {formatDate(announcement.published_at)}
                  </span>
                ) : null}
                {isUnread(announcement) ? (
                  <Badge variant="default">{t("archive.unread")}</Badge>
                ) : (
                  <span className="flex items-center gap-1 text-muted-foreground text-xs">
                    <Check className="h-3.5 w-3.5" />
                    {t("archive.readLabel")}
                  </span>
                )}
              </div>
              <CardTitle>{announcement.title}</CardTitle>
              <CardDescription className="line-clamp-2">
                {announcement.sections?.[0]?.heading ?? announcement.sections?.[0]?.body ?? ""}
              </CardDescription>
            </CardHeader>
            <CardContent>
              <Button variant="outline" size="sm" onClick={() => setReading(announcement)}>
                {t("archive.read")}
              </Button>
            </CardContent>
          </Card>
        ))
      )}

      {reading ? (
        <AnnouncementDialog
          open
          title={reading.title}
          category={reading.category}
          sections={reading.sections ?? []}
          onOpenChange={(open) => {
            if (!open) setReading(null);
          }}
          footer={<Button onClick={() => setReading(null)}>{t("dialog.gotIt")}</Button>}
        />
      ) : null}
    </div>
  );
};
