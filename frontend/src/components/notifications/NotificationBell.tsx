import { useRouter } from "@tanstack/react-router";
import { Bell, CheckCheck, Loader2 } from "lucide-react";
import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import type { NotificationRead } from "@/api/generated/initiativeAPI.schemas";
import { notificationText, openNotification } from "@/components/notifications/notificationLine";
import { useAuth } from "@/hooks/useAuth";
import { useNotificationStreamConnected } from "@/hooks/useNotificationStream";
import {
  useAllUnreadNotifications,
  useMarkAllNotificationsRead,
  useMarkNotificationRead,
} from "@/hooks/useNotifications";
import { useStoreSellingAnswer } from "@/lib/storeSelling";
import type { TranslateFn } from "@/types/i18n";
import { Badge } from "@/ui/badge";
import { Button } from "@/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/ui/popover";
import { RelativeTime } from "@/ui/relative-time";

// How often the bell asks on its own, which is only ever when there is no
// channel to ask for it.
const NOTIFICATION_POLL_INTERVAL_MS = 30_000;

export const NotificationBell = () => {
  // Plan lines are worded by whether this device may sell; re-render once a
  // phone's store has said.
  useStoreSellingAnswer();
  const [open, setOpen] = useState(false);
  // Rows read while the popover is open. The list is unread-only, so without
  // this they would vanish under the pointer and reflow what is beneath them.
  const [justRead, setJustRead] = useState<number[]>([]);
  // Their content, kept because the unread-only query stops returning them the
  // moment the read lands.
  const readWhileOpen = useRef(new Map<number, NotificationRead>());
  const router = useRouter();
  const { user } = useAuth();
  // "exports" is loaded alongside so the export download's cross-namespace
  // toast keys (exports:export.*) are available when clicked from the bell.
  const { t } = useTranslation(["communities", "exports", "moderation"]);
  const isEnabled = Boolean(user);
  const streamConnected = useNotificationStreamConnected();

  // Everything still unread, every page of it. The popover is the working set
  // — what is left to deal with — which is what makes a number on the bell
  // unnecessary: you do not need to be told how many are waiting by something
  // you can open and see. Stopping at one page would break that promise for
  // exactly the people with most to look at.
  //
  // A connected tab holds no polling timer. The channel refetches the inbox
  // the moment it moves, and it reaches every worker rather than the one that
  // happened to write the row. What a timer used to cover was the channel
  // itself going quiet, and the server now says so when that has happened.
  // With no socket at all (a proxy that drops upgrades, an offline tab) there
  // is nothing to say it, so the poll stands.
  const notificationsQuery = useAllUnreadNotifications({
    enabled: isEnabled,
    refetchInterval: streamConnected ? false : NOTIFICATION_POLL_INTERVAL_MS,
  });

  const markReadMutation = useMarkNotificationRead();

  const markAllMutation = useMarkAllNotificationsRead();

  if (!user) {
    return null;
  }

  const unread = notificationsQuery.notifications;
  // A row read while the popover is open keeps its place, dimmed, until the
  // popover closes. The list is unread-only, so without this it would vanish
  // under the pointer and reflow everything beneath it.
  const held = justRead
    .map((id) => readWhileOpen.current.get(id))
    .filter((row): row is NotificationRead => row !== undefined);
  // Deduped by id: a row can be in both while the refetch that drops it from
  // the unread list is still in flight.
  const notifications = [
    ...new Map([...unread, ...held].map((row) => [row.id, row])).values(),
  ].sort((a, b) => b.created_at.localeCompare(a.created_at));
  const hasNotifications = notifications.length > 0;
  // A dot, not a number. The popover shows every unread item, so there is
  // nothing for a count to summarise.
  const unreadCount = notificationsQuery.unreadCount;
  const hasUnread = unreadCount > 0;

  const handleNotificationClick = (notification: NotificationRead) => {
    // The read is not awaited: it is applied to the cache as it is sent, so
    // the dot and the badge have already moved. The row keeps its place,
    // dimmed, until the popover closes.
    if (!notification.read_at) {
      readWhileOpen.current.set(notification.id, notification);
      setJustRead((seen) => [...seen, notification.id]);
    }
    if (
      openNotification(notification, {
        markRead: markReadMutation.mutate,
        navigate: (options) => router.navigate(options),
        t: t as TranslateFn,
      })
    ) {
      setOpen(false);
    }
  };

  const renderContent = () => {
    if (notificationsQuery.isLoading) {
      return (
        <div className="flex items-center justify-center py-8 text-muted-foreground text-sm">
          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          {t("notifications.loadingNotifications")}
        </div>
      );
    }
    if (!hasNotifications) {
      return (
        <div className="py-8 text-center text-muted-foreground text-sm">
          {t("notifications.allCaughtUp")}
        </div>
      );
    }
    return (
      // The list is the one part that scrolls, so the bound and the overflow
      // belong on it. A max-height alone on a wrapper only clips: the element
      // that overflows has to be the one carrying the limit.
      <div className="max-h-80 min-h-0 overflow-y-auto">
        <ul className="divide-y">
          {notifications.map((notification) => (
            <li key={notification.id}>
              <button
                type="button"
                className={`flex w-full items-start gap-3 px-2 py-3 text-left transition hover:bg-accent/50 ${
                  justRead.includes(notification.id) ? "opacity-50" : ""
                }`}
                onClick={() => handleNotificationClick(notification)}
              >
                <div className="flex-1">
                  <p className="text-foreground text-sm">
                    {notificationText(notification, t as TranslateFn)}
                  </p>
                  <RelativeTime
                    date={notification.created_at}
                    className="mt-1 block text-muted-foreground text-xs"
                  />
                </div>
                {justRead.includes(notification.id) ? null : (
                  <span className="mt-1 h-2.5 w-2.5 rounded-full bg-primary" />
                )}
              </button>
            </li>
          ))}
        </ul>
      </div>
    );
  };

  return (
    <Popover
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (!next) {
          // The list settles now rather than under the pointer.
          setJustRead([]);
          readWhileOpen.current.clear();
        }
      }}
    >
      <PopoverTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          className="relative"
          aria-label={
            hasUnread
              ? t("notifications.ariaLabelCount", { count: unreadCount })
              : t("notifications.ariaLabel")
          }
        >
          <Bell className="h-5 w-5" />
          {hasUnread ? (
            // The bell counts; the navigation does not. Here the number says
            // how much is waiting without opening anything, and it is one
            // number about one list. Repeated down a tree it would be
            // arithmetic — which is why a community, an initiative and a tool
            // each get a dot instead.
            <Badge
              aria-hidden
              className="absolute -top-1 -right-1 h-5 min-w-5 justify-center rounded-full px-1 py-0 text-2xs"
            >
              {unreadCount > 99 ? "99+" : unreadCount}
            </Badge>
          ) : null}
        </Button>
      </PopoverTrigger>
      <PopoverContent collisionPadding={8} className="flex w-80 flex-col overflow-hidden">
        <div className="flex shrink-0 items-center justify-between border-b pb-2">
          <p className="font-semibold text-sm">{t("notifications.title")}</p>
          <Button
            variant="ghost"
            size="sm"
            className="text-xs"
            disabled={!hasUnread || markAllMutation.isPending}
            onClick={() => markAllMutation.mutate()}
          >
            <CheckCheck className="h-3 w-3" />
            {t("notifications.markAllRead")}
          </Button>
        </div>
        {renderContent()}
        <div className="shrink-0 border-t pt-2">
          <Button
            variant="ghost"
            size="sm"
            className="w-full text-xs"
            onClick={() => {
              setOpen(false);
              router.navigate({ to: "/notifications" });
            }}
          >
            {t("notifications.seeAll")}
          </Button>
        </div>
      </PopoverContent>
    </Popover>
  );
};
