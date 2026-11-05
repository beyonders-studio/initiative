/**
 * Everything a tool entity is connected to, ready to drop on the page it
 * belongs on.
 *
 * Like the comment thread beside it, this takes the ENTITY rather than a pile
 * of fields pulled out of it: a tool's read schema already carries the two
 * facts a link needs — its id and the initiative it lives in — so a tool page
 * says which tool and which row, and a tenth tool needs no new wiring.
 *
 * `target` splits the thing whose links these are from the tool that answers
 * for them, the same way the comment panel does: an event's links are the
 * event's, while the cache they invalidate is the calendar's.
 */

import type { ReactNode } from "react";

import type { EndpointRef, Tool } from "@/api/generated/initiativeAPI.schemas";
import type { RelationsLayout } from "@/components/entities/RelationsSection";
import { RelationsSection } from "@/components/entities/RelationsSection";
import { referenceTypeFor } from "@/lib/references";
import type { RelationGroupKey } from "@/lib/relationships";
import type { ToolRelationEntity } from "@/lib/tools";

interface ToolRelationsPanelProps {
  /** Which tool answers for these links — whose cache a write refreshes. */
  tool: Tool;
  /** The tool entity itself, as its read schema returns it. */
  entity: ToolRelationEntity | null | undefined;
  /** The thing whose links these are, where it is not the tool entity itself —
   *  an event, a counter, a picture. */
  target?: EndpointRef;
  canEdit: boolean;
  /** What the thing is called, for the middle of the graph. */
  entityTitle?: string;
  defaultLayout?: RelationsLayout;
  groups?: RelationGroupKey[];
  headerActions?: ReactNode;
  className?: string;
}

export const ToolRelationsPanel = ({
  tool,
  entity,
  target,
  canEdit,
  entityTitle,
  defaultLayout,
  groups,
  headerActions,
  className,
}: ToolRelationsPanelProps) => {
  // Pages render their frame before the row arrives, the way their comment
  // panel does.
  if (!entity) return null;

  // A community-level entity — an plugin-installed calendar — belongs to no
  // initiative, and a link is only ever made inside one. Offering the panel
  // there would offer links the server refuses, so it is not offered.
  const initiativeId = entity.initiative_id ?? null;
  if (initiativeId == null) return null;

  const anchorType = target?.type ?? referenceTypeFor(tool);
  const anchorId = target?.id ?? entity.id;

  return (
    <RelationsSection
      entity={{ type: anchorType, id: anchorId }}
      initiativeId={initiativeId}
      anchorTool={{ tool, id: entity.id }}
      canEdit={canEdit}
      collapseKey={`${anchorType}:${anchorId}:relationsCollapsed`}
      {...(entityTitle !== undefined ? { entityTitle } : {})}
      {...(defaultLayout !== undefined ? { defaultLayout } : {})}
      {...(groups !== undefined ? { groups } : {})}
      {...(headerActions !== undefined ? { headerActions } : {})}
      {...(className !== undefined ? { className } : {})}
    />
  );
};
