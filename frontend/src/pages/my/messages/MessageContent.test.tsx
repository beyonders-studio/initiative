/**
 * What a message body is allowed to become.
 *
 * The formatting is react-markdown's and is not on trial here. What is worth
 * asserting is the narrowing: a direct message renders less than a comment
 * does, and the reasons are about the reader rather than about taste — a
 * picture fetched on arrival reports where they are and when they opened it,
 * and markup carried in the body would be the sender writing their page.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { BLOCKED_URL } from "@/ui/lib/safeUrl";

import { MessageContent } from "./MessageContent";

describe("a message body", () => {
  it("formats the basics", () => {
    render(<MessageContent body={"**bold** and `code`\n\n- one\n- two"} />);

    expect(screen.getByText("bold").tagName).toBe("STRONG");
    expect(screen.getByText("code").tagName).toBe("CODE");
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
  });

  it("keeps a single newline as a line break", () => {
    // A composer is a textarea, and what somebody typed on two lines has to
    // arrive on two — markdown would otherwise run them into one paragraph.
    const { container } = render(<MessageContent body={"first\nsecond"} />);

    expect(container.querySelectorAll("br")).toHaveLength(1);
  });

  it("never fetches a picture the sender chose", () => {
    // The whole point of the conversation is that nobody learns where the
    // reader is or when they looked. An <img> would tell the sender both.
    const { container } = render(
      <MessageContent body={"![a cat](https://example.test/cat.png)"} />
    );

    expect(container.querySelector("img")).toBeNull();
    expect(screen.getByRole("link", { name: "a cat" })).toHaveAttribute(
      "href",
      "https://example.test/cat.png"
    );
  });

  it("opens a link away from the app and tells the far end nothing", () => {
    render(<MessageContent body={"[somewhere](https://example.test/)"} />);

    const link = screen.getByRole("link", { name: "somewhere" });
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
  });

  it("will not follow a scheme it does not trust", () => {
    // The words survive; the destination becomes the blocked address.
    const { container } = render(<MessageContent body={"[tap](javascript:alert(1))"} />);

    const anchor = container.querySelector("a");
    expect(anchor).toHaveTextContent("tap");
    expect(anchor?.getAttribute("href")).toBe(BLOCKED_URL);
  });

  it("carries no markup of its own", () => {
    // Raw HTML is off, so a body that contains a tag says the tag.
    const { container } = render(<MessageContent body={'<button onclick="x">press</button>'} />);

    expect(container.querySelector("button")).toBeNull();
  });
});
