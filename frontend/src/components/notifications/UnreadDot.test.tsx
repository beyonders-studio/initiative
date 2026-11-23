import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderWithProviders } from "@/__tests__/helpers/render";

import { UnreadDot } from "./UnreadDot";

describe("UnreadDot", () => {
  it("says what it means for a reader who cannot see it", async () => {
    renderWithProviders(<UnreadDot />);
    // A bare coloured circle is nothing to a screen reader, and this is the
    // only signal at these levels — there is no count beside it to fall back on.
    expect(await screen.findByRole("img", { name: /unread/i })).toBeInTheDocument();
  });
});
