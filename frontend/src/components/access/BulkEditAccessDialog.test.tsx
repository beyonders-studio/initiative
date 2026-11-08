import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";

import { buildPage, buildUserSummary, ownerCan } from "@/__tests__/factories";
import { buildFileSummary } from "@/__tests__/factories/file.factory";
import { buildInitiative } from "@/__tests__/factories/initiative.factory";
import { buildUser } from "@/__tests__/factories/user.factory";
import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderWithProviders } from "@/__tests__/helpers/render";
import type {
  FileSummary,
  InitiativeRoleRead,
  ResourceGrantSchema,
} from "@/api/generated/initiativeAPI.schemas";
import { Tool } from "@/api/generated/initiativeAPI.schemas";

import { BulkEditAccessDialog } from "./BulkEditAccessDialog";

// ── Fixtures ─────────────────────────────────────────────────────────────────
// One initiative (id 50) with a single non-current member (Bob, id 101) and one
// editor role (id 200). The current user is id 1, so Bob is selectable and Bob
// won't be filtered out as "self".

const INITIATIVE_ID = 50;
const BOB_ID = 101;
const EDITOR_ROLE_ID = 200;

const bob = buildUserSummary({ id: BOB_ID, display_name: "Bob Builder" });

const initiative = buildInitiative({ id: INITIATIVE_ID, name: "Init" });

const roles: InitiativeRoleRead[] = [
  {
    id: EDITOR_ROLE_ID,
    name: "editor",
    display_name: "Editor",
    is_builtin: false,
    is_manager: false,
    override_share_restrictions: false,
    position: 0,
    permissions: {},
    member_count: 1,
  },
];

/**
 * A file currently shared with *all initiative members* (Viewer). This is
 * the state that triggered the defect: a bulk per-user/per-role grant must drop
 * the all-members grant so ShareControl's two-mode model can still render it.
 */
function allMembersDoc(extraGrants: ResourceGrantSchema[] = []): FileSummary {
  return buildFileSummary({
    id: 10,
    initiative_id: INITIATIVE_ID,
    can: ownerCan(),
    grants: [
      { all_initiative_members: true, level: "read" },
      { user_id: 999, level: "owner" },
      ...extraGrants,
    ],
  });
}

/**
 * A file that is NOT shared with all initiative members — only an owner and
 * one individual grant. Removing all-members access on this doc is a no-op.
 */
function restrictedDoc(id: number): FileSummary {
  return buildFileSummary({
    id,
    initiative_id: INITIATIVE_ID,
    can: ownerCan(),
    grants: [
      { user_id: 999, level: "owner" },
      { user_id: BOB_ID, level: "read" },
    ],
  });
}

/** The query each member search was asked with. */
const memberSearches: URLSearchParams[] = [];

/**
 * Capture the grant lists crossing the network boundary. The dialog persists via
 * the bulk endpoint (one request, many items); we flatten to one entry per item's
 * grant list so `captured.length` still means "how many resources were written".
 */
function captureGrantPuts() {
  const captured: ResourceGrantSchema[][] = [];
  memberSearches.length = 0;
  server.use(
    communityHttp.get("/initiatives/", () => HttpResponse.json([initiative])),
    communityHttp.get("/initiatives/:initiativeId/roles", () => HttpResponse.json(roles)),
    // The initiative's member search: what was typed, or the ids asked for.
    communityHttp.get("/initiatives/:initiativeId/members/search", ({ request }) => {
      memberSearches.push(new URL(request.url).searchParams);
      return HttpResponse.json(buildPage([bob]));
    }),
    communityHttp.put("/resource-grants/bulk", async ({ request }) => {
      const body = (await request.json()) as {
        items: { resource_type: string; resource_id: number; grants: ResourceGrantSchema[] }[];
      };
      for (const item of body.items) captured.push(item.grants);
      return HttpResponse.json({
        results: body.items.map((i) => ({
          resource_type: i.resource_type,
          resource_id: i.resource_id,
          status: "ok",
        })),
      });
    })
  );
  return captured;
}

function renderDialog(files: FileSummary[]) {
  return renderWithProviders(
    <BulkEditAccessDialog
      open
      onOpenChange={vi.fn()}
      onSuccess={vi.fn()}
      items={files}
      resourceType={Tool.file}
      invalidate={vi.fn()}
    />,
    { auth: { user: buildUser({ id: 1 }) } }
  );
}

