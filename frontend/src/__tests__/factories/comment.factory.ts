import type {
  CommentRead,
  ReactionGroup,
  RecentActivityEntry,
} from "@/api/generated/initiativeAPI.schemas";

let counter = 0;

export function resetCounter(): void {
  counter = 0;
}

export function buildComment(overrides: Partial<CommentRead> = {}): CommentRead {
  counter++;
  return {
    id: counter,
    content: `Comment content ${counter}`,
    created_by: 1,
    task_id: null,
    wiki_page_id: null,
    file_id: null,
    project_id: null,
    queue_id: null,
    counter_group_id: null,
    calendar_id: null,
    dashboard_id: null,
    post_id: null,
    catalog_id: null,
    wiki_id: null,
    parent_comment_id: null,
    created_at: "2026-01-15T00:00:00.000Z",
    updated_at: null,
    imported_author_name: null,
    author: {
      id: 1,
      username: "comment-author",
      discriminator: 1001,
      display_name: "Comment Author",
      avatar_url: null,
      presence: "offline",
    },
    reactions: [],
    can_remove: false,
    removed: null,
    audience: "members",
    system_kind: null,
    ...overrides,
  };
}

/** One emoji's worth of reactions on something, as the API groups them. */
export function buildReactionGroup(overrides: Partial<ReactionGroup> = {}): ReactionGroup {
  return {
    emoji: "\u{1F44D}",
    count: 1,
    reacted: false,
    users: [
      {
        id: 1,
        username: "reactor",
        discriminator: 2002,
        display_name: "Reactor One",
        avatar_url: null,
      },
    ],
    ...overrides,
  };
}

/** An entry of the community-wide activity feed (`GET /comments/recent`). */
export function buildRecentActivityEntry(
  overrides: Partial<RecentActivityEntry> = {}
): RecentActivityEntry {
  counter++;
  return {
    comment_id: counter,
    content: `Comment content ${counter}`,
    created_at: "2026-01-15T00:00:00.000Z",
    author: {
      id: 1,
      username: "comment-author",
      discriminator: 1001,
      display_name: "Comment Author",
      avatar_url: null,
      presence: "offline",
    },
    project_id: null,
    project_name: null,
    entity_type: null,
    entity_id: null,
    entity_name: null,
    initiative_id: null,
    reactions: [],
    ...overrides,
  };
}
