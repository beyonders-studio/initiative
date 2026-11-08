import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { buildTagSummary } from "@/__tests__/factories";
import { renderPage } from "@/__tests__/helpers/render";

import { ToolCard } from "./ToolCard";

describe("ToolCard", () => {
  it("opens its page, and a tag on it opens the tag's instead", async () => {
    const tag = buildTagSummary({ id: 5, name: "Urgent" });
    const { router } = renderPage(
      () => <ToolCard to="/i/3/wikis/8" name="Handbook" tags={[tag]} />,
      { initialRoute: "/c/1" }
    );

    const card = (await screen.findByText("Handbook")).closest("a");
    expect(card).toHaveAttribute("href", "/c/1/i/3/wikis/8");

    await userEvent.click(screen.getByRole("button", { name: "Urgent" }));
    await waitFor(() => expect(router.state.location.pathname).toBe("/c/1/tags/5"));
  });
});
