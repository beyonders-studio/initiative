import { useTranslation } from "react-i18next";

import type { EndpointRef } from "@/api/generated/initiativeAPI.schemas";
import { RelationsSection } from "@/components/entities/RelationsSection";
import { useWidthClass } from "@/ui/lib/useWidthClass";
import { cn } from "@/ui/lib/utils";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/ui/sheet";

interface WikiPageConnectionsProps {
  entity: EndpointRef;
  initiativeId: number | null;
  className?: string;
}

/**
 * What this page — or a file filed in the wiki — connects to: the same
 * Connections section every tool shows.
 *
 * Read-only here. A wiki is explored rather than administered, and its links
 * are made by writing them — `[[` in the body.
 */
export const WikiPageConnections = ({
  entity,
  initiativeId,
  className,
}: WikiPageConnectionsProps) => (
  <RelationsSection
    entity={entity}
    initiativeId={initiativeId}
    canEdit={false}
    // A wiki reads its links as a list, the way a wiki always has.
    defaultLayout="rows"
    collapseKey={`${entity.type}:${entity.id}:relationsCollapsed`}
    className={className}
  />
);

/** The connections where there is no gutter beside the words for them: a
 *  drawer from the bottom on a phone, from the side on anything wider. */
export const WikiConnectionsSheet = ({
  entity,
  initiativeId,
  open,
  onOpenChange,
}: WikiPageConnectionsProps & {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) => {
  const { t } = useTranslation("wikis");
  const compact = useWidthClass() === "base";
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side={compact ? "bottom" : "right"}
        className={cn("flex flex-col gap-0 p-0", compact ? "max-h-[85svh]" : "w-full sm:max-w-sm")}
      >
        <SheetHeader className="sr-only">
          <SheetTitle className="sr-only">{t("links.title")}</SheetTitle>
        </SheetHeader>
        <div className="min-h-0 flex-1 overflow-y-auto p-4 pr-12">
          <WikiPageConnections entity={entity} initiativeId={initiativeId} />
        </div>
      </SheetContent>
    </Sheet>
  );
};
