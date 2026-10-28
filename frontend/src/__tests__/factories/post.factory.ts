import type { PollOptionRead, PollRead, PostRead } from "@/api/generated/initiativeAPI.schemas";

import { ownerCan } from "./can";

let counter = 0;
let optionCounter = 100;

export function resetCounter(): void {
  counter = 0;
  optionCounter = 100;
}

/**
 * The smallest valid Lexical editor state holding one paragraph — the shape
 * the composer actually saves, so a test post reads the way a real one does.
 */
export function buildLexicalBody(text: string): Record<string, unknown> {
  return {
    root: {
      type: "root",
      format: "",
      indent: 0,
      version: 1,
      direction: "ltr",
      children: [
        {
          type: "paragraph",
          format: "",
          indent: 0,
          version: 1,
          direction: "ltr",
          children: [
            {
              type: "text",
              text,
              format: 0,
              style: "",
              mode: "normal",
              detail: 0,
              version: 1,
            },
          ],
        },
      ],
    },
  };
}

export function buildPost(overrides: Partial<PostRead> = {}): PostRead {
  counter++;
  return {
    id: counter,
    name: `Post ${counter}`,
    body: buildLexicalBody(`Notice body ${counter}`),
    excerpt: `Notice body ${counter}`,
    initiative_id: 1,
    community_id: 1,
    created_by: 1,
    // Every real row is signed, so a test post is too.
    author: {
      id: 1,
      username: `author${counter}`,
      discriminator: 1000,
      display_name: null,
      avatar_url: null,
      profile_decorations: {
        banner: null,
        frame: null,
        frame_tint: [],
        trophies: [],
        grad_year: null,
      },
      presence: "online",
    },
    created_at: "2026-01-15T00:00:00.000Z",
    updated_at: "2026-01-15T00:00:00.000Z",
    pinned_at: null,
    pinned_by: null,
    pin_expires_at: null,
    is_pinned: false,
    // Live by default, like a notice posted rather than scheduled. Pass
    // `is_published: false` with a `scheduled_for` to build a draft.
    published_at: "2026-01-15T00:00:00.000Z",
    scheduled_for: null,
    is_published: true,
    // Unread by default: that is what a notice is until somebody reads it, and
    // it is the state most cases are about.
    is_read: false,
    read_count: 0,
    archived_at: null,
    can: ownerCan(),
    comments_enabled: true,
    reactions_enabled: true,
    comments_locked_at: null,
    comment_count: 0,
    reactions: [],
    tags: [],
    properties: [],
    grants: [],
    // Most notices ask nothing, which is what makes a poll worth noticing.
    poll: null,
    ...overrides,
  };
}

/**
 * The question a notice asks.
 *
 * Two choices, nobody answered, open — the state a poll is in the moment it is
 * written. Option ids run from 101 so a test can tell them apart from post ids
 * at a glance.
 */
export function buildPoll(overrides: Partial<PollRead> = {}): PollRead {
  const options = (overrides.options ??
    ["Tuesday", "Thursday"].map((text) => buildPollOption(text))) as PollOptionRead[] | string[];
  return {
    id: 1,
    question: "Which night works?",
    allows_multiple: false,
    is_anonymous: false,
    hide_results: false,
    closes_at: null,
    is_closed: false,
    has_voted: false,
    results_visible: true,
    total_voters: 0,
    is_locked: false,
    ...overrides,
    options: options as PollOptionRead[],
  };
}

export function buildPollOption(
  text: string,
  overrides: Partial<PollOptionRead> = {}
): PollOptionRead {
  optionCounter++;
  return {
    id: optionCounter,
    text,
    position: optionCounter - 101,
    vote_count: 0,
    voted_by_me: false,
    ...overrides,
  };
}
