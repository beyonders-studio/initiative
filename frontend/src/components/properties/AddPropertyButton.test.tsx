import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";

import { buildPropertyDefinition } from "@/__tests__/factories/properties";
import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { definitionsHandler } from "@/__tests__/helpers/handlers/property.handlers";
import { server } from "@/__tests__/helpers/msw-server";
import { renderWithProviders } from "@/__tests__/helpers/render";
import type { MetadataType, PropertyDefinitionRead } from "@/api/generated/initiativeAPI.schemas";

import { AddPropertyButton } from "./AddPropertyButton";

const mockDefinitions = (defs: PropertyDefinitionRead[]) => {
  server.use(communityHttp.get("/property-definitions/", () => HttpResponse.json(defs)));
};

describe("AddPropertyButton", () => {
  it("lists every definition the caller can see (no applies_to scope)", async () => {
    mockDefinitions([
      buildPropertyDefinition({ id: 1, name: "Alpha" }),
      buildPropertyDefinition({ id: 2, name: "Beta" }),
      buildPropertyDefinition({ id: 3, name: "Gamma" }),
    ]);
    renderWithProviders(
      <AddPropertyButton initiativeId={7} currentPropertyIds={[]} onAdd={vi.fn()} />
    );
    await userEvent.click(screen.getByRole("button", { name: /Add property/i }));
    await waitFor(() => expect(screen.getByText("Alpha")).toBeInTheDocument());
    expect(screen.getByText("Beta")).toBeInTheDocument();
    expect(screen.getByText("Gamma")).toBeInTheDocument();
  });

  it("offers a task's project metadata beside the properties, each under its own heading", async () => {
    server.use(
      definitionsHandler([buildPropertyDefinition({ id: 1, name: "Budget" })], {
        project: [buildPropertyDefinition({ id: 2, name: "Sprint", project_id: 4 })],
      })
    );
    renderWithProviders(
      <AddPropertyButton
        initiativeId={7}
        owner={{ kind: "project", id: 4 }}
        currentPropertyIds={[]}
        onAdd={vi.fn()}
      />
    );
    await userEvent.click(screen.getByRole("button", { name: "Add property or metadata" }));

    const metadata = await screen.findByRole("group", { name: "This project's metadata" });
    expect(within(metadata).getByText("Sprint")).toBeInTheDocument();
    const properties = screen.getByRole("group", { name: "Properties" });
    expect(within(properties).getByText("Budget")).toBeInTheDocument();
    expect(within(properties).queryByText("Sprint")).not.toBeInTheDocument();
  });

  it("filters out definitions whose id is in currentPropertyIds", async () => {
    mockDefinitions([
      buildPropertyDefinition({ id: 1, name: "Alpha" }),
      buildPropertyDefinition({ id: 2, name: "Beta" }),
    ]);
    renderWithProviders(
      <AddPropertyButton initiativeId={7} currentPropertyIds={[1]} onAdd={vi.fn()} />
    );
    await userEvent.click(screen.getByRole("button", { name: /Add property/i }));
    await waitFor(() => expect(screen.getByText("Beta")).toBeInTheDocument());
    expect(screen.queryByText("Alpha")).not.toBeInTheDocument();
  });

  it("calls onAdd(definition) when an existing definition is picked", async () => {
    const defs = [buildPropertyDefinition({ id: 7, name: "Priority" })];
    mockDefinitions(defs);
    const onAdd = vi.fn();
    renderWithProviders(
      <AddPropertyButton initiativeId={7} currentPropertyIds={[]} onAdd={onAdd} />
    );
    await userEvent.click(screen.getByRole("button", { name: /Add property/i }));
    const item = await screen.findByText("Priority");
    await userEvent.click(item);
    expect(onAdd).toHaveBeenCalledTimes(1);
    expect(onAdd).toHaveBeenCalledWith(expect.objectContaining({ id: 7, name: "Priority" }));
  });

  it("filters the list case-insensitively by the search input", async () => {
    mockDefinitions([
      buildPropertyDefinition({ id: 1, name: "Alpha" }),
      buildPropertyDefinition({ id: 2, name: "Beta" }),
    ]);
    renderWithProviders(
      <AddPropertyButton initiativeId={7} currentPropertyIds={[]} onAdd={vi.fn()} />
    );
    await userEvent.click(screen.getByRole("button", { name: /Add property/i }));
    const searchInput = await screen.findByPlaceholderText(/Search properties/i);
    await userEvent.type(searchInput, "BET");
    await waitFor(() => {
      expect(screen.getByText("Beta")).toBeInTheDocument();
      expect(screen.queryByText("Alpha")).not.toBeInTheDocument();
    });
  });

  it("creates a new property via the mutation and calls onAdd with the returned definition", async () => {
    mockDefinitions([]);

    const bodies: unknown[] = [];
    server.use(
      communityHttp.post("/property-definitions/", async ({ request }) => {
        const body = await request.json();
        bodies.push(body);
        return HttpResponse.json(
          buildPropertyDefinition({
            id: 99,
            name: (body as { name: string }).name,
            type: (body as { type: MetadataType }).type,
          })
        );
      })
    );

    const onAdd = vi.fn();
    renderWithProviders(
      <AddPropertyButton initiativeId={7} currentPropertyIds={[]} onAdd={onAdd} />
    );

    await userEvent.click(screen.getByRole("button", { name: /Add property/i }));
    // "Create new property" entry in the command list.
    const createEntry = await screen.findByText(/Create new property/i);
    await userEvent.click(createEntry);

    // Fill in the name.
    const nameInput = await screen.findByLabelText(/^Name$/);
    await userEvent.type(nameInput, "Quarter");
    // Default type is text, so submit directly.
    const submit = screen.getByRole("button", { name: "Create" });
    await userEvent.click(submit);

    await waitFor(() => {
      expect(bodies).toHaveLength(1);
    });
    expect(bodies[0]).toEqual(
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
    mockDefinitions([]);
    renderWithProviders(
      <AddPropertyButton initiativeId={7} currentPropertyIds={[]} onAdd={vi.fn()} disabled />
    );
    expect(screen.getByRole("button", { name: /Add property/i })).toBeDisabled();
  });
});
