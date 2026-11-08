import { TriangleAlert } from "lucide-react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/ui/button";
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/ui/empty";
import { host } from "@/ui/host";

interface StatusMessageProps {
  /** Defaults to a warning sign. */
  icon?: ReactNode;
  /** Defaults to the shared "Couldn't load this.", what a failed read says. */
  title?: string;
  description?: string;
  backTo?: string;
  /** Search params for the back link — without this, returning from an error
   *  state drops whatever the destination was filtered to. */
  backSearch?: Record<string, unknown>;
  backLabel?: string;
  /** Something to do about it, drawn beneath the description. */
  action?: ReactNode;
  /** Offers "Try again", which calls this: a failed query's `refetch`. */
  onRetry?: () => void;
}

export function StatusMessage({
  icon = <TriangleAlert />,
  title,
  description,
  backTo,
  backSearch,
  backLabel,
  action,
  onRetry,
}: StatusMessageProps) {
  const { t } = useTranslation("ui");
  return (
    // A failed read is announced as it replaces the loading placeholder.
    <Empty role={title === undefined ? "alert" : undefined}>
      <EmptyHeader>
        <EmptyMedia variant="icon">{icon}</EmptyMedia>
        <EmptyTitle>{title ?? t("loadError")}</EmptyTitle>
        {description && <EmptyDescription>{description}</EmptyDescription>}
      </EmptyHeader>
      {action}
      {onRetry && (
        <Button type="button" variant="outline" size="sm" onClick={() => onRetry()}>
          {t("tryAgain")}
        </Button>
      )}
      {backTo && backLabel && (
        <Button variant="link" size="sm" asChild className="px-0">
          <host.Link to={backTo} search={backSearch}>
            {backLabel}
          </host.Link>
        </Button>
      )}
    </Empty>
  );
}
