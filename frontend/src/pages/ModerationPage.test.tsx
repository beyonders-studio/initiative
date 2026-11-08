/**
 * The Moderation page.
 *
 * Two things matter and neither is cosmetic: a moderator is shown *how many*
 * people reported something and never who, and every outcome is a close — the
 * page has no state between "open" and "decided".
 */
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  buildInitiativeMember,
  buildPage,
  buildUser,
  buildUserSummary,
} from "@/__tests__/factories";
import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";

const settleMutate = vi.fn();
const restoreMutate = vi.fn();

const state = vi.hoisted(() => ({
  items: [] as Array<Record<string, unknown>>,
  sharing: [] as Array<Record<string, unknown>>,
  sharingFailed: false,
  page: 1,
  hasNext: false,
  log: [] as Array<Record<string, unknown>>,
}));

const report = (overrides: Record<string, unknown> = {}) => ({
  id: 1,
  initiative_id: 7,
  target_type: "comment",
  target_id: 42,
  reason: "harassment",
  reported_at: "2026-09-15T10:00:00Z",
  reporter_count: 1,
  details: [],
  outcome: null,
  note: null,
  decided_by: null,
  decided_at: null,
  target_excerpt: "Say that again and see.",
  // A comment is read on the thing it was said on, so the link opens that.
  target_link: { entity_type: "task", entity_id: 88, tool: "project", tool_id: 12 },
  ...overrides,
});

vi.mock("@/hooks/useModeration", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/hooks/useModeration")>();
  return {
    ...actual,
    useInitiativeSharing: () => ({
      data: { items: state.sharing },
      isLoading: false,
      isError: state.sharingFailed,
    }),
    useModerationReports: (params: { page?: number }) => {
      state.page = params.page ?? 1;
      return {
        data: {
          items: state.items,
          page: state.page,
          page_size: 50,
          total_count: state.items.length,
          has_next: state.hasNext,
          has_prev: state.page > 1,
        },
        isLoading: false,
      };
    },
    useSettleReport: () => ({ mutate: settleMutate, isPending: false }),
    useModerationLog: () => ({
      data: { items: state.log, page: 1, has_next: false, has_prev: false },
      isLoading: false,
      isError: false,
    }),
    useRestoreRemoval: () => ({ mutate: restoreMutate, isPending: false }),
  };
});

/** One row of the moderation log. */
const logged = (overrides: Record<string, unknown> = {}) => ({
  id: 9,
  initiative_id: 7,
  action: "remove",
  target_type: "comment",
  target_id: 42,
  reason: "harassment",
  note: "Second time.",
  snapshot: "Say that again and see.",
  actor: { id: 2, name: "Mo Derator" },
  subject: { id: 5, name: "Sam Poster" },
  report_id: null,
  hold_id: null,
  created_at: "2026-09-16T10:00:00Z",
  restorable: true,
  ...overrides,
});

/** One thing the community has shared, as the Sharing tab reads it. */
const shared = (overrides: Record<string, unknown> = {}) => ({
  resource_type: "project",
  resource_id: 4,
  name: "Spring Play",
  all_initiative_members: false,
  user_grant_count: 1,
  role_grant_count: 0,
  ...overrides,
});

vi.mock("@/hooks/useActiveCommunityId", () => ({ useActiveCommunityId: () => 3 }));

import { ModerationPage } from "./ModerationPage";

// The real route tree, so `<Link>` has a router and the initiative comes from
// the path the way it does in the app.
const render = () =>
  renderPage(ModerationPage, {
    auth: { user: buildUser() },
    initialRoute: "/c/$communityId/i/$initiativeId/moderation",
    routeParams: { communityId: "3", initiativeId: "7" },
  });

/** Render and open the Sharing tab, which is where the second shape lives. */
const openSharing = async () => {
  render();
  const user = userEvent.setup();
  await user.click(await screen.findByRole("tab", { name: "Sharing" }));
};

