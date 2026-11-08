import { useLexicalComposerContext } from "@lexical/react/LexicalComposerContext";
import { LexicalExtensionComposer } from "@lexical/react/LexicalExtensionComposer";
import type { TableOfContentsEntry } from "@lexical/react/LexicalTableOfContentsPlugin";
import { $createHeadingNode, type HeadingTagType } from "@lexical/rich-text";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { $createTextNode, $getRoot, type LexicalEditor } from "lexical";
import { useMemo } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { renderPage } from "@/__tests__/helpers/render";
import {
  buildOutlineTree,
  DocumentOutlinePanel,
  DocumentOutlineScope,
  DocumentOutlineTracker,
} from "@/ui/editor/DocumentOutline";
import { documentExtension } from "@/ui/editor/document-extension";
import { Plugins } from "@/ui/editor/plugins";
import { TooltipProvider } from "@/ui/tooltip";

const entry = (key: string, text: string, tag: HeadingTagType): TableOfContentsEntry => [
  key,
  text,
  tag,
];

describe("buildOutlineTree", () => {
  it("files each heading under the nearest shallower one", () => {
    const tree = buildOutlineTree([
      entry("1", "Overview", "h1"),
      entry("2", "Details", "h2"),
      entry("3", "Edge cases", "h3"),
      entry("4", "Appendix", "h1"),
    ]);

    expect(tree.map((node) => node.text)).toEqual(["Overview", "Appendix"]);
    expect(tree[0].children.map((node) => node.text)).toEqual(["Details"]);
    expect(tree[0].children[0].children.map((node) => node.text)).toEqual(["Edge cases"]);
    expect(tree[1].children).toEqual([]);
  });

  it("puts the shallowest headings it actually has at the top", () => {
    const tree = buildOutlineTree([
      entry("1", "First", "h2"),
      entry("2", "Under first", "h3"),
      entry("3", "Second", "h2"),
    ]);

    expect(tree.map((node) => node.text)).toEqual(["First", "Second"]);
    expect(tree[0].children.map((node) => node.text)).toEqual(["Under first"]);
  });

  it("keeps a skipped level as nesting rather than inventing a heading", () => {
    const tree = buildOutlineTree([entry("1", "Overview", "h1"), entry("2", "Deep", "h3")]);

    expect(tree).toHaveLength(1);
    expect(tree[0].children.map((node) => node.text)).toEqual(["Deep"]);
  });

  it("closes every deeper heading when a shallower one arrives", () => {
    const tree = buildOutlineTree([
      entry("1", "A", "h3"),
      entry("2", "B", "h4"),
      entry("3", "C", "h5"),
      entry("4", "D", "h3"),
    ]);

    expect(tree.map((node) => node.text)).toEqual(["A", "D"]);
    expect(tree[0].children[0].children.map((node) => node.text)).toEqual(["C"]);
  });
});

let editor!: LexicalEditor;

function Grab(): null {
  const [found] = useLexicalComposerContext();
  editor = found;
  return null;
}

/** The document page's arrangement: the body editor in its own scrollport, with
 *  the toolbar stuck to the top of it, and the contents list beside them. The
 *  scope is the only thing joining the two. */
function Harness() {
  const extension = useMemo(() => documentExtension({ collaborative: false, editable: true }), []);

  return (
    <DocumentOutlineScope>
      <div data-testid="scrollport" style={{ overflowY: "auto" }}>
        <LexicalExtensionComposer extension={extension} contentEditable={null}>
          <TooltipProvider>
            <Grab />
            <Plugins showToolbar />
            <DocumentOutlineTracker />
          </TooltipProvider>
        </LexicalExtensionComposer>
      </div>
      <DocumentOutlinePanel isOpen onOpenChange={() => {}} />
    </DocumentOutlineScope>
  );
}

/** jsdom lays nothing out, so the geometry the outline measures is supplied. */
const atTop = (element: Element, top: number) => {
  vi.spyOn(element, "getBoundingClientRect").mockReturnValue({ top } as DOMRect);
};

