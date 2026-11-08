/**
 * The filter's two choices: whether every row must match or any may, and
 * whether archived work and templates are left out, included, or all there is. The defaults are switches
 * so "any" never turns them into "archived or not".
 */
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";

import { buildProject, buildTaskType } from "@/__tests__/factories";
import { buildPropertyDefinition } from "@/__tests__/factories/properties";
import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderWithProviders } from "@/__tests__/helpers/render";
import type { FilterFieldSpec, FilterLeaf, FilterNode } from "@/lib/widgets/conditions";

import { FilterBuilder } from "./FilterBuilder";

const ARCHIVED = { field: "archived_at", op: "is_null", value: true } as FilterNode;
const TITLE_A = { field: "title", op: "ilike", value: "a" } as FilterNode;
const TITLE_B = { field: "title", op: "ilike", value: "b" } as FilterNode;

const TITLE: FilterFieldSpec = { field: "title", kind: "text", ops: ["ilike"], multiple: false };

const mount = (
  value: FilterNode[],
  fields: FilterFieldSpec[] = [TITLE],
  defaults: FilterLeaf[] = [ARCHIVED as FilterLeaf]
) => {
  const onChange = vi.fn();
  renderWithProviders(
    <FilterBuilder
      value={value}
      onChange={onChange}
      initiativeId={1}
      fields={fields}
      defaults={defaults}
      loading={false}
    />
  );
  return onChange;
};

describe("FilterBuilder", () => {
  it("reads one OR group as 'any' and keeps the default outside it", async () => {
    mount([ARCHIVED, { logic: "or", conditions: [TITLE_A, TITLE_B] }]);
    expect(await screen.findByRole("combobox", { name: /^archived$/i })).toHaveTextContent(
      /leave out/i
    );
    expect(screen.getByRole("combobox", { name: /match all or any/i })).toHaveTextContent(/any/i);
    expect(screen.getByText(/^or$/i)).toBeInTheDocument();
  });

  it("switches to 'any' by wrapping the rows, not the defaults", async () => {
    const onChange = mount([ARCHIVED, TITLE_A, TITLE_B]);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("combobox", { name: /match all or any/i }));
    await user.click(await screen.findByRole("option", { name: /^any$/i }));
    await waitFor(() =>
      expect(onChange).toHaveBeenLastCalledWith([
        ARCHIVED,
        { logic: "or", conditions: [TITLE_A, TITLE_B] },
      ])
    );
  });

  it("including archived work drops its condition", async () => {
    const onChange = mount([ARCHIVED, TITLE_A]);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("combobox", { name: /^archived$/i }));
    await user.click(await screen.findByRole("option", { name: /^include$/i }));
    expect(onChange).toHaveBeenLastCalledWith([TITLE_A]);
  });

  it("asks for only archived work with the same comparison flipped", async () => {
    const onChange = mount([ARCHIVED, TITLE_A]);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("combobox", { name: /^archived$/i }));
    await user.click(await screen.findByRole("option", { name: /^only$/i }));
    expect(onChange).toHaveBeenLastCalledWith([
      { field: "archived_at", op: "is_null", value: false },
      TITLE_A,
    ]);
  });

  it("reads 'only' back from a stored filter", async () => {
    mount([{ field: "archived_at", op: "is_null", value: false } as FilterNode]);
    expect(await screen.findByRole("combobox", { name: /^archived$/i })).toHaveTextContent(/only/i);
    expect(screen.queryByText(/no filters/i)).not.toBeInTheDocument();
  });

  it("picks a property from the initiative's own", async () => {
    server.use(
      communityHttp.get("/property-definitions/", () =>
        HttpResponse.json([
          buildPropertyDefinition({ id: 7, name: "Points" }),
          buildPropertyDefinition({ id: 8, name: "Sprint" }),
        ])
      )
    );
    mount(
      [{ field: "property_id", op: "in_", value: [7] } as FilterNode],
      [{ field: "property_id", kind: "property", ops: ["in_"], multiple: true }],
      []
    );
    expect(await screen.findByText("Points")).toBeInTheDocument();
  });

  it("picks a type from the initiative's projects, naming whose each is", async () => {
    const garden = buildProject({ id: 3, name: "Garden", initiative_id: 1 });
    const kitchen = buildProject({ id: 4, name: "Kitchen", initiative_id: 1 });
    server.use(
      communityHttp.get("/projects/", () =>
        HttpResponse.json({ items: [garden, kitchen], total_count: 2, has_next: false })
      ),
      communityHttp.get("/projects/:projectId/task-types/", ({ params }) =>
        HttpResponse.json(
          params.projectId === "3"
            ? [buildTaskType({ id: 12, project_id: 3, name: "Bug" })]
            : [buildTaskType({ id: 13, project_id: 4, name: "Recipe" })]
        )
      )
    );
    mount(
      [{ field: "task_type_id", op: "in_", value: [12] } as FilterNode],
      [{ field: "task_type_id", kind: "task_type", ops: ["in_"], multiple: true }],
      []
    );
    expect(await screen.findByText("Bug (Garden)")).toBeInTheDocument();
  });
});
