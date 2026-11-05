/**
 * Which link writes a save actually makes.
 *
 * Links are written a kind at a time, and which kinds get written is the whole
 * of what this decides: too few and a removal never lands, too many and every
 * save rewrites sets nobody touched.
 */
import { describe, expect, it } from "vitest";

import { SearchEntityType } from "@/api/generated/initiativeAPI.schemas";
import { type ItemEndKind, idsByKind, type LinkedRef, sameIds } from "@/lib/relationships";

const ref = (type: ItemEndKind, id: number): LinkedRef => ({ type, id, title: null });

/** The decision `useSetQueueItemLinks` makes, stated on its own. */
const kindsWritten = (links: LinkedRef[], previous: LinkedRef[], force = false) => {
  const wanted = idsByKind(links);
  const had = idsByKind(previous);
  const written: ItemEndKind[] = [];
  for (const kind of new Set([...wanted.keys(), ...had.keys()])) {
    const next = wanted.get(kind) ?? [];
    if (!force && sameIds(next, had.get(kind) ?? [])) continue;
    written.push(kind);
  }
  return written;
};

const doc = (id: number) => ref(SearchEntityType.file, id);
const task = (id: number) => ref(SearchEntityType.task, id);

describe("which kinds a save writes", () => {
  it("leaves alone a kind nobody touched", () => {
    expect(kindsWritten([doc(1), task(2)], [doc(1), task(2)])).toEqual([]);
  });

  it("writes a kind whose set changed", () => {
    expect(kindsWritten([doc(1), task(3)], [doc(1), task(2)])).toEqual([SearchEntityType.task]);
  });

  it("clears a kind that lost its last link", () => {
    // The set has to be written as empty; skipping it would leave the link on.
    expect(kindsWritten([doc(1)], [doc(1), task(2)])).toEqual([SearchEntityType.task]);
  });

  it("reads a reorder as no change", () => {
    expect(kindsWritten([doc(2), doc(1)], [doc(1), doc(2)])).toEqual([]);
  });

  it("writes every kind when forced, including one that looks unchanged", () => {
    // A retry: the kind that failed asks for exactly what it asked for before,
    // so without this it would be skipped as unchanged and never land.
    expect(kindsWritten([doc(1), task(2)], [doc(1), task(2)], true).sort()).toEqual(
      [SearchEntityType.file, SearchEntityType.task].sort()
    );
  });

  it("still clears a removed kind when forced", () => {
    expect(kindsWritten([doc(1)], [doc(1), task(2)], true).sort()).toEqual(
      [SearchEntityType.file, SearchEntityType.task].sort()
    );
  });
});
