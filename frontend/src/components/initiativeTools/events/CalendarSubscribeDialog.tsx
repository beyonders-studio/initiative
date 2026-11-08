import { useState } from "react";
import { useTranslation } from "react-i18next";

import { type ApiKeyMetadata, Tool } from "@/api/generated/initiativeAPI.schemas";
import { useListMyApiKeys } from "@/api/generated/users/users";
import { useCreateApiKey } from "@/hooks/useSecurity";
import { toast } from "@/lib/mascotToast";
import { buildApiUrl } from "@/lib/wsUrl";
import { Button } from "@/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/ui/dialog";

/** The longest name an API key takes. */
const KEY_NAME_MAX = 100;

type SubscribableCalendar = { id: number; name: string };

type CalendarSubscribeDialogProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  communityId: number;
  calendars: SubscribableCalendar[];
};

/**
 * Subscription links to calendars, for another calendar app: one link per
 * calendar, so each stays a calendar of its own there.
 *
 * A link is a personal API key that names its calendar, so it follows the
 * community's API-access setting, shows under Settings › Security, and is
 * shown once. Getting another replaces it.
 */
export const CalendarSubscribeDialog = ({
  open,
  onOpenChange,
  communityId,
  calendars,
}: CalendarSubscribeDialogProps) => {
  const { t } = useTranslation(["calendars", "common"]);
  const keysQuery = useListMyApiKeys();
  const linked = new Set(
    (keysQuery.data?.keys ?? [])
      .filter((key) => key.resource_type === Tool.calendar && key.community_id === communityId)
      .map((key) => key.resource_id)
  );

  const [only] = calendars.length === 1 ? calendars : [];
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            {only ? t("subscribe.title", { name: only.name }) : t("subscribe.titleMany")}
          </DialogTitle>
          <DialogDescription>{t("subscribe.description")}</DialogDescription>
        </DialogHeader>
        <p className="text-muted-foreground text-sm">{t("subscribe.secret")}</p>
        {/* Links are shown once: each row holds its own, and closing the dialog
            drops them with the rows. */}
        <ul className="max-h-[50vh] space-y-3 overflow-y-auto">
          {calendars.map((calendar) => (
            <SubscribeRow
              key={calendar.id}
              communityId={communityId}
              calendar={calendar}
              hasLink={linked.has(calendar.id)}
              showName={!only}
            />
          ))}
        </ul>
        <p className="text-muted-foreground text-sm">{t("subscribe.manage")}</p>
        <DialogFooter>
          <Button type="button" onClick={() => onOpenChange(false)}>
            {t("common:done")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};

/**
 * A calendar's subscription link, made on request and shown once: a new
 * personal API key that names the calendar, replacing any it had.
 */
export const useSubscriptionLink = (communityId: number, calendarId: number) => {
  const [link, setLink] = useState<string | null>(null);
  const createLink = useCreateApiKey(
    {
      onSuccess: (data) => {
        const url = buildApiUrl(`c/${communityId}/calendars/${calendarId}/feed.ics`);
        url.searchParams.set("token", data.secret);
        setLink(url.toString());
      },
    },
    "calendars:subscribe.error"
  );
  const create = (name: string) =>
    createLink.mutate({
      name: name.slice(0, KEY_NAME_MAX),
      community_id: communityId,
      resource_type: Tool.calendar,
      resource_id: calendarId,
    });
  return { link, create, isPending: createLink.isPending };
};

/** A subscription link, to copy or open in a calendar app. */
export const SubscriptionLink = ({ link }: { link: string }) => {
  const { t } = useTranslation("calendars");
  const copyLink = () => {
    if (!navigator?.clipboard) {
      return;
    }
    void navigator.clipboard.writeText(link).then(() => {
      toast.success(t("subscribe.copied"));
    });
  };
  return (
    <>
      <code className="block break-all rounded-md border bg-muted px-3 py-2 font-mono text-sm">
        {link}
      </code>
      <div className="flex flex-wrap gap-2">
        <Button type="button" size="sm" variant="outline" onClick={copyLink}>
          {t("subscribe.copy")}
        </Button>
        <Button type="button" size="sm" variant="outline" asChild>
          <a href={link.replace(/^https?:/, "webcal:")}>{t("subscribe.open")}</a>
        </Button>
      </div>
    </>
  );
};

/** One calendar's link: made on request and shown once. */
const SubscribeRow = ({
  communityId,
  calendar,
  hasLink,
  showName,
}: {
  communityId: number;
  calendar: SubscribableCalendar;
  hasLink: boolean;
  showName: boolean;
}) => {
  const { t } = useTranslation("calendars");
  const { link, create, isPending } = useSubscriptionLink(communityId, calendar.id);

  return (
    <li className="space-y-2 rounded-md border p-3">
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          {showName ? <p className="truncate font-medium">{calendar.name}</p> : null}
          {hasLink && !link ? (
            <p className="text-muted-foreground text-sm">{t("subscribe.replaces")}</p>
          ) : null}
        </div>
        {link ? null : (
          <Button
            type="button"
            size="sm"
            disabled={isPending}
            onClick={() => create(t("subscribe.keyName", { name: calendar.name }))}
          >
            {hasLink ? t("subscribe.getNewLink") : t("subscribe.getLink")}
          </Button>
        )}
      </div>
      {link ? <SubscriptionLink link={link} /> : null}
    </li>
  );
};

/** A subscription key with its calendar's community: one a new link can be
 *  made in place of. */
export type SubscriptionKey = ApiKeyMetadata & { community_id: number; resource_id: number };

export const isSubscription = (key: ApiKeyMetadata): key is SubscriptionKey =>
  key.resource_type === Tool.calendar && key.resource_id != null && key.community_id != null;

/**
 * A new link for a calendar subscription, whose own link was shown once. It
 * replaces the key, keeping its name, so the old link stops working.
 */
export const NewSubscriptionLinkDialog = ({
  apiKey,
  onClose,
}: {
  apiKey: SubscriptionKey;
  onClose: () => void;
}) => {
  const { t } = useTranslation(["calendars", "common"]);
  const { link, create, isPending } = useSubscriptionLink(apiKey.community_id, apiKey.resource_id);
  // Once asked for, the old link is replaced whatever happens here, so the
  // dialog stays until the new one is shown.
  const close = () => {
    if (!isPending) onClose();
  };
  return (
    <Dialog open onOpenChange={(open) => (open ? undefined : close())}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("subscribe.newLinkTitle", { name: apiKey.name })}</DialogTitle>
          <DialogDescription>{t("subscribe.newLinkDescription")}</DialogDescription>
        </DialogHeader>
        {link ? (
          <div className="space-y-2">
            <SubscriptionLink link={link} />
          </div>
        ) : (
          <p className="text-muted-foreground text-sm">{t("subscribe.secret")}</p>
        )}
        <DialogFooter>
          {link ? (
            <Button type="button" onClick={onClose}>
              {t("common:done")}
            </Button>
          ) : (
            <>
              <Button type="button" variant="outline" disabled={isPending} onClick={close}>
                {t("common:cancel")}
              </Button>
              <Button type="button" disabled={isPending} onClick={() => create(apiKey.name)}>
                {t("subscribe.getNewLink")}
              </Button>
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};
