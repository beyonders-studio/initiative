import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderEmbeddable, validateEmbeddable } from "./whiteboardEmbeds";

describe("whiteboard embeds", () => {
  it("embeds a post the app can frame, refuses one it can't, and leaves other sites to Excalidraw", () => {
    expect(validateEmbeddable("https://x.com/jack/status/20")).toBe(true);
    expect(validateEmbeddable("x.com/jack/status/20")).toBe(true);
    expect(validateEmbeddable("https://www.reddit.com/r/reddit/comments/87/memo/")).toBe(true);
    expect(validateEmbeddable("https://x.com/home")).toBe(false);
    expect(validateEmbeddable("https://twitter.com/jack")).toBe(false);
    expect(validateEmbeddable("https://www.youtube.com/watch?v=dQw4w9WgXcQ")).toBeUndefined();
  });

  it("draws a post in the app's frame and leaves other links to Excalidraw", () => {
    render(<>{renderEmbeddable({ link: "https://x.com/jack/status/20" })}</>);
    expect(screen.getByTitle("X")).toHaveAttribute(
      "src",
      "https://platform.twitter.com/embed/Tweet.html?id=20&dnt=true"
    );
    expect(renderEmbeddable({ link: "https://www.youtube.com/watch?v=dQw4w9WgXcQ" })).toBeNull();
    expect(renderEmbeddable({ link: null })).toBeNull();
  });
});
