import { Capacitor } from "@capacitor/core";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { apiClient } from "@/api/client";
import { ThemeContext } from "@/hooks/useTheme";

import { Markdown } from "./Markdown";

/** The wrapper the classes that keep content inside its container live on. */
const root = (container: HTMLElement) => container.firstElementChild as HTMLElement;

describe("Markdown", () => {
  it("renders nothing for empty content", () => {
    const { container } = render(<Markdown content="" />);
    expect(container).toBeEmptyDOMElement();
  });

  it("wraps code fences instead of letting them widen the container", () => {
    const { container } = render(
      <Markdown content={"```\nconst averyveryverylongidentifierwithnospaces = 1;\n```"} />
    );

    const classes = root(container).className;
    expect(classes).toContain("[&_pre]:whitespace-pre-wrap");
    expect(classes).toContain("[&_pre]:wrap-break-word");
    expect(classes).toContain("[&_pre]:max-w-full");
    expect(classes).toContain("[&_pre]:overflow-x-auto");
    expect(container.querySelector("pre")).not.toBeNull();
  });

  it("breaks long inline code, links and prose", () => {
    const { container } = render(<Markdown content="`inline` and text" />);

    const classes = root(container).className;
    expect(classes).toContain("wrap-break-word");
    expect(classes).toContain("[&_code]:wrap-break-word");
    expect(classes).toContain("[&_a]:break-all");
    expect(classes).toContain("[&_img]:max-w-full");
  });

  it("scrolls a wide table instead of widening the container", () => {
    const { container } = render(<Markdown content={"| a | b |\n| - | - |\n| 1 | 2 |"} />);

    const classes = root(container).className;
    expect(classes).toContain("[&_table]:overflow-x-auto");
    expect(classes).toContain("[&_table]:max-w-full");
    expect(container.querySelector("table")).not.toBeNull();
  });

  it("keeps the caller's classes alongside the defaults", () => {
    const { container } = render(<Markdown content="hello" className="line-clamp-2" />);

    expect(root(container).className).toContain("line-clamp-2");
    expect(screen.getByText("hello")).toBeInTheDocument();
  });

  it("does not leak the hast node onto rendered elements", () => {
    const { container } = render(<Markdown content="[link](https://example.com)" />);

    const anchor = container.querySelector("a");
    expect(anchor?.getAttribute("node")).toBeNull();
  });

  it("opens a picture full size, paging through the others in reading order", async () => {
    const user = userEvent.setup();
    render(
      <Markdown content={"![First](/uploads/1/a.png)\n\ntext\n\n![Second](/uploads/1/b.png)"} />
    );

    await user.click(screen.getByRole("button", { name: "View Second full size" }));

    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByRole("img", { name: "Second" })).toBeInTheDocument();
    expect(within(dialog).getByText("2 / 2")).toBeInTheDocument();
  });

  it("leaves a picture inside a link to the link", () => {
    render(<Markdown content="[![Badge](/uploads/1/badge.svg)](https://example.com)" />);

    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.getByRole("link").querySelector("img")).not.toBeNull();
  });

  it("draws the picture without a way to open it when zooming is off", () => {
    render(<Markdown content="![Shot](/uploads/1/a.png)" zoomImages={false} />);

    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Shot" })).toBeInTheDocument();
  });

  it("turns a picture from anywhere else into a link unless the text is trusted", () => {
    const markdown = "![pixel](https://tracker.example/p.gif)";
    const { container, rerender } = render(<Markdown content={markdown} />);

    expect(container.querySelector("img")).toBeNull();
    expect(screen.getByRole("link", { name: "pixel" })).toHaveAttribute(
      "href",
      "https://tracker.example/p.gif"
    );

    rerender(<Markdown content={markdown} remoteImages />);
    expect(screen.getByRole("img", { name: "pixel" })).toBeInTheDocument();
  });

  it("opens a link to another site in a new tab and keeps an in-app link here", () => {
    render(<Markdown content="[away](https://example.com) and [home](/c/1/projects)" />);

    const away = screen.getByRole("link", { name: "away" });
    expect(away).toHaveAttribute("target", "_blank");
    expect(away).toHaveAttribute("rel", "noopener noreferrer");
    expect(screen.getByRole("link", { name: "home" })).not.toHaveAttribute("target");
  });

  it("draws a release's screenshot in the theme the app is in", () => {
    const content = "![The Gantt view](docs/images/releases/gantt.webp)";
    const theme = (resolvedTheme: "light" | "dark") => ({
      theme: resolvedTheme,
      resolvedTheme,
      setTheme: () => {},
      toggleTheme: () => {},
    });

    const { unmount } = render(
      <ThemeContext value={theme("light")}>
        <Markdown surface="release" remoteImages content={content} />
      </ThemeContext>
    );
    expect(screen.getByAltText("The Gantt view")).toHaveAttribute(
      "src",
      "https://beyonders-studio.github.io/initiative/images/releases/gantt.webp"
    );
    unmount();

    render(
      <ThemeContext value={theme("dark")}>
        <Markdown surface="release" remoteImages content={content} />
      </ThemeContext>
    );
    expect(screen.getByAltText("The Gantt view")).toHaveAttribute(
      "src",
      "https://beyonders-studio.github.io/initiative/images/releases/gantt.dark.webp"
    );
  });

  it("loads a release's screenshot from the docs site in the native app too", () => {
    vi.spyOn(Capacitor, "isNativePlatform").mockReturnValue(true);
    vi.spyOn(apiClient.defaults, "baseURL", "get").mockReturnValue(
      "https://example.com/initiative/api/v1"
    );
    render(
      <Markdown
        surface="release"
        remoteImages
        content="![The Gantt view](docs/images/releases/gantt.webp)"
      />
    );
    expect(screen.getByAltText("The Gantt view")).toHaveAttribute(
      "src",
      "https://beyonders-studio.github.io/initiative/images/releases/gantt.webp"
    );
    vi.restoreAllMocks();
  });

  it("scrolls a release's pictures sideways as a strip when there are several", async () => {
    const user = userEvent.setup();
    const { container } = render(
      <Markdown
        surface="release"
        remoteImages
        content={[
          "- **Task types.** Every project starts with four.",
          "",
          "  ![The task types in settings](docs/images/releases/task-types.webp)",
          "  ![A board showing each type](docs/images/releases/type-icons.webp)",
        ].join("\n")}
      />
    );

    const settings = screen.getByAltText("The task types in settings");
    const board = screen.getByAltText("A board showing each type");
    expect(settings.closest("p")).toBeNull();
    const strip = settings.closest(".overflow-x-auto");
    expect(strip).not.toBeNull();
    expect(strip).toContainElement(board);
    expect(container).toHaveTextContent("2");

    await user.click(screen.getByRole("button", { name: /A board showing each type/ }));
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
  });

  it("ticks a checklist item in text being edited, wherever the item sits", async () => {
    const content = "- [ ] **Book** the room\n  1) [x] nested\n\n> - [ ] quoted";
    const onChange = vi.fn();
    render(<Markdown content={content} onChange={onChange} />);

    const [book, nested, quoted] = screen.getAllByRole("checkbox");
    await userEvent.click(book);
    expect(onChange).toHaveBeenLastCalledWith(content.replace("- [ ] **Book**", "- [x] **Book**"));
    await userEvent.click(nested);
    expect(onChange).toHaveBeenLastCalledWith(content.replace("1) [x]", "1) [ ]"));
    await userEvent.click(quoted);
    expect(onChange).toHaveBeenLastCalledWith(content.replace("> - [ ]", "> - [x]"));
  });

  it("draws a checklist's boxes in place of its bullets, ticked only where it is edited", () => {
    const { container } = render(<Markdown content={"- [x] done\n- [ ] not yet"} />);

    expect(root(container).className).toContain("[&_.task-list-item]:list-none");
    expect(screen.getAllByRole("checkbox").map((box) => box.hasAttribute("disabled"))).toEqual([
      true,
      true,
    ]);
  });

  it("keeps a lone picture, or one beside text, in its paragraph", () => {
    render(
      <Markdown
        surface="release"
        remoteImages
        content={[
          "![The Gantt view](docs/images/releases/gantt.webp)",
          "",
          "See ![the board](docs/images/releases/board.webp) and ![the table](docs/images/releases/table.webp)",
        ].join("\n")}
      />
    );
    expect(screen.getByAltText("The Gantt view").closest("p")).not.toBeNull();
    expect(screen.getByAltText("the board").closest("p")).not.toBeNull();
    expect(screen.getByAltText("the table").closest(".overflow-x-auto")).toBeNull();
  });
});
