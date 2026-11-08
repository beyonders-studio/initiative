import { fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/__tests__/helpers/render";

import { MarkdownComposer } from "./MarkdownComposer";

/** The composer is controlled, so a test drives it through its owner's state. */
const Host = ({
  initial = "",
  defaultMode,
}: {
  initial?: string;
  defaultMode?: "write" | "preview";
}) => {
  const [value, setValue] = useState(initial);
  return (
    <>
      <MarkdownComposer
        value={value}
        onChange={setValue}
        placeholder="Say something"
        defaultMode={defaultMode}
      />
      <output>{value}</output>
    </>
  );
};

const field = () => screen.getByRole("textbox") as HTMLTextAreaElement;

/** Preview-first with the text arriving after mount — a task description is
 *  seeded from its query, not from the first render. */
const LateHost = ({ value }: { value: string }) => (
  <MarkdownComposer value={value} onChange={() => {}} defaultMode="preview" />
);

/**
 * jsdom lays nothing out, so the toolbar's measurements are stood in for: the
 * row is `rowWidth` wide and every item in it is one button wide.
 */
const stubLayout = (rowWidth: number, itemWidth = 34) => {
  // The measured row is the toolbar's own scroll box, not the labelled
  // container around it — that one also holds the overflow control.
  const widthOf = (element: HTMLElement) =>
    element.classList.contains("overflow-hidden") ? rowWidth : itemWidth;
  for (const property of ["offsetWidth", "clientWidth"]) {
    Object.defineProperty(HTMLElement.prototype, property, {
      configurable: true,
      get(this: HTMLElement) {
        return widthOf(this);
      },
    });
  }
};

afterEach(() => {
  for (const property of ["offsetWidth", "clientWidth"]) {
    Reflect.deleteProperty(HTMLElement.prototype, property);
  }
});

const select = (from: number, to: number) => {
  const element = field();
  element.focus();
  element.setSelectionRange(from, to);
};

describe("MarkdownComposer", () => {
  it("formats the selection with a toolbar button", async () => {
    const user = userEvent.setup();
    renderWithProviders(<Host initial="ship it" />);

    select(0, 4);
    await user.click(screen.getByRole("button", { name: "Bold" }));

    expect(screen.getByRole("status")).toHaveTextContent("**ship** it");
  });

  it("puts the selection back around what it just formatted", async () => {
    const user = userEvent.setup();
    renderWithProviders(<Host initial="ship it" />);

    select(0, 4);
    await user.click(screen.getByRole("button", { name: "Bold" }));

    await waitFor(() => {
      expect(field().selectionStart).toBe(2);
      expect(field().selectionEnd).toBe(6);
    });
  });

  it("formats from the keyboard", async () => {
    const user = userEvent.setup();
    renderWithProviders(<Host initial="ship it" />);

    select(0, 4);
    await user.keyboard("{Control>}b{/Control}");

    expect(screen.getByRole("status")).toHaveTextContent("**ship** it");
  });

  it("renders the draft in the preview tab", async () => {
    const user = userEvent.setup();
    renderWithProviders(<Host initial="## Plan" />);

    await user.click(screen.getByRole("tab", { name: "Preview" }));

    expect(screen.getByRole("heading", { name: "Plan" })).toBeInTheDocument();
  });

  it("says there is nothing to preview when the draft is empty", async () => {
    const user = userEvent.setup();
    renderWithProviders(<Host />);

    await user.click(screen.getByRole("tab", { name: "Preview" }));

    expect(screen.getByText("Nothing to preview yet.")).toBeInTheDocument();
  });

  it("puts the field away while the preview is showing, and brings it back intact", async () => {
    const user = userEvent.setup();
    renderWithProviders(<Host initial="half a thought" />);

    await user.click(screen.getByRole("tab", { name: "Preview" }));
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "Write" }));
    expect(field()).toHaveValue("half a thought");
  });

  it("leaves the caret ready to type after a list marker", async () => {
    const user = userEvent.setup();
    renderWithProviders(<Host />);

    await user.click(screen.getByRole("button", { name: "Bulleted list" }));
    await user.keyboard("first");

    expect(screen.getByRole("status")).toHaveTextContent("- first");
  });

  it("does not offer formatting while the preview is showing", async () => {
    const user = userEvent.setup();
    renderWithProviders(<Host initial="ship it" />);

    await user.click(screen.getByRole("tab", { name: "Preview" }));

    expect(screen.getByRole("button", { name: "Bold" })).toBeDisabled();
  });

  it("keeps every button in the row when they all fit", () => {
    stubLayout(1000);
    renderWithProviders(<Host />);

    expect(screen.getByRole("button", { name: "Task list" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "More formatting" })).not.toBeInTheDocument();
  });

  it("moves the buttons that no longer fit into a menu instead of wrapping", async () => {
    const user = userEvent.setup();
    stubLayout(150);
    renderWithProviders(<Host />);

    // The row sheds from the right, so what a writer reaches for most stays.
    expect(screen.getByRole("button", { name: "Heading" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Task list" })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "More formatting" }));

    expect(await screen.findByRole("menuitem", { name: "Task list" })).toBeInTheDocument();
  });

  it("formats from the overflow menu", async () => {
    const user = userEvent.setup();
    stubLayout(150);
    renderWithProviders(<Host initial="one" />);

    field().setSelectionRange(0, 3);
    await user.click(screen.getByRole("button", { name: "More formatting" }));
    await user.click(await screen.findByRole("menuitem", { name: "Bulleted list" }));

    expect(screen.getByRole("status")).toHaveTextContent("- one");
  });

  it("carries a list marker onto the next line as you type", async () => {
    const user = userEvent.setup();
    renderWithProviders(<Host />);

    await user.click(screen.getByRole("button", { name: "Bulleted list" }));
    await user.keyboard("first{Enter}second");

    expect(screen.getByRole("status")).toHaveTextContent("- first - second");
  });

  it("ends the list when you press Enter on an empty item", async () => {
    const user = userEvent.setup();
    renderWithProviders(<Host />);

    await user.click(screen.getByRole("button", { name: "Bulleted list" }));
    await user.keyboard("first{Enter}{Enter}after");

    // The empty item's marker comes off and the caret stays on that line, so
    // what follows sits directly under the list rather than a blank line below.
    expect(field()).toHaveValue("- first\nafter");
  });

  it("opens on the preview when the caller asks for it", () => {
    renderWithProviders(<Host initial="## Plan" defaultMode="preview" />);

    expect(screen.getByRole("heading", { name: "Plan" })).toBeInTheDocument();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  });

  it("ticks a checklist box in the preview and stays on the preview", async () => {
    const user = userEvent.setup();
    renderWithProviders(<Host initial="- [ ] Book the room" defaultMode="preview" />);

    await user.click(screen.getByRole("checkbox"));

    expect(screen.getByRole("checkbox")).toBeChecked();
    expect(screen.getByRole("status")).toHaveTextContent("- [x] Book the room");
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  });

  it("opens ready to type when preview-first has nothing to preview", () => {
    renderWithProviders(<Host defaultMode="preview" />);

    expect(field()).toBeInTheDocument();
  });

  it("stays on the field while text is typed into an empty preview-first one", async () => {
    const user = userEvent.setup();
    renderWithProviders(<Host defaultMode="preview" />);

    await user.type(field(), "Plan");

    expect(field()).toHaveValue("Plan");
  });

  it("settles on the preview once a late-loading draft arrives", async () => {
    const { rerender } = renderWithProviders(<LateHost value="" />);
    expect(screen.getByRole("textbox")).toBeInTheDocument();

    rerender(<LateHost value="## Plan" />);

    await waitFor(() => expect(screen.getByRole("heading", { name: "Plan" })).toBeInTheDocument());
  });

  it("keeps the tab the reader picked", async () => {
    const user = userEvent.setup();
    renderWithProviders(<Host initial="## Plan" defaultMode="preview" />);

    await user.click(screen.getByRole("tab", { name: "Write" }));

    expect(field()).toHaveValue("## Plan");
  });
});

describe("pictures", () => {
  const png = () => new File(["x"], "shot.png", { type: "image/png" });

  const PictureHost = ({ upload }: { upload: (file: File) => Promise<string> }) => {
    const [value, setValue] = useState("See:");
    return (
      <>
        <MarkdownComposer value={value} onChange={setValue} onUploadImage={upload} />
        <output>{value}</output>
      </>
    );
  };

  const paste = (file: File) =>
    fireEvent.paste(field(), { clipboardData: { files: [file], types: ["Files"] } });

  it("puts a pasted picture where the caret is, once it has been stored", async () => {
    let finish: (url: string) => void = () => {};
    const upload = vi.fn(() => new Promise<string>((resolve) => (finish = resolve)));
    renderWithProviders(<PictureHost upload={upload} />);
    select(4, 4);

    paste(png());

    // A placeholder at once, so the writer can see something is happening.
    expect(field().value).toMatch(/^See:\n!\[.*shot\.png.*\]\(uploading:\d+\)$/);
    expect(upload).toHaveBeenCalledOnce();

    finish("/uploads/9/task-a.png");
    await waitFor(() => expect(field()).toHaveValue("See:\n![shot](/uploads/9/task-a.png)"));
  });

  it("takes the placeholder back out when the picture could not be stored", async () => {
    const upload = vi.fn(() => Promise.reject(new Error("nope")));
    renderWithProviders(<PictureHost upload={upload} />);
    select(4, 4);

    paste(png());

    await waitFor(() => expect(field()).toHaveValue("See:\n"));
  });

  it("leaves pasted text to the field", () => {
    const upload = vi.fn();
    renderWithProviders(<PictureHost upload={upload} />);

    fireEvent.paste(field(), { clipboardData: { files: [], types: ["text/plain"] } });

    expect(upload).not.toHaveBeenCalled();
  });

  it("offers a button for a picture only where one can be stored", () => {
    const { unmount } = renderWithProviders(<Host />);
    expect(screen.queryByRole("button", { name: "Image" })).toBeNull();
    unmount();

    renderWithProviders(<PictureHost upload={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Image" })).toBeInTheDocument();
  });
});
