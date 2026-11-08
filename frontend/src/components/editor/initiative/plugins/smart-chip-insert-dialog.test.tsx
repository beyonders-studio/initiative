/**
 * Inserting a smart chip.
 *
 * Two things that were wrong and are invisible to a type-checker. The dialog is
 * opened from something that hands focus back as it closes, so `autoFocus` on
 * the search box lost the race and the caret landed elsewhere — you had to
 * click the field before you could type. And the suggestion list claimed the
 * full height of a stretched grid item while sitting under that search box, so
 * it hung out of the bottom of the dialog by the height of the box above it.
 *
 * The second is a layout fact, which jsdom cannot measure. What is asserted
 * here is the class that caused it, which is the part that can regress.
 */
import fs from "node:fs";
import path from "node:path";

import { screen, waitFor } from "@testing-library/react";
import { HttpResponse } from "msw";
import { useEffect, useRef } from "react";
import { describe, expect, it } from "vitest";

import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";
import { SmartChipInsertDialog } from "@/components/editor/initiative/plugins/smart-chip-insert-dialog";

const editor = { update: () => {} } as never;

const page = () => () => (
  <SmartChipInsertDialog initiativeId={7} activeEditor={editor} onClose={() => {}} />
);

describe("SmartChipInsertDialog", () => {
  /**
   * What actually opened this dialog: something that takes focus back as it
   * closes — the toolbar's select restoring its trigger, the `/` menu
   * returning to the editor. It runs after the dialog has mounted, which is
   * why `autoFocus` alone was not enough, and why a test without it would pass
   * against the bug.
   */
  function FocusThief() {
    const ref = useRef<HTMLButtonElement>(null);
    useEffect(() => ref.current?.focus(), []);
    return <button type="button" ref={ref} />;
  }

  const pageWithThief = () => () => (
    <>
      <SmartChipInsertDialog initiativeId={7} activeEditor={editor} onClose={() => {}} />
      <FocusThief />
    </>
  );

  it("puts the caret in the search box, and keeps it", async () => {
    server.use(communityHttp.get("/search/recent", () => HttpResponse.json([])));

    renderPage(pageWithThief());

    const search = await screen.findByLabelText(/search for something to show/i);
    await waitFor(() => expect(document.activeElement).toBe(search));
  });

  // cmdk moves the highlight and answers Enter for the input it owns. A search
  // box that merely sits above a Command looks the same and leaves every
  // suggestion mouse-only, so what is asserted is the ownership.
  it("lets the keyboard reach the suggestions", async () => {
    server.use(
      communityHttp.get("/search/recent", () =>
        HttpResponse.json([
          {
            entity_type: "calendar_event",
            entity_id: 3,
            title: "Session: Cragmaw Hideout",
            initiative_id: 7,
            tool: "calendar",
            tool_id: 1,
          },
        ])
      )
    );

    renderPage(page());

    const search = await screen.findByLabelText(/search for something to show/i);
    const option = await screen.findByText("Session: Cragmaw Hideout");
    // The field drives the list: cmdk points the input at the highlighted item.
    await waitFor(() => expect(search).toHaveAttribute("aria-controls"));
    expect(search.closest("[cmdk-root]")).toContainElement(option);
  });
});

describe("Command", () => {
  // `h-full` inside a dialog's grid is what put the list outside the dialog: a
  // grid item is stretched to its row, and a Command claiming all of that while
  // a search box sits above it overflows by exactly the box's height. Every
  // place a Command is the whole surface, it is the only child — so sizing to
  // content leaves those unchanged.
  it("sizes to its content rather than its container", () => {
    // Asserted against the source rather than a rendered box, because jsdom
    // does no layout — which is exactly why nothing caught this.
    const source = fs.readFileSync(path.resolve(__dirname, "../../../../ui/command.tsx"), "utf-8");
    const base = /"flex[^"]*rounded-md bg-popover[^"]*"/.exec(source)?.[0];

    expect(base, "the Command base class list moved").toBeTruthy();
    expect(base).not.toContain("h-full");
  });
});