describe("ModerationPage", () => {
  beforeEach(() => {
    settleMutate.mockClear();
    restoreMutate.mockClear();
    state.log = [];
    state.items = [];
    state.sharing = [];
    state.sharingFailed = false;
    state.page = 1;
    state.hasNext = false;
  });

  it("says so when nothing has been reported", async () => {
    render();
    expect(await screen.findByText("Nothing has been reported.")).toBeInTheDocument();
  });

  it("sends a report to the platform with it left up", async () => {
    state.items = [report()];
    const user = userEvent.setup();
    render();
    await user.click(await screen.findByRole("button", { name: "Send to the platform" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByRole("radio", { name: /Leave it up/ })).toBeChecked();
    await user.click(within(dialog).getByRole("button", { name: "Send" }));
    expect(settleMutate).toHaveBeenCalledWith(
      { reportId: 1, body: { outcome: "escalated", note: null } },
      expect.anything()
    );
  });

  it("hides an illegal report's target by default, asking which law", async () => {
    state.items = [report({ reason: "illegal" })];
    const user = userEvent.setup();
    render();
    await user.click(await screen.findByRole("button", { name: "Send to the platform" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByRole("radio", { name: /Hide it now/ })).toBeChecked();
    expect(within(dialog).getByText(/disappears for everyone, you included/)).toBeInTheDocument();
    const send = within(dialog).getByRole("button", { name: "Hide and send" });
    expect(send).toBeDisabled();
    await user.click(within(dialog).getByRole("combobox", { name: "Which law" }));
    await user.click(await screen.findByRole("option", { name: "Privacy" }));
    await user.click(send);
    expect(settleMutate).toHaveBeenCalledWith(
      {
        reportId: 1,
        body: {
          outcome: "held",
          note: null,
          hold: { reason: "illegal_content", legal_basis: "privacy", note: null },
        },
      },
      expect.anything()
    );
  });

  it("shows what the reporters sent, blurred until a moderator asks to look", async () => {
    state.items = [
      report({
        evidence: [
          {
            id: 4,
            display_name: "screenshot.png",
            content_type: "image/png",
            size_bytes: 1024,
            created_at: new Date().toISOString(),
          },
        ],
      }),
    ];
    render();
    expect(await screen.findByText("What they sent")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Show screenshot.png" })).toBeInTheDocument();
    expect(screen.queryByRole("img", { name: "screenshot.png" })).toBeNull();
  });

  it("shows what was reported and how many reported it, and never who", async () => {
    state.items = [report({ reporter_count: 3, details: ["Abusive.", "Not on."] })];
    render();

    expect(await screen.findByText(/Reported by 3 people/)).toBeInTheDocument();
    expect(screen.getByText("Abusive.")).toBeInTheDocument();
    expect(screen.getByText("Not on.")).toBeInTheDocument();
    // Nothing in the payload names a reporter, and nothing on the page does.
    expect(screen.queryByText(/reporter_id/i)).not.toBeInTheDocument();
    // The card shows the thing itself, and sends a moderator to it in context
    // rather than pretending this page is where it is read.
    const card = screen.getByRole("region", { name: "A comment" });
    expect(within(card).getByText("Say that again and see.")).toBeInTheDocument();
    expect(
      screen.getByText("Open the reported item to look at it in context, then decide here.")
    ).toBeInTheDocument();
  });

  it("offers every outcome, and each one closes the report", async () => {
    state.items = [report()];
    render();
    const user = userEvent.setup();

    const card = await screen.findByRole("region", { name: "A comment" });
    for (const label of ["Dismiss", "Remove…", "Warn…", "Send to the platform"]) {
      expect(within(card).getByRole("button", { name: label })).toBeInTheDocument();
    }

    await user.click(within(card).getByRole("button", { name: "Dismiss" }));
    expect(settleMutate).toHaveBeenCalledWith({
      reportId: 1,
      body: { outcome: "dismissed", note: null },
    });
  });

  it("carries the moderator's note with the decision", async () => {
    state.items = [report()];
    render();
    const user = userEvent.setup();

    const card = await screen.findByRole("region", { name: "A comment" });
    await user.type(within(card).getByRole("textbox"), "Checked it.");
    await user.click(within(card).getByRole("button", { name: "Dismiss" }));

    expect(settleMutate).toHaveBeenCalledWith({
      reportId: 1,
      body: { outcome: "dismissed", note: "Checked it." },
    });
  });

  it("takes it down for the reason it was reported for, unless the moderator says otherwise", async () => {
    state.items = [report()];
    render();
    const user = userEvent.setup();

    const card = await screen.findByRole("region", { name: "A comment" });
    await user.type(within(card).getByRole("textbox"), "Seen it before.");
    await user.click(within(card).getByRole("button", { name: "Remove…" }));

    const dialog = await screen.findByRole("dialog", { name: "Take it down" });
    // Starts from the report: its reason, and the note typed on the card.
    expect(within(dialog).getByRole("combobox")).toHaveTextContent("Harassment");
    expect(within(dialog).getByRole("textbox")).toHaveValue("Seen it before.");
    await user.click(within(dialog).getByRole("button", { name: "Take it down" }));

    expect(settleMutate).toHaveBeenCalledWith(
      {
        reportId: 1,
        body: { outcome: "content_removed", note: "Seen it before.", removal_reason: null },
      },
      expect.anything()
    );
  });

  it("warns whoever wrote it in the moderator's words, and needs some", async () => {
    state.items = [report()];
    render();
    const user = userEvent.setup();

    const card = await screen.findByRole("region", { name: "A comment" });
    await user.click(within(card).getByRole("button", { name: "Warn…" }));
    const dialog = await screen.findByRole("dialog", { name: "Warn whoever wrote this" });
    const send = within(dialog).getByRole("button", { name: "Send warning" });
    expect(send).toBeDisabled();

    await user.type(within(dialog).getByRole("textbox"), "Keep it civil.");
    await user.click(send);
    expect(settleMutate).toHaveBeenCalledWith(
      {
        reportId: 1,
        body: { outcome: "member_warned", note: null, message: "Keep it civil." },
      },
      expect.anything()
    );
  });

  it("says when the platform was told as well, and which law", async () => {
    state.items = [
      report({
        reason: "illegal",
        legal_basis: "privacy",
        platform_notified_at: "2026-09-15T10:00:01Z",
      }),
    ];
    render();

    const card = await screen.findByRole("region", { name: "A comment" });
    expect(within(card).getByText("Platform notified")).toBeInTheDocument();
    expect(within(card).getByText(/Illegal \(Privacy\)/)).toBeInTheDocument();
    expect(within(card).getByText(/hide it and send it to the platform/)).toBeInTheDocument();
  });

  it("reads the log back, with the words a removal took down, and puts it back", async () => {
    state.log = [
      logged(),
      logged({ id: 8, action: "warn", reason: null, snapshot: null, restorable: false }),
    ];
    render();
    const user = userEvent.setup();
    await user.click(await screen.findByRole("tab", { name: "Log" }));

    expect(await screen.findByText("Say that again and see.")).toBeInTheDocument();
    expect(screen.getByText("Removed")).toBeInTheDocument();
    expect(screen.getByText("Warned")).toBeInTheDocument();
    // Only a removal still standing can be put back.
    const restore = screen.getAllByRole("button", { name: "Put back" });
    expect(restore).toHaveLength(1);
    await user.click(restore[0]);
    expect(restoreMutate).toHaveBeenCalledWith(9);
  });

  it("a settled report shows what was decided and offers no outcomes", async () => {
    state.items = [
      report({
        outcome: "content_removed",
        note: "Removed it.",
        decided_at: "2026-09-15T12:00:00Z",
      }),
    ];
    render();

    const card = await screen.findByRole("region", { name: "A comment" });
    expect(within(card).getByText("Content removed")).toBeInTheDocument();
    expect(within(card).getByText("Removed it.")).toBeInTheDocument();
    expect(within(card).queryByRole("button", { name: "Dismiss" })).not.toBeInTheDocument();
  });

  // A comment has no page of its own; it is read where it was written. The
  // project is only what the task is *shared* as part of, and landing there
  // leaves a moderator hunting for the comment they were sent to read.
  it.each([
    [
      "a comment, to the task it was said on rather than to its project",
      {},
      "A comment",
      "/projects/12/tasks/88",
    ],
    [
      "a comment on a file, to that file",
      { target_link: { entity_type: "file", entity_id: 5, tool: "file", tool_id: 5 } },
      "A comment",
      "/files/5",
    ],
    [
      "a reported task, to the task itself",
      { target_type: "task", target_id: 88 },
      "A task",
      "/projects/12/tasks/88",
    ],
  ])("links %s", async (_label, overrides, name, href) => {
    state.items = [report(overrides)];
    render();

    const link = await screen.findByRole("link", { name });
    expect(link).toHaveAttribute("href", expect.stringContaining(href));
  });

  it("says so, and links nowhere, once the reported thing is gone", async () => {
    // Deleted since — or never this reader's to see. One answer for both, and
    // a link would go nowhere either way.
    state.items = [report({ target_excerpt: null, target_link: null })];
    render();

    expect(
      await screen.findByText("This isn't here any more, or isn't yours to see.")
    ).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "A comment" })).not.toBeInTheDocument();
  });

  it("offers a further page while there is one", async () => {
    state.items = Array.from({ length: 50 }, (_, i) => report({ id: i + 1 }));
    state.hasNext = true;
    render();
    const user = userEvent.setup();

    const next = await screen.findByRole("button", { name: "Next" });
    expect(screen.getByRole("button", { name: "Previous" })).toBeDisabled();

    await user.click(next);
    expect(state.page).toBe(2);
  });

  it("offers no paging when one page holds everything", async () => {
    state.items = [report()];
    render();
    await screen.findByRole("region", { name: "A comment" });
    expect(screen.queryByRole("button", { name: "Next" })).not.toBeInTheDocument();
  });

  it("reads the initiative's roster a page at a time, each member with their role", async () => {
    server.use(
      communityHttp.get("/initiatives/:id/members", ({ request }) => {
        const page = Number(new URL(request.url).searchParams.get("page"));
        const member =
          page === 2
            ? buildInitiativeMember({
                user: buildUserSummary({ display_name: "Bea Second" }),
                role_display_name: "Member",
              })
            : buildInitiativeMember({
                user: buildUserSummary({ display_name: "Ada First" }),
                role_display_name: "Moderator",
                override_share_restrictions: true,
              });
        return HttpResponse.json(
          buildPage([member], { page, has_next: page === 1, has_prev: page === 2 })
        );
      })
    );
    render();
    const user = userEvent.setup();

    await user.click(await screen.findByRole("tab", { name: "Members" }));
    expect(await screen.findByText("Ada First")).toBeInTheDocument();
    expect(screen.getByText("Full access")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Next" }));

    expect(await screen.findByText("Bea Second")).toBeInTheDocument();
    expect(screen.queryByText("Ada First")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Previous" })).toBeEnabled();
  });

  it("gathers what a moderator acts with beside what they act on", async () => {
    render();
    for (const area of ["Reports", "Members", "Sharing", "Log"]) {
      expect(await screen.findByRole("tab", { name: area })).toBeInTheDocument();
    }
  });

  it("shows how widely each thing is reached, and links to it", async () => {
    state.sharing = [
      shared({ all_initiative_members: true, user_grant_count: 2, role_grant_count: 1 }),
    ];
    await openSharing();

    expect(await screen.findByText("Everyone here")).toBeInTheDocument();
    expect(screen.getByText(/2 people/)).toBeInTheDocument();
    expect(screen.getByText(/1 role(?!s)/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Spring Play" })).toHaveAttribute(
      "href",
      expect.stringContaining("/go/project/4")
    );
  });

  it("offers no way to change sharing from here", async () => {
    state.sharing = [shared()];
    await openSharing();
    await screen.findByText("Spring Play");
    // Changing it goes through the resource's own control, which is the one
    // editor for it.
    expect(screen.queryByRole("button", { name: /share|remove|add/i })).toBeNull();
  });

  it("counts one person as a person, not as people", async () => {
    state.sharing = [shared({ role_grant_count: 1 })];
    await openSharing();
    await screen.findByText("Spring Play");
    expect(screen.queryByText(/1 people/)).not.toBeInTheDocument();
    expect(screen.queryByText(/1 roles/)).not.toBeInTheDocument();
  });

  it("a failed read is not a community that has shared nothing", async () => {
    // "Nothing is shared" reads as a finding, so it has to be one somebody
    // actually got an answer to.
    state.sharingFailed = true;
    await openSharing();

    expect(await screen.findByText("Could not load that. Try again.")).toBeInTheDocument();
    expect(
      screen.queryByText("Nothing here has been shared with anybody in particular.")
    ).not.toBeInTheDocument();
  });
});
