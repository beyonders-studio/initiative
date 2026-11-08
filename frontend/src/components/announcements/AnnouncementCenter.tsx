import { useEffect, useSyncExternalStore } from "react";
import { useTranslation } from "react-i18next";

import { AnnouncementDialog } from "@/components/announcements/AnnouncementDialog";
import { useAnnouncementArchive, useAnnouncements } from "@/hooks/useAnnouncements";
import { toast } from "@/lib/mascotToast";
import { Button } from "@/ui/button";

// The notice a bell line asked to show again, kept outside React so the line
// opens the dialog this center draws.
let requested: string | null = null;
const listeners = new Set<() => void>();
const setRequested = (key: string | null) => {
  requested = key;
  for (const listener of listeners) listener();
};
const subscribe = (listener: () => void) => {
  listeners.add(listener);
  return () => listeners.delete(listener);
};

/** Show an announcement again: what its line in the notifications does. */
export const openAnnouncement = (key: string) => setRequested(key);

/**
 * Shows the announcements queued for the signed-in reader, one at a time, and
 * one asked for again from its line in the notifications.
 *
 * Mounted once in the authenticated layout: the notices follow the account,
 * not the page, so this has no community, project or route of its own — though a
 * notice may name a route it waits for, which the queue handles.
 */
export const AnnouncementCenter = ({ enabled = true }: { enabled?: boolean }) => {
  const { t } = useTranslation("announcements");
  const { current, remaining, dismiss } = useAnnouncements(enabled);
  const requestedKey = useSyncExternalStore(
    subscribe,
    () => requested,
    () => null
  );
  const archive = useAnnouncementArchive(requestedKey !== null);
  const again = archive.data?.items?.find((item) => item.key === requestedKey) ?? null;

  // A notice that has ended or been deleted since its line was written opens
  // nothing, and says so.
  const gone = requestedKey !== null && archive.isFetched && !archive.isFetching && !again;
  useEffect(() => {
    if (!gone) return;
    toast.info(t("dialog.gone"));
    setRequested(null);
  }, [gone, t]);

  if (again) {
    return (
      <AnnouncementDialog
        open
        title={again.title}
        category={again.category}
        sections={again.sections ?? []}
        onOpenChange={(open) => {
          if (!open) setRequested(null);
        }}
        footer={<Button onClick={() => setRequested(null)}>{t("dialog.gotIt")}</Button>}
      />
    );
  }

  if (!current) {
    return null;
  }

  // A notice that asks to be acknowledged more than once says so, rather than
  // reappearing tomorrow for no visible reason.
  const required = current.dismissals_required ?? 1;
  const acknowledgements = required - (current.dismiss_count ?? 0);
  const metaParts = [
    remaining > 0 ? t("dialog.more", { count: remaining }) : null,
    acknowledgements > 1 ? t("dialog.showsAgain", { count: acknowledgements - 1 }) : null,
  ].filter(Boolean);

  return (
    <AnnouncementDialog
      open
      title={current.title}
      category={current.category}
      sections={current.sections ?? []}
      meta={metaParts.length > 0 ? metaParts.join(" · ") : undefined}
      onOpenChange={(open) => {
        if (!open) dismiss(current.key);
      }}
      footer={<Button onClick={() => dismiss(current.key)}>{t("dialog.gotIt")}</Button>}
    />
  );
};
