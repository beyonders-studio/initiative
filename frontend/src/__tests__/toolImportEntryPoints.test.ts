/**
 * Every tool list page offers a way in.
 *
 * Import and export are one capability — a tool's JSON envelope round-trips
 * through both — so a tool that can be exported can be imported, and the
 * place a file gets dropped is the list page for the thing inside it. The
 * failure this guards is quiet: the endpoint works, the importer works, and
 * there is simply nowhere in the app to hand it a file. Wikis, galleries and
 * posts all shipped importers that way, and posts stayed unreachable longest
 * because it is the one board that does not go through {@link ToolIndexPage}.
 *
 * Asserted against the source, because the alternative is mounting three
 * pages' worth of providers to look for one menu item — and the thing that
 * actually regresses is a page being written without the wiring.
 *
 * {@link ToolIndexPage} covers every tool with no list page of its own
 * (projects, files, wikis, queues, …), so it is on the list too:
 * the entry disappearing from it would take all of them at once.
 */
import fs from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

const read = (relative: string) => fs.readFileSync(path.resolve(__dirname, relative), "utf-8");

/** Each surface that lists an importable tool, and its source. */
const SURFACES = [
  {
    what: "the shared tool index",
    source: read("../components/tools/ToolIndexPage.tsx"),
  },
  {
    what: "the calendars page",
    source: read("../pages/initiativeTools/events/CalendarsPage.tsx"),
  },
  {
    what: "the posts board",
    source: read("../pages/initiativeTools/posts/PostsPage.tsx"),
  },
];

describe("tool list pages offer an import", () => {
  it.each(SURFACES)("$what mounts the import affordance", ({ source }) => {
    expect(source).toMatch(/\b(useToolImportAction|ToolImportAction)\b/);
  });

  it.each(SURFACES.filter((surface) => surface.source.includes("useToolImportAction")))(
    "$what renders the dialog outside the menu that holds the entry",
    ({ source }) => {
      // The hook is split precisely because a dropdown unmounts its content
      // on close, taking a dialog nested inside it along with it. Using the
      // entry without the dialog is the shape of that bug.
      expect(source).toMatch(/\.menuItem\b/);
      expect(source).toMatch(/\.dialog\b/);
    }
  );
});
