/**
 * Who has read a notice.
 *
 * Two lists, and the one that matters is the second: "unread" is the people
 * the notice was *shared with*, which is what makes the number mean anything.
 *
 * The padding case is a layout fact jsdom cannot measure, so it is asserted
 * against the class — which is also the thing that regresses. A worn frame is
 * drawn 128% of the avatar and hangs outside it; a scrolling box clips that,
 * because `overflow-y: auto` computes `overflow-x` to `auto` too.
 */
import fs from "node:fs";
import path from "node:path";

import { screen } from "@testing-library/react";
import { HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";

import { PostReadersDialog } from "./PostReadersDialog";

const person = (id: number, username: string, extra: Record<string, unknown> = {}) => ({
  id,
  username,
  discriminator: 1000 + id,
  display_name: null,
  avatar_url: null,
  profile_decorations: { banner: null, frame: null, frame_tint: [], trophies: [] },
  read_at: null,
  ...extra,
});

const page = () => () => <PostReadersDialog open onOpenChange={() => {}} postId={3} />;

describe("PostReadersDialog", () => {
  it("counts both sides and names who has read it", async () => {
    server.use(
      communityHttp.get("/posts/3/reads", () =>
        HttpResponse.json({
          read: [
            person(1, "reader", { read_at: "2026-03-01T09:00:00Z" }),
            person(4, "ada", { read_at: "2026-03-01T09:00:00Z", display_name: "Ada Lovelace" }),
          ],
          unread: [person(2, "waiting"), person(3, "alsowaiting")],
        })
      )
    );

    renderPage(page());

    expect(await screen.findByRole("tab", { name: /^read 2/i })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /unread 2/i })).toBeInTheDocument();
    expect(screen.getByText(/reader/)).toBeInTheDocument();
    // By the name the community knows them by, where they set one.
    expect(screen.getByText("Ada Lovelace")).toBeInTheDocument();
  });

  it("says so when a notice has reached everybody it went to", async () => {
    server.use(
      communityHttp.get("/posts/3/reads", () =>
        HttpResponse.json({ read: [person(1, "reader")], unread: [] })
      )
    );

    renderPage(page());
    await screen.findByRole("tab", { name: /unread 0/i });
  });

  it("leaves the worn frame room to hang outside the avatar", () => {
    const source = fs.readFileSync(path.resolve(__dirname, "./PostReadersDialog.tsx"), "utf-8");
    const roster = /const ROSTER_LIST = "([^"]+)"/.exec(source)?.[1];

    expect(roster, "the roster list class moved").toBeTruthy();
    // Scrolls, and therefore clips: the padding is what the frame hangs into.
    expect(roster).toContain("overflow-y-auto");
    expect(roster).toMatch(/\bpx-\d/);
  });
});
