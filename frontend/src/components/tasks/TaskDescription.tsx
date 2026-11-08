import { type ComponentProps, useMemo } from "react";

import { CommentReferences } from "@/components/comments/CommentReferences";
import { Markdown } from "@/components/Markdown";

interface TaskDescriptionProps {
  content: string;
  /** The community the task is in, where that is not the one the page is in. */
  communityId?: number;
  className?: string;
  onChange?: ComponentProps<typeof Markdown>["onChange"];
}

/**
 * A task's description as it reads: markdown, with the people and things it
 * mentions shown by what they are called now rather than what they were called
 * when it was written.
 *
 * It resolves its own mentions, so mount it where one description is on
 * screen. A board of cards shows each card's excerpt instead, with the people
 * in all of them asked about once for the board.
 */
export const TaskDescription = ({
  content,
  communityId,
  className,
  onChange,
}: TaskDescriptionProps) => {
  const contents = useMemo(() => [content], [content]);
  return (
    <CommentReferences contents={contents} communityId={communityId}>
      <Markdown content={content} className={className} onChange={onChange} mentions />
    </CommentReferences>
  );
};
