import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { buildPropertyDefinition } from "@/__tests__/factories/properties";
import { renderWithProviders } from "@/__tests__/helpers/render";
import type { MetadataType } from "@/api/generated/initiativeAPI.schemas";

import { AddPropertyButton } from "./AddPropertyButton";

describe("AddPropertyButton", () => {
  it("lists every definition the caller can see (no applies_to scope)", async () => {
    renderWithProviders(
      <AddPropertyButton
        definitions={[
          buildPropertyDefinition({ id: 1, name: "Alpha" }),
          buildPropertyDefinition({ id: 2, name: "Beta" }),
          buildPropertyDefinition({ id: 3, name: "Gamma" }),
        ]}
        initiativeId={7}
        create={vi.fn()}
        currentPropertyIds={[]}
        onAdd={vi.fn()}
      />
    );
    await userEvent.click(screen.getByRole("button", { name: /Add metadata/i }));
    await waitFor(() => expect(screen.getByText("Alpha")).toBeInTheDocument());
    expect(screen.getByText("Beta")).toBeInTheDocument();
    expect(screen.getByText("Gamma")).toBeInTheDocument();
  });

  it("offers a task's project properties beside the metadata, each under its own heading", async () => {
    renderWithProviders(
      <AddPropertyButton
        definitions={[
          buildPropertyDefinition({ id: 2, name: "Sprint", project_id: 4 }),
          buildPropertyDefinition({ id: 1, name: "Budget" }),
        ]}
        initiativeId={7}
        create={vi.fn()}
        owner={{ kind: "project", id: 4 }}
        currentPropertyIds={[]}
        onAdd={vi.fn()}
      />
    );
    await userEvent.click(screen.getByRole("button", { name: "Add property or metadata" }));

    const metadata = await screen.findByRole("group", { name: "This project's properties" });
    expect(within(metadata).getByText("Sprint")).toBeInTheDocument();
    const properties = screen.getByRole("group", { name: "The initiative's metadata" });
    expect(within(properties).getByText("Budget")).toBeInTheDocument();
    expect(within(properties).queryByText("Sprint")).not.toBeInTheDocument();
  });

  it("filters out definitions whose id is in currentPropertyIds", async () => {
    renderWithProviders(
      <AddPropertyButton
        definitions={[
          buildPropertyDefinition({ id: 1, name: "Alpha" }),
          buildPropertyDefinition({ id: 2, name: "Beta" }),
        ]}
        initiativeId={7}
        create={vi.fn()}
        currentPropertyIds={[1]}
        onAdd={vi.fn()}
      />
    );
    await userEvent.click(screen.getByRole("button", { name: /Add metadata/i }));
    await waitFor(() => expect(screen.getByText("Beta")).toBeInTheDocument());
    expect(screen.queryByText("Alpha")).not.toBeInTheDocument();
  });

  it("calls onAdd(definition) when an existing definition is picked", async () => {
    const defs = [buildPropertyDefinition({ id: 7, name: "Priority" })];
    const onAdd = vi.fn();
    renderWithProviders(
      <AddPropertyButton
        definitions={defs}
        initiativeId={7}
        create={vi.fn()}
        currentPropertyIds={[]}
        onAdd={onAdd}
      />
    );
    await userEvent.click(screen.getByRole("button", { name: /Add metadata/i }));
    const item = await screen.findByText("Priority");
    await userEvent.click(item);
    expect(onAdd).toHaveBeenCalledTimes(1);
    expect(onAdd).toHaveBeenCalledWith(expect.objectContaining({ id: 7, name: "Priority" }));
  });

  it("filters the list case-insensitively by the search input", async () => {
    renderWithProviders(
      <AddPropertyButton
        definitions={[
          buildPropertyDefinition({ id: 1, name: "Alpha" }),
          buildPropertyDefinition({ id: 2, name: "Beta" }),
        ]}
        initiativeId={7}
        create={vi.fn()}
        currentPropertyIds={[]}
        onAdd={vi.fn()}
      />
    );
    await userEvent.click(screen.getByRole("button", { name: /Add metadata/i }));
    const searchInput = await screen.findByPlaceholderText(/Search/i);
    await userEvent.type(searchInput, "BET");
    await waitFor(() => {
      expect(screen.getByText("Beta")).toBeInTheDocument();
      expect(screen.queryByText("Alpha")).not.toBeInTheDocument();
    });
  });

  it("creates a new property through create and calls onAdd with the returned definition", async () => {
    const create = vi.fn(async (body: { name: string; type: MetadataType }) =>
      buildPropertyDefinition({ id: 99, name: body.name, type: body.type })
    );

    const onAdd = vi.fn();
    renderWithProviders(
      <AddPropertyButton
        definitions={[]}
        initiativeId={7}
        create={create}
        currentPropertyIds={[]}
        onAdd={onAdd}
      />
    );

    await userEvent.click(screen.getByRole("button", { name: /Add metadata/i }));
    // "New metadata" entry in the command list.
    const createEntry = await screen.findByText(/New metadata/i);
    await userEvent.click(createEntry);

    // Fill in the name.
    const nameInput = await screen.findByLabelText(/^Name$/);
    await userEvent.type(nameInput, "Quarter");
    // Default type is text, so submit directly.
    const submit = screen.getByRole("button", { name: "Create" });
    await userEvent.click(submit);

    await waitFor(() => {
      expect(create).toHaveBeenCalledTimes(1);
    });
    expect(create.mock.calls[0][0]).toEqual(
      expect.objectContaining({
        name: "Quarter",
        type: "text",
        initiative_id: 7,
      })
    );
    await waitFor(() =>
      expect(onAdd).toHaveBeenCalledWith(expect.objectContaining({ id: 99, name: "Quarter" }))
    );
  });

  it("disables the trigger when disabled=true", () => {
    renderWithProviders(
      <AddPropertyButton
        definitions={[]}
        initiativeId={7}
        create={vi.fn()}
        currentPropertyIds={[]}
        onAdd={vi.fn()}
        disabled
      />
    );
    expect(screen.getByRole("button", { name: /Add metadata/i })).toBeDisabled();
  });
});
