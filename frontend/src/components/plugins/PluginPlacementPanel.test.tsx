/**
 * What reaches the server when an admin picks initiatives.
 *
 * Each save replaces the whole selection, which makes two things matter that a
 * single-field form never has to think about.
 *
 * **Order.** Ticking two boxes quickly starts two saves. If they were sent
 * concurrently the slower one could land last and store the older selection, so
 * they are chained and the server sees them in the order they were made.
 *
 * **What is still there.** An initiative deleted after it was chosen leaves an
 * id behind that nothing on screen shows. Resubmitting it would be refused, and
 * the admin would have no way to see why — so the selection sent is the one
 * being displayed.
 */

import { screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderPage } from "@/__tests__/helpers/render";
import type { CommunityPluginDetail } from "@/api/generated/initiativeAPI.schemas";

import { PluginPlacementPanel } from "./PluginPlacementPanel";

/** Every payload handed to the update mutation, in the order it was sent. */
const sent: unknown[] = [];
/** Resolves the in-flight save, so a test can hold one open. */
let release: Array<() => void> = [];
let holdSaves = false;

const mutateAsync = vi.fn((body: unknown) => {
  sent.push(body);
  if (!holdSaves) return Promise.resolve({});
  return new Promise<object>((resolve) => release.push(() => resolve({})));
});

vi.mock("@/hooks/useCommunityPlugins", () => ({
  useUpdateCommunityPlugin: () => ({ mutateAsync }),
}));

let roster = [
  { id: 1, name: "Platform" },
  { id: 2, name: "Marketing" },
];

vi.mock("@/hooks/useInitiatives", () => ({
  useCommunityInitiatives: () => ({ data: roster, isLoading: false }),
  // The admin's own memberships: narrower than the community on purpose. The
  // panel must never read this list — see "every initiative in the community".
  useInitiatives: () => ({ data: roster.slice(0, 1), isLoading: false }),
}));

/** A page the plug-in shows inside initiatives. */
const initiativePage = { id: "board", path: "/board", scopes: ["initiative"] };

/** A field the plug-in adds to tasks. */
const taskField = { key: "estimate", kind: "text", on: ["task"] };

/**
 * An install placed in these initiatives. It shows a page inside initiatives
 * unless ``page`` is false, and the ``fields`` given.
 */
const plugin = (placed: number[], page = true, fields: object[] = []) =>
  ({
    id: 7,
    name: "Automations",
    definition: { pages: page ? [initiativePage] : [], fields },
    requested_scopes: ["projects:read"],
    placed_initiative_ids: placed,
  }) as unknown as CommunityPluginDetail;

beforeEach(() => {
  sent.length = 0;
  release = [];
  holdSaves = false;
  mutateAsync.mockClear();
  roster = [
    { id: 1, name: "Platform" },
    { id: 2, name: "Marketing" },
  ];
});

const tick = async (name: string) => (await screen.findByLabelText(name)).click();