/**
 * The same, installed before anything renders — the outline measures as soon as
 * the headings arrive, and a test that mocks afterwards is only agreeing with
 * whatever the first, unmocked pass happened to decide.
 *
 * `tops` is keyed on what an element says, which for a heading is its own text
 * and for the scrollport is nothing (its children's text is not its own).
 */
const layOut = (tops: Record<string, number>, toolbarHeight: number) => {
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function (
    this: HTMLElement
  ) {
    const named = this.dataset.testid ?? this.textContent ?? "";
    return { top: tops[named] ?? 0 } as DOMRect;
  });
  Object.defineProperty(HTMLElement.prototype, "offsetHeight", {
    configurable: true,
    get(this: HTMLElement) {
      return this.hasAttribute("data-editor-toolbar") ? toolbarHeight : 0;
    },
  });
};

const jsdomOffsetHeight = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "offsetHeight");

afterEach(() => {
  if (jsdomOffsetHeight) {
    Object.defineProperty(HTMLElement.prototype, "offsetHeight", jsdomOffsetHeight);
  }
});

const writeHeadings = (headings: [HeadingTagType, string][]) => {
  editor.update(
    () => {
      const root = $getRoot().clear();
      for (const [tag, text] of headings) {
        root.append($createHeadingNode(tag).append($createTextNode(text)));
      }
    },
    { discrete: true }
  );
};

describe("the document's contents", () => {
  it("lists the body's headings, nested", async () => {
    renderPage(Harness);
    await waitFor(() => expect(editor).toBeTruthy());

    writeHeadings([
      ["h1", "Overview"],
      ["h2", "Details"],
    ]);

    const overview = await screen.findByRole("button", { name: "Overview" });
    const section = overview.closest("li");
    expect(section).not.toBeNull();
    expect(
      within(section as HTMLElement).getByRole("button", { name: "Details" })
    ).toBeInTheDocument();
  });

  it("parks the chosen heading below the toolbar, not behind it", async () => {
    renderPage(Harness);
    await waitFor(() => expect(editor).toBeTruthy());

    writeHeadings([
      ["h1", "Overview"],
      ["h1", "Appendix"],
    ]);
    await screen.findByRole("button", { name: "Appendix" });

    const scrollPort = screen.getByTestId("scrollport");
    const scrollTo = vi.fn();
    scrollPort.scrollTo = scrollTo;
    atTop(scrollPort, 100);

    // One toolbar, whatever the width: it sheds controls rather than swapping.
    const toolbars = scrollPort.querySelectorAll<HTMLElement>("[data-editor-toolbar]");
    expect(toolbars).toHaveLength(1);
    Object.defineProperty(toolbars[0], "offsetHeight", { value: 48, configurable: true });

    const keys = editor.getEditorState().read(() =>
      $getRoot()
        .getChildren()
        .map((child) => child.getKey())
    );
    atTop(editor.getElementByKey(keys[0]) as HTMLElement, 200);
    atTop(editor.getElementByKey(keys[1]) as HTMLElement, 400);

    await userEvent.click(screen.getByRole("button", { name: "Appendix" }));

    // 400 (the heading) - 100 (the scrollport) - 48 (the toolbar) - 8 (room to breathe)
    expect(scrollTo).toHaveBeenCalledWith({ top: 244, behavior: "smooth" });
  });

  it("marks the heading it just scrolled to as the one being read", async () => {
    // "Appendix" sits exactly where `scrollToHeading` parks it: 48 for the
    // toolbar plus 8 of room. A reading line drawn from the scrollport's own
    // edge would fall above that and credit "Overview", which is 300px off the
    // top of the page.
    layOut({ scrollport: 0, Overview: -300, Appendix: 56 }, 48);

    renderPage(Harness);
    await waitFor(() => expect(editor).toBeTruthy());

    writeHeadings([
      ["h1", "Overview"],
      ["h1", "Appendix"],
    ]);

    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Appendix" })).toHaveAttribute(
        "aria-current",
        "location"
      )
    );
    expect(screen.getByRole("button", { name: "Overview" })).not.toHaveAttribute("aria-current");
  });

  it("says so when the document has no headings", async () => {
    renderPage(Harness);
    await waitFor(() => expect(editor).toBeTruthy());

    expect(await screen.findByText("Headings you add appear here.")).toBeInTheDocument();
  });
});
