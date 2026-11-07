import { useTranslation } from "react-i18next";

import { AnnouncementDialog } from "@/components/announcements/AnnouncementDialog";
import { useAnnouncements } from "@/hooks/useAnnouncements";
import { Button } from "@/ui/button";

/**
 * Shows the announcements queued for the signed-in reader, one at a time.
 *
 * Mounted once in the authenticated layout: the notices follow the account,
 * not the page, so this has no community, project or route of its own — though a
 * notice may name a route it waits for, which the queue handles.
 */
export const AnnouncementCenter = ({ enabled = true }: { enabled?: boolean }) => {
  const { t } = useTranslation("announcements");
  const { current, remaining, dismiss } = useAnnouncements(enabled);

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
