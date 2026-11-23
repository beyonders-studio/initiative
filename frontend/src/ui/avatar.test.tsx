import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Avatar, AvatarFallback } from "./avatar";

// The tests stick to fallback-only avatars so they can assert on the fallback
// element directly via its text content. jsdom normalizes HSL backgrounds to
// RGB on read, so colours are compared with each other rather than a literal.

describe("AvatarFallback", () => {
  // The guard is `userId > 0`: a zero/negative id signals a non-user fallback.
  it.each([
    ["no userId", undefined],
    ["a userId of 0", 0],
  ])("uses the default bg-muted class with %s", (_case, userId) => {
    render(
      <Avatar>
        <AvatarFallback userId={userId}>AB</AvatarFallback>
      </Avatar>
    );
    const fallback = screen.getByText("AB");
    expect(fallback.className).toMatch(/bg-muted/);
    expect(fallback.style.backgroundColor).toBe("");
    expect(fallback.style.color).toBe("");
  });

  it("colours a user by their id: stable for one id, distinct between ids", () => {
    render(
      <>
        {[7, 7, 2].map((userId, index) => (
          <Avatar key={index}>
            <AvatarFallback userId={userId}>{`U${index}`}</AvatarFallback>
          </Avatar>
        ))}
      </>
    );
    const [first, again, other] = ["U0", "U1", "U2"].map((name) => screen.getByText(name));

    // bg-muted gives way to a colour set inline, under the shared dark slate-900.
    expect(first.className).not.toMatch(/bg-muted/);
    expect(first.style.backgroundColor).not.toBe("");
    expect(first.style.color.toLowerCase()).toBe("rgb(15, 23, 42)");
    expect(again.style.backgroundColor).toBe(first.style.backgroundColor);
    expect(other.style.backgroundColor).not.toBe(first.style.backgroundColor);
  });
});
