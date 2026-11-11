import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/__tests__/helpers/render";

import { MemberPicker, type MemberScope, type SearchMembers } from "./member-picker";

const ada = { id: 7, name: "Ada Lovelace", initials: "AL" };
const grace = { id: 8, name: "Grace Hopper", initials: "GH" };
const scope: MemberScope = { type: "initiative", initiativeId: 1 };

describe("MemberPicker", () => {
  it("names a bare id by looking it up, and searches its scope once opened", async () => {
    const searchMembers = vi.fn<SearchMembers>(async (_scope, query) =>
      "ids" in query ? [grace] : [ada, grace]
    );
    const onChange = vi.fn();
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

describe("MemberPicker with multiple", () => {
  it("shows the people picked as chips, looking up only those it was not given", async () => {
    const searchMembers = vi.fn<SearchMembers>(async () => [grace]);
    const onChange = vi.fn();
    renderWithProviders(
      <MemberPicker
        multiple
        searchMembers={searchMembers}
        scope={scope}
        value={[7, 8]}
        selected={[ada]}
        onChange={onChange}
        placeholder="Search members"
      />
    );
    expect(await screen.findByText("Grace Hopper")).toBeInTheDocument();
    expect(screen.getByText("Ada Lovelace")).toBeInTheDocument();
    expect(searchMembers).toHaveBeenCalledWith(scope, { ids: [8] });
    expect(searchMembers).not.toHaveBeenCalledWith(scope, { ids: [7, 8] });

    await userEvent.click(screen.getByRole("button", { name: "Remove Ada Lovelace" }));
    expect(onChange).toHaveBeenLastCalledWith([8], [grace]);
    await userEvent.click(screen.getByRole("button", { name: "Clear assignees" }));
    expect(onChange).toHaveBeenLastCalledWith([], []);
  });

  it("lists the extras first, then the reader, then everyone else", async () => {
    const onToggle = vi.fn();
    const onChange = vi.fn();
    renderWithProviders(
      <MemberPicker
        multiple
        variant="filter"
        searchMembers={async () => [ada, grace]}
        scope={scope}
        value={[]}
        extras={[{ value: "me", label: "Assigned to me", selected: false, onToggle }]}
        currentUserId={grace.id}
        onChange={onChange}
        placeholder="All assignees"
      />
    );
    await userEvent.click(screen.getByRole("combobox"));
    await screen.findByRole("option", { name: /Ada Lovelace/ });
    const options = screen.getAllByRole("option");
    expect(options).toHaveLength(3);
    expect(options[0]).toHaveTextContent("Assigned to me");
    expect(options[1]).toHaveTextContent("Grace Hopper");
    expect(options[1]).toHaveTextContent("You");
    expect(options[2]).toHaveTextContent("Ada Lovelace");

    await userEvent.click(options[0]);
    expect(onToggle).toHaveBeenCalledWith(true);
    expect(onChange).not.toHaveBeenCalled();
  });

  it("keeps a picked person listed when the search misses them", async () => {
    const onChange = vi.fn();
    renderWithProviders(
      <MemberPicker
        multiple
        variant="filter"
        searchMembers={async (_scope, query) => ("ids" in query ? [] : [ada])}
        scope={scope}
        value={[99]}
        onChange={onChange}
        placeholder="All assignees"
      />
    );
    // Nobody in the scope has the id, so it is drawn by its number.
    expect(await screen.findByText("User #99")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("combobox"));
    await screen.findByRole("option", { name: /Ada Lovelace/ });
    const kept = screen.getByRole("option", { name: /User #99/ });
    expect(kept).toHaveAttribute("aria-checked", "true");
    await userEvent.click(kept);
    expect(onChange).toHaveBeenCalledWith([], []);
  });

  it("picks the people a plug-in knows by reference, on a row of its own kind", async () => {
    const adaRef = { ...ada, id: "p-ada" };
    const graceRef = { ...grace, id: "p-grace" };
    const material: MemberScope<string> = { type: "canOpen", tool: "material", id: 3 };
    const searchMembers = vi.fn<SearchMembers<string, string>>(async (_scope, query) =>
      "ids" in query ? [graceRef] : [adaRef, graceRef]
    );
    const onChange = vi.fn();
    renderWithProviders(
      <MemberPicker
        multiple
        searchMembers={searchMembers}
        scope={material}
        value={["p-grace"]}
        onChange={onChange}
        placeholder="Search members"
      />
    );
    expect(await screen.findByText("Grace Hopper")).toBeInTheDocument();
    expect(searchMembers).toHaveBeenCalledWith(material, { ids: ["p-grace"] });

    await userEvent.click(screen.getByRole("combobox"));
    await userEvent.click(await screen.findByRole("option", { name: /Ada Lovelace/ }));
    expect(onChange).toHaveBeenLastCalledWith(["p-grace", "p-ada"], [graceRef, adaRef]);
  });
});
