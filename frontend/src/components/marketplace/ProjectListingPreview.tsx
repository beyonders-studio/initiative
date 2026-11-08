/**
 * A project listing, drawn on the real board from the listing alone.
 *
 * The envelope becomes the statuses, tasks and properties the board takes as
 * props, with its dates moved to start today, as installing today would put
 * them. Nothing here reads the viewer's community: the board is given its
 * property definitions rather than asking the initiative, nothing can be
 * dragged or archived, and a card's title leads back to this listing.
 */

import { format } from "date-fns";
import { useCallback, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type { MarketplaceListingDetail } from "@/api/generated/initiativeAPI.schemas";
import { ProjectTasksKanbanView } from "@/components/projects/ProjectTasksKanbanView";
import { useCommunityPath } from "@/lib/communityUrl";
import { projectListingBoard, readProjectEnvelope } from "@/lib/projectListing";
import { ToggleGroup, ToggleGroupItem } from "@/ui/toggle-group";

type Showing = "blank" | "example";

/** No project has id 0, so the fields the preview shows are remembered apart
 *  from every real board's. */
const PREVIEW_PROJECT_ID = 0;

const noop = () => {};

export function ProjectListingPreview({ listing }: { listing: MarketplaceListingDetail }) {
  const { t } = useTranslation("marketplace");
  const gp = useCommunityPath();
  const blank = readProjectEnvelope(listing.definition);
  const filled = readProjectEnvelope(listing.example);
  // The example, when there is one: a blank template is the least convincing
  // way to show what it is for.
  const [showing, setShowing] = useState<Showing>(filled ? "example" : "blank");
  const [collapsed, setCollapsed] = useState<Set<number>>(() => new Set());
  const envelope = showing === "example" && filled ? filled : blank;
  const board = useMemo(
    () => (envelope ? projectListingBoard(envelope, format(new Date(), "yyyy-MM-dd")) : null),
    [envelope]
  );
  const listingHref = gp(`/marketplace/${listing.public_id}`);
  // Stable, so the board's cards are not redrawn on every pass here.
  const taskHref = useCallback(() => listingHref, [listingHref]);

  if (!board) return null;

  return (
    <div className="space-y-4">
      {filled ? (
        <ToggleGroup
          type="single"
          variant="outline"
          className="justify-start"
          aria-label={t("projectPreview.showing")}
          value={showing}
          onValueChange={(next) => next && setShowing(next as Showing)}
        >
          <ToggleGroupItem value="blank" className="h-8 px-3">
            {t("projectPreview.blank")}
          </ToggleGroupItem>
          <ToggleGroupItem value="example" className="h-8 px-3">
            {t("projectPreview.example")}
          </ToggleGroupItem>
        </ToggleGroup>
      ) : null}
      <ProjectTasksKanbanView
        projectId={PREVIEW_PROJECT_ID}
        initiativeId={0}
        taskStatuses={board.taskStatuses}
        groupedTasks={board.groupedTasks}
        propertyDefinitions={board.propertyDefinitions}
        collapsedStatusIds={collapsed}
        onToggleCollapse={(statusId) =>
          setCollapsed((current) => {
            const next = new Set(current);
            if (!next.delete(statusId)) next.add(statusId);
            return next;
          })
        }
        canReorderTasks={false}
        taskHref={taskHref}
        sensors={undefined}
        activeTask={null}
        onDragStart={noop}
        onDragOver={noop}
        onDragEnd={noop}
        onDragCancel={noop}
      />
    </div>
  );
}
