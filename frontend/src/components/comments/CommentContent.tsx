import type { ComponentProps } from "react";

import { Markdown } from "@/components/Markdown";

type CommentContentProps = Pick<
  ComponentProps<typeof Markdown>,
  "content" | "compact" | "disableLinks" | "onChange" | "className" | "ref"
>;

/** A comment's body, with the mentions its composer writes read as chips. A
 *  picture stored here stays a picture; one from anywhere else becomes a
 *  link, so reading a comment never fetches from a site nobody chose. */
export const CommentContent = (props: CommentContentProps) => (
  <Markdown surface="comment" mentions {...props} />
);
