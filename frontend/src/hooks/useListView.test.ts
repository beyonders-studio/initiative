import { act, waitFor } from "@testing-library/react";
import { createElement } from "react";
import { describe, expect, it } from "vitest";

import { renderWithProviders } from "@/__tests__/helpers/render";
import { keepViewPreferences } from "@/__tests__/helpers/viewPreferences";

import {
  keptView,
  LIST,
  NO_PART_VIEW,
  partOf,
  sanitizeListView,
  useListView,
  viewKey,
} from "./useListView";

/** What an older release kept on the account for every files list. */
const OLDER = { "file:view-mode": "grid" };

const spec = {
  key: viewKey("initiative", 2, "files"),
  communityId: 4,
  read: (raw: unknown) => raw as { tag_ids: number[] },
  defaults: { filters: { tag_ids: [] }, ...NO_PART_VIEW, sorting: [{ id: "name", desc: false }] },
  carryOver: (
    _items: Readonly<Record<string, unknown>>,
    account: Readonly<Record<string, unknown>>
  ) =>
    account["file:view-mode"] === "grid"
      ? { layout: "grid", parts: { [LIST]: { sorting: [{ id: "updated_at", desc: true }] } } }
      : null,
};

describe("a person's view of a list", () => {
  it("is kept in the community's map, under what names the list", () => {
    expect(spec.key).toBe("view:initiative:2:files");
  });

  it("reads what is kept, else what an older release kept on the account", () => {
    const kept = { layout: "list", parts: { [LIST]: { filters: { tag_ids: [7] } } } };
    expect(keptView({ [spec.key]: kept }, spec, OLDER).view.layout).toBe("list");
    expect(keptView({}, spec, OLDER).view.layout).toBe("grid");
    expect(keptView(OLDER, spec, {}).view.layout).toBeUndefined();
  });

  it("fills what a part keeps with the list's defaults", () => {
    const view = keptView({}, spec, OLDER).view;
    expect(partOf(view, LIST, spec)).toEqual({
      filters: { tag_ids: [] },
      sorting: [{ id: "updated_at", desc: true }],
      grouping: [],
      columns: {},
    });
  });

  it("drops what has the wrong type rather than breaking the list", () => {
    const view = sanitizeListView({
      layout: 3,
      parts: { [LIST]: { sorting: [{ id: 1 }, { id: "name", desc: true }], grouping: "x" } },
    });
    expect(view.layout).toBeNull();
    expect(partOf(view, LIST, spec)).toMatchObject({
      sorting: [{ id: "name", desc: true }],
      grouping: [],
    });
  });

  it("applies a change made before it is in to it, and saves no change that leaves it as it was", async () => {
    const account = keepViewPreferences();
    const kept = keepViewPreferences(4);
    kept[spec.key] = { layout: "list" };
    let view!: ReturnType<typeof useListView<{ tag_ids: number[] }>>;
    const Probe = () => {
      view = useListView(spec);
      return null;
    };
    renderWithProviders(createElement(Probe));

    act(() => view.setMode("week"));
    await waitFor(() => expect(view.mode).toBe("week"));
    expect(view.layout).toBe("list");
    await waitFor(() => expect(kept[spec.key]).toMatchObject({ layout: "list", mode: "week" }));
    expect(account).toEqual({});

    const saved = kept[spec.key];
    act(() => view.rememberLayout("list"));
    // Past the save's debounce: nothing more reached the server.
    await new Promise((resolve) => setTimeout(resolve, 500));
    expect(kept[spec.key]).toBe(saved);
  });
});
