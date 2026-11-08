import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/__tests__/helpers/render";

import { MemberPicker, type MemberScope, type SearchMembers } from "./member-picker";

describe("MemberPicker", () => {
  it("names a bare id by looking it up, and searches its scope once opened", async () => {
    const ada = { id: 7, name: "Ada Lovelace", initials: "AL" };
    const grace = { id: 8, name: "Grace Hopper", initials: "GH" };
    const searchMembers = vi.fn<SearchMembers>(async (_scope, query) =>
      "ids" in query ? [grace] : [ada, grace]
    );
    const onChange = vi.fn();
    const scope: MemberScope = { type: "initiative", initiativeId: 1 };
    renderWithProviders(
      <MemberPicker
        searchMembers={searchMembers}
        scope={scope}
        value={8}
        onChange={onChange}
        placeholder="Assign person…"
      />
    );
    expect(await screen.findByText("Grace Hopper")).toBeInTheDocument();
    expect(searchMembers).toHaveBeenCalledWith(scope, { ids: [8] });
    expect(searchMembers).not.toHaveBeenCalledWith(scope, { search: "" });

    await userEvent.click(screen.getByRole("combobox"));
    await userEvent.click(await screen.findByRole("option", { name: /Ada Lovelace/i }));
    expect(searchMembers).toHaveBeenCalledWith(scope, { search: "" });
    expect(onChange).toHaveBeenCalledWith(7, ada);
  });
});
