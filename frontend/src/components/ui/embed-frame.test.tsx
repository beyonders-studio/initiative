import { act, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { EmbedFrame } from "./embed-frame";

const heightOf = (data: unknown) => (typeof data === "number" ? data : null);

const post = (data: unknown, origin: string, source: MessageEventSource | null) =>
  act(() => {
    window.dispatchEvent(new MessageEvent("message", { data, origin, source }));
  });

describe("EmbedFrame", () => {
  it("takes the height only its own frame reports from its own origin", () => {
    render(<EmbedFrame src="https://embed.example.com/post/1" title="Post" heightOf={heightOf} />);
    const frame = screen.getByTitle("Post") as HTMLIFrameElement;

    post(300, "https://elsewhere.example.com", frame.contentWindow);
    post(300, "https://embed.example.com", window);
    expect(frame.style.height).toBe("");

    post(300, "https://embed.example.com", frame.contentWindow);
    expect(frame.style.height).toBe("300px");

    post(99999, "https://embed.example.com", frame.contentWindow);
    expect(frame.style.height).toBe("2000px");
  });

  it("frames nothing on the app's own origin", () => {
    render(<EmbedFrame src={`${window.location.origin}/page`} title="Own" />);
    expect(screen.queryByTitle("Own")).toBeNull();
  });
});
