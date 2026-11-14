import { Bell } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { ContentKind } from "@/api/generated/initiativeAPI.schemas";
import { useSubscription } from "@/hooks/usePersonalItems";
import { cn } from "@/ui/lib/utils";

interface SubscribeButtonProps {
  kind: ContentKind;
  entityId: number;
  /** The item's own community, where it is not the one the page is in. */
  communityId?: number;
  className?: string;
}

/** Subscribe to any tool or anything inside one: what changes in it notifies
 *  the reader and ranks higher in their activity feed. Beside the bookmark on a
 *  tool's page, and in the actions of a page for something inside a tool. */
export const SubscribeButton = ({
  kind,
  entityId,
  communityId,
  className,
}: SubscribeButtonProps) => {
  const { t } = useTranslation("common");
  const { subscribed, ready, toggle } = useSubscription(kind, entityId, communityId);
  const label = subscribed ? t("subscribe.remove") : t("subscribe.add");

  return (
    <button
      type="button"
      className={cn(
        "inline-flex size-9 shrink-0 items-center justify-center rounded-md text-muted-foreground transition hover:bg-accent hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-default",
        className
      )}
      aria-pressed={subscribed}
      aria-label={label}
      title={label}
      disabled={!ready}
      onClick={toggle}
    >
      <Bell
        className={cn("size-4", subscribed && "text-primary")}
        fill={subscribed ? "currentColor" : "none"}
        aria-hidden
      />
    </button>
  );
};
