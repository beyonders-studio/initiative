import { lazy, Suspense } from "react";

import { normalizeEditorState } from "@/lib/editorState";
import { hasBody } from "@/lib/posts";
import { cn } from "@/ui/lib/utils";
import { Skeleton } from "@/ui/skeleton";

// The editor is the largest thing in the bundle and a board is often the first
// page someone lands on, so it arrives on demand rather than in the route chunk.
const Editor = lazy(() =>
  import("@/components/editor/editor").then((m) => ({ default: m.Editor }))
);

interface PostBodyProps {
  /** The stored Lexical state. An empty object is a post with only a headline. */
  body: Record<string, unknown>;
  className?: string;
}

/**
 * A post's body, rendered read-only.
 *
 * The same editor that wrote it, with editing and the toolbar off — which is
 * what keeps an image, a smart chip and a mention looking the same in the feed
 * as they did in the composer. A chip re-reads its own state here too, so a
 * notice about a task keeps showing that task's *current* column.
 */
export const PostBody = ({ body, className }: PostBodyProps) => {
  if (!hasBody(body)) return null;
  return (
    <div className={cn("text-sm", className)}>
      <Suspense fallback={<Skeleton className="h-16 w-full" />}>
        <Editor
          editorSerializedState={normalizeEditorState(body)}
          readOnly
          showToolbar={false}
          variant="post"
          compact
        />
      </Suspense>
    </div>
  );
};