describe("PluginPlacementPanel", () => {
  it("sends the selection the admin built, one tick at a time", async () => {
    renderPage(() => <PluginPlacementPanel plugin={plugin([])} />);

    await tick("Platform");
    await waitFor(() => expect(sent).toEqual([{ placed_initiative_ids: [1] }]));

    await tick("Marketing");
    await waitFor(() =>
      expect(sent).toEqual([{ placed_initiative_ids: [1] }, { placed_initiative_ids: [1, 2] }])
    );
  });

  it("does not start a second save while the first is in flight", async () => {
    // Both boxes are ticked before either save answers. Concurrent requests
    // could be stored in either order; chained ones cannot.
    holdSaves = true;
    renderPage(() => <PluginPlacementPanel plugin={plugin([])} />);

    await tick("Platform");
    await waitFor(() => expect(mutateAsync).toHaveBeenCalledTimes(1));
    await tick("Marketing");

    // Still one: the second is queued behind the first rather than racing it.
    expect(mutateAsync).toHaveBeenCalledTimes(1);

    release[0]?.();
    await waitFor(() => expect(mutateAsync).toHaveBeenCalledTimes(2));
    expect(sent[1]).toEqual({ placed_initiative_ids: [1, 2] });
  });

  it("drops an id whose initiative is gone rather than resubmitting it", async () => {
    // Initiative 9 was chosen once and has since been deleted: it is in the
    // stored placement and on no row of the roster.
    renderPage(() => <PluginPlacementPanel plugin={plugin([1, 9])} />);

    await tick("Marketing");
    await waitFor(() => expect(sent).toEqual([{ placed_initiative_ids: [1, 2] }]));
  });

  it("leaves the next edit building on what the server kept", async () => {
    // The first save fails while a second is already queued behind it. The
    // second succeeds, so the server holds that selection — and the panel has
    // to agree, or the following edit is computed from a state nobody stored.
    let rejectFirst: (reason: unknown) => void = () => {};
    mutateAsync.mockImplementationOnce((body: unknown) => {
      sent.push(body);
      return new Promise<object>((_resolve, reject) => {
        rejectFirst = reject;
      });
    });
    renderPage(() => <PluginPlacementPanel plugin={plugin([])} />);

    await tick("Platform");
    await waitFor(() => expect(mutateAsync).toHaveBeenCalledTimes(1));
    await tick("Marketing");

    rejectFirst(new Error("refused"));
    await waitFor(() => expect(sent[1]).toEqual({ placed_initiative_ids: [1, 2] }));

    // Untick the first one. Built on [1, 2] — what the server took — rather
    // than on the empty selection the failed save would have rolled back to.
    await tick("Platform");
    await waitFor(() => expect(sent[2]).toEqual({ placed_initiative_ids: [2] }));
  });

  it("places the plug-in in every current initiative in one choice", async () => {
    renderPage(() => <PluginPlacementPanel plugin={plugin([1])} />);

    (await screen.findByLabelText("Every current initiative")).click();
    await waitFor(() => expect(sent).toEqual([{ placed_initiative_ids: [1, 2] }]));
  });

  it("reads a plug-in placed in every initiative as every current one", async () => {
    renderPage(() => <PluginPlacementPanel plugin={plugin([1, 2])} />);

    expect(await screen.findByLabelText("Every current initiative")).toBeChecked();
    expect(screen.queryByLabelText("Platform")).toBeNull();
  });

  describe("every initiative in the community", () => {
    // The admin is a member of Platform only. Placement bounds where the
    // plug-in's automations fire, so an initiative they never joined still
    // counts — reading their memberships instead left automations silent there
    // while the panel claimed "every current initiative".
    it("places it in initiatives the admin is not a member of", async () => {
      renderPage(() => <PluginPlacementPanel plugin={plugin([])} />);

      (await screen.findByLabelText("Every current initiative")).click();
      await waitFor(() => expect(sent).toEqual([{ placed_initiative_ids: [1, 2] }]));
    });

    it("does not read as every initiative while one the admin never joined is missing", async () => {
      renderPage(() => <PluginPlacementPanel plugin={plugin([1])} />);

      expect(await screen.findByLabelText("Only the initiatives I choose")).toBeChecked();
    });
  });

  it("choosing to pick shows the current placements and saves nothing", async () => {
    renderPage(() => <PluginPlacementPanel plugin={plugin([1, 2])} />);

    (await screen.findByLabelText("Only the initiatives I choose")).click();
    expect(await screen.findByLabelText("Platform")).toBeChecked();
    expect(screen.getByLabelText("Marketing")).toBeChecked();
    expect(sent).toEqual([]);
  });

  describe("where its roles are set", () => {
    const rolesLink = (name: string) => screen.queryByRole("link", { name: `Roles in ${name}` });

    it("links each initiative it is placed in to that initiative's Roles screen", async () => {
      renderPage(() => <PluginPlacementPanel plugin={plugin([1])} />);

      await screen.findByLabelText("Platform");
      expect(rolesLink("Platform")?.getAttribute("href")).toMatch(/\/i\/1\/settings\/roles$/);
      // Marketing is not placed, so its roles have nothing of the plug-in.
      expect(rolesLink("Marketing")).toBeNull();
      expect(screen.getByText(/Each initiative's roles say who uses it there/)).toBeTruthy();
    });

    it("links every placement when placed everywhere", async () => {
      renderPage(() => <PluginPlacementPanel plugin={plugin([1, 2])} />);

      expect(await screen.findByRole("link", { name: "Roles in Platform" })).toBeTruthy();
      expect(rolesLink("Marketing")).toBeTruthy();
    });

    it("links no roles for a plug-in with no page inside initiatives", async () => {
      renderPage(() => <PluginPlacementPanel plugin={plugin([1, 2], false)} />);

      expect(
        await screen.findByText(
          "This plug-in reads and changes things only in the initiatives you choose."
        )
      ).toBeTruthy();
      expect(rolesLink("Platform")).toBeNull();
    });

    it("links roles for a plug-in with a field on items and no page", async () => {
      // The roles say who is drawn the field on an item there, as they say
      // who opens a page.
      renderPage(() => <PluginPlacementPanel plugin={plugin([1], false, [taskField])} />);

      await screen.findByLabelText("Platform");
      expect(rolesLink("Platform")).toBeTruthy();
    });
  });
});
