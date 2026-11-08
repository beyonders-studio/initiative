import { useRouter } from "@tanstack/react-router";
import { Check, CheckCheck, Trash2, Undo2 } from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type { NotificationRead } from "@/api/generated/initiativeAPI.schemas";
import { notificationText, openNotification } from "@/components/notifications/notificationLine";
import { useAuth } from "@/hooks/useAuth";
import { useCommunities } from "@/hooks/useCommunities";
import {
  useDismissNotification,
  useMarkAllNotificationsRead,
  useMarkNotificationRead,
  useMarkNotificationUnread,
  useNotificationHistory,
} from "@/hooks/useNotifications";
import { formatDayHeading, localDayKey } from "@/lib/formatDate";
import { useStoreSellingAnswer } from "@/lib/storeSelling";
import type { TranslateFn } from "@/types/i18n";
import { Button } from "@/ui/button";
import { LoadMore } from "@/ui/load-more";
import { ListSkeleton, SkeletonRegion } from "@/ui/page-skeletons";
import { RelativeTime } from "@/ui/relative-time";

type Filter = "all" | "unread" | "personal";

const FILTERS: Filter[] = ["all", "unread", "personal"];

/**
 * The record: everything that has happened, read and unread.
 *
 * Distinct from the bell's popover, which holds only what is still unread —
 * the working set. Neither is a shortened version of the other; they answer
 * "what is left for me" and "what happened".
 */
export const NotificationsInboxPage = () => {
  // Plan lines are worded by whether this device may sell; re-render once a
  // phone's store has said.
  useStoreSellingAnswer();
  // "exports" is loaded alongside for a finished export's download toasts.
  const { t } = useTranslation(["communities", "common", "exports", "moderation"]);
  const { user } = useAuth();
  const router = useRouter();
  const [filter, setFilter] = useState<Filter>("all");
  const [communityId, setCommunityId] = useState<number | undefined>(undefined);

  const { communities } = useCommunities();
  const history = useNotificationHistory({
    enabled: Boolean(user),
    unreadOnly: filter === "unread",
    personalOnly: filter === "personal",
    communityId,
  });

  const markRead = useMarkNotificationRead();
  const markUnread = useMarkNotificationUnread();
  const dismiss = useDismissNotification();
  const markAll = useMarkAllNotificationsRead();

  const rows = useMemo(
    () => history.data?.pages.flatMap((page) => page.notifications) ?? [],
    [history.data]
  );

  const days = useMemo(() => {
    const buckets = new Map<string, NotificationRead[]>();
    for (const row of rows) {
      const key = localDayKey(row.created_at);
      const bucket = buckets.get(key);
      if (bucket) bucket.push(row);
      else buckets.set(key, [row]);
    }
    return [...buckets.entries()];
  }, [rows]);

  const communityName = (id: number | null | undefined): string | null => {
    if (id === null || id === undefined) return null;
    return communities?.find((community) => community.id === id)?.name ?? null;
  };

  const open = (notification: NotificationRead) =>
    openNotification(notification, {
      markRead: markRead.mutate,
      navigate: (options) => router.navigate(options),
      t: t as TranslateFn,
    });

  if (!user) return null;

  return (
    <div className="mx-auto w-full max-w-3xl space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="font-semibold text-3xl tracking-tight">{t("notifications.inbox.title")}</h1>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => markAll.mutate()}
          disabled={markAll.isPending}
        >
          <CheckCheck className="h-4 w-4" />
          {t("notifications.markAllRead")}
        </Button>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <div className="flex rounded-md border p-0.5">
          {FILTERS.map((value) => (
            <Button
              key={value}
              variant={filter === value ? "secondary" : "ghost"}
              size="sm"
              className="h-7"
              onClick={() => setFilter(value)}
            >
              {t(`notifications.inbox.filters.${value}`)}
            </Button>
          ))}
        </div>
        {(communities?.length ?? 0) > 1 && (
          <select
            className="h-8 rounded-md border bg-background px-2 text-sm"
            value={communityId ?? ""}
            aria-label={t("notifications.inbox.filterByCommunity")}
            onChange={(event) =>
              setCommunityId(event.target.value ? Number(event.target.value) : undefined)
            }
          >
            <option value="">{t("notifications.inbox.allCommunities")}</option>
            {communities?.map((community) => (
              <option key={community.id} value={community.id}>
                {community.name}
              </option>
            ))}
          </select>
        )}
      </div>

      {history.isLoading ? (
        <SkeletonRegion>
          <ListSkeleton rows={6} />
        </SkeletonRegion>
      ) : rows.length === 0 ? (
        <p className="py-12 text-center text-muted-foreground text-sm">
          {t("notifications.inbox.empty")}
        </p>
      ) : (
        <div className="space-y-6">
          {days.map(([key, bucket]) => (
            <section key={key} className="space-y-1">
              <h2 className="font-medium text-muted-foreground text-xs uppercase tracking-wide">
                {formatDayHeading(key, t as TranslateFn)}
              </h2>
              <ul className="divide-y rounded-md border">
                {bucket.map((notification) => (
                  <li
                    key={notification.id}
                    className="group flex items-start gap-3 px-3 py-3 transition hover:bg-accent/40"
                  >
                    <button
                      type="button"
                      className="flex-1 text-left"
                      onClick={() => open(notification)}
                    >
                      <p
                        className={`text-sm ${notification.read_at ? "text-muted-foreground" : "text-foreground"}`}
                      >
                        {notificationText(notification, t as TranslateFn)}
                      </p>
                      <p className="mt-1 flex items-center gap-2 text-muted-foreground text-xs">
                        {communityName(notification.community_id) && (
                          <span>{communityName(notification.community_id)}</span>
                        )}
                        <RelativeTime date={notification.created_at} />
                      </p>
                    </button>
                    <div className="flex items-center gap-1 opacity-0 transition focus-within:opacity-100 group-hover:opacity-100">
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-7 w-7"
                        aria-label={
                          notification.read_at
                            ? t("notifications.inbox.markUnread")
                            : t("notifications.inbox.markRead")
                        }
                        onClick={() =>
                          notification.read_at
                            ? markUnread.mutate(notification.id)
                            : markRead.mutate(notification.id)
                        }
                      >
                        {notification.read_at ? (
                          <Undo2 className="h-3.5 w-3.5" />
                        ) : (
                          <Check className="h-3.5 w-3.5" />
                        )}
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-7 w-7"
                        aria-label={t("notifications.inbox.dismiss")}
                        onClick={() => dismiss.mutate(notification.id)}
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </Button>
                    </div>
                    {!notification.read_at && (
                      <span aria-hidden className="mt-2 h-2 w-2 shrink-0 rounded-full bg-primary" />
                    )}
                  </li>
                ))}
              </ul>
            </section>
          ))}

          <LoadMore
            hasMore={history.hasNextPage}
            loading={history.isFetchingNextPage}
            onLoadMore={history.fetchNextPage}
          />
        </div>
      )}
    </div>
  );
};
