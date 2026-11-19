import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { renderWithProviders } from "@/__tests__/helpers/render";

import { ListingDescription, ListingGallery } from "./ListingGallery";

describe("ListingDescription", () => {
  it("draws a paragraph of '- ' lines as a list, and the rest as paragraphs", () => {
    renderWithProviders(
      <ListingDescription text={"Calendars for everyone.\n\n- One to start\n- Add more"} />
    );
    expect(screen.getByText("Calendars for everyone.").tagName).toBe("P");
    expect(screen.getAllByRole("listitem").map((item) => item.textContent)).toEqual([
      "One to start",
      "Add more",
    ]);
  });
});

describe("ListingGallery", () => {
  it("opens a screenshot full size", async () => {
    renderWithProviders(<ListingGallery name="Calendar" sources={["/a.webp", "/b.webp"]} />);
    await userEvent.click(screen.getByRole("button", { name: "Calendar screenshot 2" }));
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
  });
});
