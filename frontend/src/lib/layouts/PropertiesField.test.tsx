import type { QueryClient } from "@tanstack/react-query";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { buildPropertyDefinition, buildPropertySummary } from "@/__tests__/factories/properties";
import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderWithProviders } from "@/__tests__/helpers/render";
import {
  MetadataType,
  type PropertySummary,
  PropertyTarget,
  Tool,
} from "@/api/generated/initiativeAPI.schemas";
import { propertySaves } from "@/hooks/useProperties";

import { PropertiesField } from "./fieldEditors";

const status = buildPropertySummary({
  property_id: 1,
  name: "Status",
  type: MetadataType.text,
  value: "open",
});
const owner = buildPropertySummary({
  property_id: 2,
  name: "Owner",
  type: MetadataType.text,
  value: "Ada",
});

/** Each write to the row's properties, as sent; answered with what the row
 *  then holds. */
const writes = (answer: PropertySummary[] = []) => {
  const sent: Record<string, unknown>[] = [];
  server.use(
    communityHttp.put("/properties/:target/:entityId", async ({ request, params }) => {
      const body = (await request.json()) as Record<string, unknown>;
      sent.push({ ...body, at: `${params.target}/${params.entityId}` });
      return HttpResponse.json(answer);
    })
  );
  return sent;
};

const panel = (saved: PropertySummary[], readOnly = false, queryClient?: QueryClient) =>
  renderWithProviders(
    <PropertiesField
      kind={propertySaves[PropertyTarget.file]}
      id={10}
      properties={saved}
      readOnly={readOnly}
      initiativeId={1}
      canOpen={{ tool: Tool.file, id: 10 }}
    />,
    { queryClient }
  );

describe("a row's properties, saved one at a time", () => {
  it("saves the one value changed, leaving the others as they are", async () => {
    const sent = writes([{ ...status, value: "closed" }, owner]);
    panel([status, owner]);
    const user = userEvent.setup();

    const input = screen.getByDisplayValue("open");
    await user.clear(input);
    await user.type(input, "closed{Enter}");

    await waitFor(() =>
      expect(sent).toEqual([
        { at: "file/10", merge: true, values: [{ property_id: 1, value: "closed" }] },
      ])
    );
    expect(await screen.findByDisplayValue("closed")).toBeInTheDocument();
    expect(screen.getByDisplayValue("Ada")).toBeInTheDocument();
  });

  it("keeps an answer when opened again on the read it was answered over", async () => {
    writes([{ ...status, value: "closed" }, owner]);
    const saved = [status, owner];
    const first = panel(saved);
    const user = userEvent.setup();
    const input = screen.getByDisplayValue("open");
    await user.clear(input);
    await user.type(input, "closed{Enter}");
    await screen.findByDisplayValue("closed");

    // A dialog closed and opened again on the copy it held.
    first.unmount();
    panel(saved, false, first.queryClient);

    expect(await screen.findByDisplayValue("closed")).toBeInTheDocument();
  });

  it("sends a change still being typed when it is left", async () => {
    const sent = writes();
    const { unmount } = panel([status, owner]);
    const user = userEvent.setup();
    const input = screen.getByDisplayValue("open");
    await user.clear(input);
    await user.type(input, "closed");

    unmount();

    await waitFor(() =>
      expect(sent).toEqual([
        { at: "file/10", merge: true, values: [{ property_id: 1, value: "closed" }] },
      ])
    );
  });

  it("offers no retry of one row's failed addition once it shows another", async () => {
    server.use(
      communityHttp.get("/property-definitions/", () =>
        HttpResponse.json([buildPropertyDefinition({ id: 3, name: "Size" })])
      ),
      communityHttp.put(
        "/properties/:target/:entityId",
        () => new HttpResponse(null, { status: 500 })
      )
    );
    const { rerender } = panel([status, owner]);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /add metadata/i }));
    await user.click(await screen.findByRole("option", { name: /size/i }));
    expect(await screen.findByRole("button", { name: /try again/i })).toBeInTheDocument();

    // The panel moves to another row: its Retry would add Size there.
    rerender(
      <PropertiesField
        kind={propertySaves[PropertyTarget.file]}
        id={11}
        properties={[{ ...status, value: "draft" }]}
        readOnly={false}
        initiativeId={1}
        canOpen={{ tool: Tool.file, id: 11 }}
      />
    );

    expect(await screen.findByDisplayValue("draft")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /try again/i })).not.toBeInTheDocument();
  });

  it("takes a property off the row by itself", async () => {
    const sent = writes();
    panel([status, owner]);

    await userEvent.click(
      within(screen.getByRole("group", { name: "Owner" })).getByRole("button", { name: /remove/i })
    );

    await waitFor(() =>
      expect(sent).toEqual([{ at: "file/10", merge: true, values: [], removed: [2] }])
    );
  });

  it("shows a reader the values, with nothing to change them with", () => {
    panel([status, owner], true);

    expect(screen.getByText("open")).toBeInTheDocument();
    expect(screen.getByText("Ada")).toBeInTheDocument();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /remove/i })).not.toBeInTheDocument();
  });

  it("lists the row's own values, not a collection's metadata or a plug-in's", () => {
    panel(
      [
        status,
        buildPropertySummary({ name: "Caption", collection_id: 5, value: "Dusk" }),
        buildPropertySummary({ name: "Build", install_id: 3, key: "ci.state", value: "green" }),
      ],
      true
    );

    expect(screen.getByText("open")).toBeInTheDocument();
    expect(screen.queryByText("Dusk")).not.toBeInTheDocument();
    expect(screen.queryByText("green")).not.toBeInTheDocument();
  });

  it("names a task's panel for its project's metadata as well", () => {
    renderWithProviders(
      <PropertiesField
        kind={propertySaves[PropertyTarget.task]}
        id={10}
        properties={[]}
        readOnly
        initiativeId={1}
        owner={{ kind: "project", id: 3 }}
      />
    );

    expect(screen.getByText("Properties and metadata")).toBeInTheDocument();
    expect(screen.getByText("No properties or metadata")).toBeInTheDocument();
  });
});