describe("BulkEditAccessDialog grant rebuild", () => {
  it("user grant drops the all-members grant (switches the doc to restricted mode)", async () => {
    const user = userEvent.setup();
    const captured = captureGrantPuts();

    renderDialog([allMembersDoc()]);

    // People is the default tab.
    // Open the picker via its placeholder text (its accessible *name* is the
    // "People" label, which collides with the tab — match the visible text).
    await user.click(screen.getByText("Select people…"));
    await user.click(await screen.findByText("Bob Builder"));
    await user.click(screen.getByRole("button", { name: /Grant 1 person/i }));

    await waitFor(() => expect(captured).toHaveLength(1));
    const payload = captured[0];
    // The all-members grant must be gone — otherwise ShareControl gets a mixed
    // list it can't display and silently discards on the next save.
    expect(payload.some((g) => g.all_initiative_members)).toBe(false);
    // The targeted user is granted at the chosen level.
    expect(payload).toContainEqual({ user_id: BOB_ID, level: "read" });
    // Owner grants are dropped from the payload (the server re-adds the owner).
    expect(payload.some((g) => g.level === "owner")).toBe(false);
  });

  it("role grant drops the all-members grant (switches the doc to restricted mode)", async () => {
    const user = userEvent.setup();
    const captured = captureGrantPuts();

    renderDialog([allMembersDoc()]);

    await user.click(screen.getByRole("tab", { name: "Roles" }));
    // Open the picker via its placeholder text.
    await user.click(screen.getByText("Select roles…"));
    await user.click(await screen.findByText("Editor"));
    await user.click(screen.getByRole("button", { name: /Grant 1 role/i }));

    await waitFor(() => expect(captured).toHaveLength(1));
    const payload = captured[0];
    expect(payload.some((g) => g.all_initiative_members)).toBe(false);
    expect(payload).toContainEqual({ role_id: EDITOR_ROLE_ID, level: "read" });
  });

  it("user revoke keeps the all-members grant, dropping only the targeted user", async () => {
    const user = userEvent.setup();
    const captured = captureGrantPuts();

    // Doc shared with all members AND with Bob individually.
    renderDialog([allMembersDoc([{ user_id: BOB_ID, level: "read" }])]);

    // People is the default tab.
    // Switch the action mode from Grant to Revoke (the mode select is labelled
    // "Action"; click the trigger, not the pointer-events:none value span).
    await user.click(screen.getByLabelText("Action"));
    await user.click(await screen.findByRole("option", { name: "Revoke access" }));
    await user.click(screen.getByText("Select people to revoke…"));
    // Names resolve by looking the grantees up among the initiative's members
    // (not from the resource row), so Bob shows by name even in revoke mode.
    await user.click(await screen.findByText("Bob Builder"));
    await user.click(screen.getByRole("button", { name: /Revoke 1 person/i }));
    expect(memberSearches.some((params) => params.getAll("user_id").includes(String(BOB_ID)))).toBe(
      true
    );

    await waitFor(() => expect(captured).toHaveLength(1));
    const payload = captured[0];
    // Revoking one grantee must NOT silently strip everyone's all-members share.
    expect(payload.some((g) => g.all_initiative_members)).toBe(true);
    expect(payload.some((g) => g.user_id === BOB_ID)).toBe(false);
  });

  it("all-members remove only writes docs that actually have an all-members grant", async () => {
    const user = userEvent.setup();
    const captured = captureGrantPuts();

    // One doc shared with all members (id 10), one restricted-only (id 11).
    renderDialog([allMembersDoc(), restrictedDoc(11)]);

    await user.click(screen.getByRole("tab", { name: "All members" }));
    await user.click(screen.getByLabelText("Action"));
    await user.click(await screen.findByRole("option", { name: "Remove all-members access" }));
    await user.click(screen.getByRole("button", { name: "Remove all-members access" }));

    // Exactly one PUT: the restricted-only doc is skipped (no-op), not re-saved
    // with an unchanged grant list.
    await waitFor(() => expect(captured).toHaveLength(1));
    expect(captured[0].some((g) => g.all_initiative_members)).toBe(false);
  });

  it("revoke skips items the person isn't granted on (accurate count)", async () => {
    const user = userEvent.setup();
    const captured = captureGrantPuts();

    // Doc 10 grants Bob; doc 11 does not (owner only).
    const docWithBob = allMembersDoc([{ user_id: BOB_ID, level: "read" }]);
    const docWithoutBob = buildFileSummary({
      id: 11,
      initiative_id: INITIATIVE_ID,
      can: ownerCan(),
      grants: [{ user_id: 999, level: "owner" }],
    });
    renderDialog([docWithBob, docWithoutBob]);

    await user.click(screen.getByLabelText("Action"));
    await user.click(await screen.findByRole("option", { name: "Revoke access" }));
    await user.click(screen.getByText("Select people to revoke…"));
    await user.click(await screen.findByText("Bob Builder"));
    await user.click(screen.getByRole("button", { name: /Revoke 1 person/i }));

    // Only the doc that actually granted Bob is written — the other is skipped.
    await waitFor(() => expect(captured).toHaveLength(1));
    expect(captured[0].some((g) => g.user_id === BOB_ID)).toBe(false);
  });

  it("names the resource type in copy, not a hardcoded 'files'", async () => {
    captureGrantPuts();

    renderWithProviders(
      <BulkEditAccessDialog
        open
        onOpenChange={vi.fn()}
        onSuccess={vi.fn()}
        items={[{ id: 1, initiative_id: INITIATIVE_ID, grants: [], can: ownerCan() }]}
        resourceType={Tool.counter_group}
        invalidate={vi.fn()}
      />,
      { auth: { user: buildUser({ id: 1 }) } }
    );

    // Default People tab, grant mode → the description uses the counter group noun.
    expect(await screen.findByText("Grant people access on 1 counter group.")).toBeInTheDocument();
  });

  it("all-members remove makes no request when nothing is shared with all members", async () => {
    const user = userEvent.setup();
    const captured = captureGrantPuts();
    const onSuccess = vi.fn();

    renderWithProviders(
      <BulkEditAccessDialog
        open
        onOpenChange={vi.fn()}
        onSuccess={onSuccess}
        items={[restrictedDoc(11)]}
        resourceType={Tool.file}
        invalidate={vi.fn()}
      />,
      { auth: { user: buildUser({ id: 1 }) } }
    );

    await user.click(screen.getByRole("tab", { name: "All members" }));
    await user.click(screen.getByLabelText("Action"));
    await user.click(await screen.findByRole("option", { name: "Remove all-members access" }));
    await user.click(screen.getByRole("button", { name: "Remove all-members access" }));

    // The handler still settles (dialog closes) but issues zero writes.
    await waitFor(() => expect(onSuccess).toHaveBeenCalled());
    expect(captured).toHaveLength(0);
  });
});
