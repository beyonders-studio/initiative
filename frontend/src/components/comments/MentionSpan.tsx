import { Link } from "@tanstack/react-router";
import type { ComponentPropsWithoutRef } from "react";
import { useTranslation } from "react-i18next";

import { useCommentReferences } from "@/components/comments/CommentReferences";
import { MENTION_BADGE, UserMention } from "@/components/user/UserMention";
import { useCommunities } from "@/hooks/useCommunities";
import { useReferenceKinds } from "@/hooks/useReferenceKinds";
import { communityPath } from "@/lib/communityUrl";
import { entityRefTypeFor } from "@/lib/entityResolver";
import { referenceRef } from "@/lib/smartChips";
import { entityRefRoute } from "@/lib/tools";

import type { MentionType } from "./remarkCommentPlugins";

type SpanProps = ComponentPropsWithoutRef<"span"> & { node?: unknown };

/** Mentions reach here as spans carrying their type, id, and label — the shape
 *  `remarkMentions` folds them into. Every other span passes through.
 *
 *  Shared by everything that renders markdown with mentions in it — a comment,
 *  a task's description — so a mention is the same chip wherever it is
 *  written. Current names come from the nearest `CommentReferences`, so every
 *  surface that renders mentions sits under one. */
const buildMentionSpan = (linked: boolean) =>
  function MentionSpan({ children, node: _node, ...props }: SpanProps) {
    const { t } = useTranslation("comments");
    const { activeCommunityId } = useCommunities();
    const references = useCommentReferences();
    const kinds = useReferenceKinds();

    const attrs = props as Record<string, string | undefined>;
    const type = attrs["data-mention-type"] as MentionType | undefined;
    const id = attrs["data-mention-id"];
    const label = attrs["data-mention-label"] ?? "";

    if (!type) {
      return <span {...props}>{children}</span>;
    }

    if (type === "user") {
      // The name is read, not trusted: a comment written a year ago says what
      // that person is called today. The chip resolves it, links to them, and
      // shows who they are on hover.
      return <UserMention userId={id ? Number(id) : null} fallback={label} disableLink={!linked} />;
    }

    // A mention carries only an id, and an entity's address names its
    // initiative — so these link at the `/go` resolver, which reads the entity
    // and redirects. An id-less mention, or a kind with no page of its own,
    // renders as plain text rather than a link that resolves to nothing.
    const refType = entityRefTypeFor(type);
    if (!refType || !id) {
      return <span>{label}</span>;
    }

    const live = references.titles.get(referenceRef(type, Number(id)));
    const text = t("contextPrefix", { type: kinds.label(type), name: live ?? label });
    // Nothing came back for it once the answer has arrived: deleted, or never
    // shared with this reader. It keeps its words and stops being a link.
    if (references.ready && live === undefined) {
      return <span className="text-muted-foreground/80">{text}</span>;
    }
    if (!linked) {
      return <span className={MENTION_BADGE}>{text}</span>;
    }

    // Build a community-scoped link directly instead of using the /navigate redirect.
    const path = entityRefRoute(refType, Number(id));
    return (
      <Link
        to={activeCommunityId ? communityPath(activeCommunityId, path) : path}
        className="text-primary hover:underline"
      >
        {text}
      </Link>
    );
  };

/** A mention that links to what it names. */
export const LinkedMentionSpan = buildMentionSpan(true);

/** A mention as plain words — for a body that itself sits inside a link. */
export const PlainMentionSpan = buildMentionSpan(false);
