import { useLexicalComposerContext } from "@lexical/react/LexicalComposerContext";
import { useLexicalEditable } from "@lexical/react/useLexicalEditable";
import { useNavigate } from "@tanstack/react-router";
import { $getNodeByKey, type NodeKey, type SerializedEditorState } from "lexical";
import { Link2 } from "lucide-react";
import { createContext, lazy, Suspense, useContext } from "react";
import { useTranslation } from "react-i18next";

import type { SearchEntityType } from "@/api/generated/initiativeAPI.schemas";
import { AskWhereUnavailable } from "@/components/access/RequestAccess";
import { TaskDescription } from "@/components/tasks/TaskDescription";
import { Button } from "@/components/ui/button";
import { EmbedCallout, useEmbedFold } from "@/components/ui/editor/nodes/embed-callout";
import {
  $isReferenceEmbedNode,
  $showAsLink,
} from "@/components/ui/editor/nodes/reference-embed-node";
import { SmartChip } from "@/components/ui/editor/nodes/smart-chip";
import { TaskQueryEmbed } from "@/components/ui/editor/nodes/task-query-embed";
import { Skeleton } from "@/components/ui/skeleton";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { useReferenceEmbed } from "@/hooks/useSmartChips";
import { communityPath } from "@/lib/communityUrl";
import type { EmbedDisplay, TaskQuery } from "@/lib/embeds";
import { entityRefTypeFor } from "@/lib/entityResolver";
import { hasBody } from "@/lib/posts";
import { entityIcon } from "@/lib/searchResults";
import { entityRefRoute } from "@/lib/tools";
import { cn } from "@/lib/utils";

// Lazy for the reason a post's body is, and because the editor is what draws
// this component: importing it here would make the two modules each other's.
const Editor = lazy(() =>
  import("@/components/ui/editor/editor").then((m) => ({ default: m.Editor }))
);

/**
 * How many embedded bodies this one is inside. An embedded page draws its own
 * embeds as their names only, so a page embedding itself — or two pages
 * embedding each other — stops one level down instead of going on forever.
 */
const EmbedDepth = createContext(0);

/** The deepest an embed draws a body at: one page inside another, no further. */
const MAX_BODY_DEPTH = 1;

/** What a prose embed says: the page itself, read-only, in a pane of its own. */
function EmbeddedBody({ body }: { body: Record<string, unknown> }) {
  const depth = useContext(EmbedDepth);
  return (
    <EmbedDepth.Provider value={depth + 1}>
      <div className="max-h-96 overflow-y-auto rounded-md border bg-background/60 px-3">
        <Suspense fallback={<Skeleton className="my-2 h-16 w-full" />}>
          <Editor
            editorSerializedState={body as unknown as SerializedEditorState}
            readOnly
            showToolbar={false}
            variant="post"
            compact
          />
        </Suspense>
      </div>
    </EmbedDepth.Provider>
  );
}

interface ReferenceEmbedProps {
  entityType: SearchEntityType;
  entityId: number;
  /** The name as it read when written, shown when the thing cannot be read. */
  fallback: string;
  /** Folded to its name, as the page saved it. */
  collapsed: boolean;
  display: EmbedDisplay;
  /** The tasks it shows, for an embed of a filter. */
  query: TaskQuery | null;
  nodeKey: NodeKey;
}

/** What an embed draws: the tasks a filter matches, or one thing. */
export function ReferenceEmbed(props: ReferenceEmbedProps) {
  if (props.query) {
    return (
      <TaskQueryEmbed
        query={props.query}
        display={props.display}
        label={props.fallback}
        collapsed={props.collapsed}
        nodeKey={props.nodeKey}
      />
    );
  }
  return <ItemEmbed {...props} />;
}

/**
 * What an embed draws inside its callout: the thing's name, which opens it,
 * and below it what the thing says about itself — its description, or for a
 * page, the page.
 *
 * A thing that cannot be read — deleted, or never shared with this reader —
 * keeps the name it had, dimmed, and says so; the two look the same on
 * purpose, as they do for a link. One the reader knows is there, inside an
 * initiative of theirs, offers to ask for access instead.
 *
 * Shown as `fields`, it holds a smart chip for each fact chosen for this page —
 * its status, who has it, when it is due — under its name.
 */
function ItemEmbed({
  entityType,
  entityId,
  fallback,
  collapsed,
  display,
  nodeKey,
}: ReferenceEmbedProps) {
  const { t } = useTranslation(["editor", "search"]);
  const [editor] = useLexicalComposerContext();
  const editable = useLexicalEditable();
  const navigate = useNavigate();
  const communityId = useActiveCommunityId();
  const { data: embed, isFetched } = useReferenceEmbed(entityType, entityId);
  const depth = useContext(EmbedDepth);
  const fold = useEmbedFold(nodeKey, collapsed);

  const refType = entityRefTypeFor(entityType);
  const reachable = embed != null && refType !== null;

  const card = display.mode === "card";
  const facts = card ? [] : (display.fields ?? []);
  const showBody = card && Boolean(embed?.body && hasBody(embed.body) && depth < MAX_BODY_DEPTH);
  const showDescription = card && Boolean(embed?.description);
  const foldable = facts.length > 0 || showBody || showDescription;

  const showAsLink = () =>
    editor.update(() => {
      const node = $getNodeByKey(nodeKey);
      if ($isReferenceEmbedNode(node)) $showAsLink(node);
    });

  return (
    <EmbedCallout
      icon={entityIcon(entityType)}
      nodeKey={nodeKey}
      title={
        <button
          type="button"
          onClick={() => {
            if (reachable && refType) {
              void navigate({ to: communityPath(communityId, entityRefRoute(refType, entityId)) });
            }
          }}
          aria-disabled={!reachable}
          className={cn(
            "min-w-0 flex-1 text-left font-semibold",
            reachable ? "cursor-pointer hover:underline" : "cursor-default text-muted-foreground"
          )}
        >
          {embed?.title ?? fallback}
        </button>
      }
      meta={t(`search:types.${entityType}` as never)}
      actions={
        editable ? (
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="-my-1 size-7 shrink-0"
            onClick={showAsLink}
            aria-label={t("embeds.showAsLink")}
            title={t("embeds.showAsLink")}
          >
            <Link2 className="size-3.5" />
          </Button>
        ) : null
      }
      fold={foldable ? fold : null}
    >
      {fold.folded && foldable ? null : facts.length > 0 ? (
        <div className="flex flex-wrap items-center gap-1">
          {facts.map((kind) => (
            <SmartChip key={kind} chipKind={kind} entityId={entityId} fallback="" />
          ))}
        </div>
      ) : showBody && embed?.body ? (
        <EmbeddedBody body={embed.body} />
      ) : showDescription && embed?.description ? (
        <TaskDescription content={embed.description} />
      ) : isFetched && !embed ? (
        <AskWhereUnavailable kind={entityType} entityId={entityId}>
          <p className="text-muted-foreground text-sm">{t("references.unavailable")}</p>
        </AskWhereUnavailable>
      ) : null}
    </EmbedCallout>
  );
}
