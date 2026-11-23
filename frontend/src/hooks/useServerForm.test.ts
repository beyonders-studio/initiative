import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { useServerForm } from "./useServerForm";

interface Entity {
  id: number;
  name: string;
  description: string | null;
}

const derive = (entity: Entity | undefined) => ({
  name: entity?.name ?? "",
  description: entity?.description ?? "",
});

const entity = (overrides: Partial<Entity> = {}): Entity => ({
  id: 1,
  name: "Roadmap",
  description: null,
  ...overrides,
});

/** The hook as a page uses it: one entity, identified by its id. */
const renderForm = (initial: Entity | undefined) =>
  renderHook(({ loaded }) => useServerForm(loaded, derive, loaded?.id), {
    initialProps: { loaded: initial },
  });

describe("useServerForm", () => {
  it("fills in from the entity once it lands", () => {
    const { result, rerender } = renderForm(undefined);
    expect(result.current.values).toEqual({ name: "", description: "" });

    rerender({ loaded: entity() });

    expect(result.current.values).toEqual({ name: "Roadmap", description: "" });
    expect(result.current.edited).toBe(false);
  });

  it("keeps unsaved work when a later answer would overwrite it, until it is reset", () => {
    const { result, rerender } = renderForm(entity());

    act(() => result.current.set({ name: "Half-written" }));
    rerender({ loaded: entity({ name: "Renamed by somebody else" }) });

    expect(result.current.values.name).toBe("Half-written");
    expect(result.current.edited).toBe(true);

    // A refused name goes back; the description typed beside it, and a name
    // typed again since the save was sent, are not what was refused.
    act(() => result.current.set({ description: "Typed meanwhile" }));
    act(() => result.current.reset({ name: "Half-written" }));

    expect(result.current.values).toEqual({
      name: "Renamed by somebody else",
      description: "Typed meanwhile",
    });
    expect(result.current.edited).toBe(true);

    act(() => result.current.set({ description: "Typed again" }));
    act(() => result.current.reset({ description: "Typed meanwhile" }));
    expect(result.current.values.description).toBe("Typed again");

    act(() => result.current.reset({ description: "Typed again" }));
    expect(result.current.edited).toBe(false);
  });

  it("leaves the fields alone when the same answer arrives again", () => {
    const loaded = entity();
    const { result, rerender } = renderForm(loaded);

    act(() => result.current.set({ name: "Half-written" }));
    rerender({ loaded });

    expect(result.current.values.name).toBe("Half-written");
  });

  it("does not mistake a rebuilt list of ids for a change", () => {
    const { result, rerender } = renderHook(
      ({ ids }) => useServerForm({ ids }, (source) => ({ ids: source?.ids ?? [] }), 1),
      { initialProps: { ids: [1, 2, 3] } }
    );

    act(() => result.current.set({ ids: [1, 2] }));
    rerender({ ids: [1, 2, 3] });

    expect(result.current.values.ids).toEqual([1, 2]);
  });

  it("follows a list that actually changed", () => {
    const { result, rerender } = renderHook(
      ({ ids }) => useServerForm({ ids }, (source) => ({ ids: source?.ids ?? [] }), 1),
      { initialProps: { ids: [1, 2, 3] } }
    );

    rerender({ ids: [1, 2, 3, 4] });

    expect(result.current.values.ids).toEqual([1, 2, 3, 4]);
  });

  it("edits one field without disturbing the others", () => {
    const { result } = renderForm(entity({ description: "A description" }));

    act(() => result.current.set({ name: "Renamed" }));

    expect(result.current.values).toEqual({ name: "Renamed", description: "A description" });
  });

  describe("moving to something else", () => {
    it("starts afresh, unsaved work and all", () => {
      // A routed page that stays mounted while its id changes: what was typed
      // for one thing must never be shown — or saved — under another.
      const { result, rerender } = renderForm(entity({ id: 1 }));

      act(() => result.current.set({ name: "Half-written" }));
      rerender({ loaded: entity({ id: 2, name: "A different thing" }) });

      expect(result.current.values.name).toBe("A different thing");
      expect(result.current.edited).toBe(false);
    });

    it("starts afresh when a dialog reopens on the same row", () => {
      const { result, rerender } = renderHook(
        ({ open }) => useServerForm(entity(), derive, [open, 1]),
        { initialProps: { open: true } }
      );

      act(() => result.current.set({ name: "Abandoned half-way" }));
      rerender({ open: false });
      rerender({ open: true });

      expect(result.current.values.name).toBe("Roadmap");
    });
  });

  describe("settling", () => {
    it("goes back to following the server once the work is saved", () => {
      const { result, rerender } = renderForm(entity());

      act(() => result.current.set({ name: "Half-written" }));
      act(() => result.current.settle({ name: "Half-written", description: "" }));
      expect(result.current.edited).toBe(false);
      // Still showing what was typed — settling does not undo it.
      expect(result.current.values.name).toBe("Half-written");

      rerender({ loaded: entity({ name: "Half-written", description: "and described" }) });

      expect(result.current.values.description).toBe("and described");
    });

    it("settles a form whose values are deeper than fields, once it holds what was sent", () => {
      // The rows come back as new objects every time, so field-by-field
      // identity would never match and the form would never settle again —
      // and never adopt another server answer for the rest of its life.
      const deep = (rows: { id: number }[]) => ({ rows });
      const { result } = renderHook(() =>
        useServerForm(
          { rows: [{ id: 1 }] },
          (source) => deep(source?.rows ?? []),
          1,
          (a, b) => JSON.stringify(a) === JSON.stringify(b)
        )
      );

      act(() => result.current.set({ rows: [{ id: 1 }, { id: 2 }] }));
      act(() => result.current.set({ rows: [{ id: 1 }, { id: 2 }, { id: 3 }] }));
      // The reply for an older save does not cover what moved on since.
      act(() => result.current.settle(deep([{ id: 1 }, { id: 2 }])));
      expect(result.current.edited).toBe(true);

      act(() => result.current.settle(deep([{ id: 1 }, { id: 2 }, { id: 3 }])));

      expect(result.current.edited).toBe(false);
    });
  });
});
