import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty";
import { host } from "@/ui/host";

interface StatusMessageProps {
  icon: ReactNode;
  title: string;
  description?: string;
  backTo?: string;
  /** Search params for the back link — without this, returning from an error
   *  state drops whatever the destination was filtered to. */
  backSearch?: Record<string, unknown>;
  backLabel?: string;
  /** Something to do about it, drawn beneath the description. */
  action?: ReactNode;
}

export function StatusMessage({
  icon,
  title,
  description,
  backTo,
  backSearch,
  backLabel,
  action,
}: StatusMessageProps) {
  return (
    <Empty>
      <EmptyHeader>
        <EmptyMedia variant="icon">{icon}</EmptyMedia>
        <EmptyTitle>{title}</EmptyTitle>
        {description && <EmptyDescription>{description}</EmptyDescription>}
      </EmptyHeader>
      {action}
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
