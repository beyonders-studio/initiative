/**
 * The post length limit is one number in two places, and the server owns it.
 *
 * The composer needs it locally to show a remaining count while somebody
 * types; the endpoint needs it to refuse what arrives. This pins the copy to
 * the original the way `locale-keys` pins the two message catalogues together,
 * so a change on the backend cannot leave the composer counting down to the
 * wrong number.
 */
import fs from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

import {
  hasBody,
  MAX_POLL_OPTION_CHARS,
  MAX_POLL_OPTIONS,
  MAX_POST_TEXT_CHARS,
  MIN_POLL_OPTIONS,
  postBoardTime,
  postPeriod,
} from "@/lib/posts";

const SCHEMA = path.resolve(__dirname, "../../../backend/app/schemas/tenant/post.py");
const POLL_MODEL = path.resolve(__dirname, "../../../backend/app/models/tenant/post_poll.py");

const serverConstant = (source: string, name: string) => {
  const match = source.match(new RegExp(`^${name} = ([\\d_]+)$`, "m"));
  expect(match, `${name} not found in the backend`).toBeTruthy();
  return Number(match?.[1].replaceAll("_", ""));
};

describe("post and poll limits", () => {
  it("match the server's own bounds", () => {
    const schema = fs.readFileSync(SCHEMA, "utf-8");
    expect(serverConstant(schema, "MAX_POST_TEXT_CHARS")).toBe(MAX_POST_TEXT_CHARS);
    const source = fs.readFileSync(POLL_MODEL, "utf-8");
    expect(serverConstant(source, "MIN_POLL_OPTIONS")).toBe(MIN_POLL_OPTIONS);
    expect(serverConstant(source, "MAX_POLL_OPTIONS")).toBe(MAX_POLL_OPTIONS);
    expect(serverConstant(source, "MAX_POLL_OPTION_CHARS")).toBe(MAX_POLL_OPTION_CHARS);
  });
});

describe("hasBody", () => {
  // Lexical refuses an editor state whose root has no children, so `{}` — what
  // a headline-only notice stores, and what a notice that is only a headline
  // and a poll stores — is a crash rather than an empty document.
  it("refuses the empty object a bodyless notice stores, and nothing at all", () => {
    expect(hasBody({})).toBe(false);
    expect(hasBody(null)).toBe(false);
    expect(hasBody(undefined)).toBe(false);
    expect(hasBody({ root: { children: [] } })).toBe(true);
  });
});

describe("postBoardTime", () => {
  const created = "2026-01-01T00:00:00.000Z";
  const scheduled = "2026-02-01T00:00:00.000Z";
  const published = "2026-03-01T00:00:00.000Z";

  // A live notice by when it went up, a draft by when it is due (so it
  // previews where it will land), else when it was written.
  it.each([
    [published, scheduled, published],
    [null, scheduled, scheduled],
    [null, null, created],
  ])("dates published %s, scheduled %s by %s", (published_at, scheduled_for, expected) => {
    expect(postBoardTime({ published_at, scheduled_for, created_at: created })).toBe(expected);
  });

  // The timeline groups by this and the server orders by its own board_time().
  // If the two disagree about which instant dates a notice, the rail offers
  // months the feed then puts somewhere else.
  it("uses the same precedence the server's board_time() does", () => {
    const model = fs.readFileSync(
      path.resolve(__dirname, "../../../backend/app/models/tenant/post.py"),
      "utf-8"
    );
    const coalesce = /func\.coalesce\(\s*([^)]+)\)/.exec(model)?.[1] ?? "";
    const columns = coalesce
      .split(",")
      .map((part) => part.trim().replace(/^Post\./, ""))
      .filter(Boolean);

    expect(columns).toEqual(["published_at", "scheduled_for", "created_at"]);
  });
});

describe("postPeriod", () => {
  it("groups a notice by the month it falls in, padded so periods sort as strings", () => {
    // Built from local parts so the expectation holds in any zone the suite
    // runs in — the same reason the helper reads local getters.
    for (const [month, expected] of [
      [2, "2026-03"],
      [0, "2026-01"],
    ] as const) {
      const local = new Date(2026, month, 15, 9, 0).toISOString();
      expect(postPeriod({ published_at: local, created_at: local })).toBe(expected);
    }
  });
});
