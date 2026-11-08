import { useLexicalComposerContext } from "@lexical/react/LexicalComposerContext";
import { useLexicalEditable } from "@lexical/react/useLexicalEditable";
import { useNavigate } from "@tanstack/react-router";
import { $getNodeByKey, type NodeKey } from "lexical";
import { PanelTop } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { SearchEntityType } from "@/api/generated/initiativeAPI.schemas";
import { $isEntityMentionNode } from "@/components/editor/nodes/entity-mention-node";
import { $showAsEmbed } from "@/components/editor/nodes/reference-embed-node";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { useReferenceTitle } from "@/hooks/useSmartChips";
import { communityPath } from "@/lib/communityUrl";
import { entityRefTypeFor } from "@/lib/entityResolver";
import { entityIcon } from "@/lib/searchResults";
import { entityRefRoute } from "@/lib/tools";
import { Button } from "@/ui/button";
import { HoverCard, HoverCardContent, HoverCardTrigger } from "@/ui/hover-card";
import { cn } from "@/ui/lib/utils";

interface EntityReferenceProps {
  entityType: SearchEntityType;
  entityId: number;
  /** The name as it read when written. What an export shows, and what stands
   *  in when the thing can no longer be read. */
  fallback: string;
  showIcon?: boolean;
}

/**
 * A named thing, inside prose.
 *
 * Renders what it is called **now**, read from the page's one reference
 * request. Renaming a task changes every sentence that mentions it, in every
 * document and every comment, with none of them edited.
 *
 * A thing that cannot be read — deleted, or never shared with this reader —
 * shows the name it had, dimmed and going nowhere. Gone and out of reach look
 * the same on purpose: the server does not distinguish them either.
 */
export function EntityReference({
  entityType,
  entityId,
  fallback,
  showIcon = true,
}: EntityReferenceProps) {
  const { t } = useTranslation("editor");
  const navigate = useNavigate();
  const communityId = useActiveCommunityId();
  const live = useReferenceTitle(entityType, entityId);

  const refType = entityRefTypeFor(entityType);
  const reachable = live !== undefined && refType !== null;
  const label = live ?? fallback ?? t("references.gone");
  const Icon = entityIcon(entityType);

  const shared = "mx-0.5 inline-flex items-baseline gap-1 rounded px-1 align-baseline";

  if (!reachable) {
    return (
      <span
        className={cn(shared, "bg-muted/60 text-muted-foreground/80")}
        title={t("references.unavailable")}
      >
        {label}
      </span>
    );
  }

  return (
    <button
      type="button"
      onClick={() =>
        void navigate({ to: communityPath(communityId, entityRefRoute(refType, entityId)) })
      }
      className={cn(
        shared,
        "cursor-pointer bg-primary/10 font-medium text-primary hover:bg-primary/20"
      )}
    >
      {showIcon && <Icon className="size-3 shrink-0 self-center" />}
      {label}
    </button>
  );
}

/**
 * A `#` link as the editor draws it: the link, and — while the page is being
 * written — a hover offering to show the thing in full instead, as `![[ ]]`
 * would have.
 */
export function EditorEntityReference({
  nodeKey,
  ...props
}: EntityReferenceProps & { nodeKey: NodeKey }) {
  const { t } = useTranslation("editor");
  const [editor] = useLexicalComposerContext();
  const editable = useLexicalEditable();
  const link = <EntityReference {...props} />;
  if (!editable) return link;

  const showAsEmbed = () =>
    editor.update(() => {
      const node = $getNodeByKey(nodeKey);
      if ($isEntityMentionNode(node)) $showAsEmbed(node);
    });

  return (
    <HoverCard openDelay={400} closeDelay={100}>
      <HoverCardTrigger asChild>
        <span>{link}</span>
      </HoverCardTrigger>
      <HoverCardContent align="start" className="w-auto p-1">
        <Button type="button" variant="ghost" size="sm" onClick={showAsEmbed}>
          <PanelTop className="size-4" />
          {t("embeds.showAsEmbed")}
        </Button>
      </HoverCardContent>
    </HoverCard>
  );
}
