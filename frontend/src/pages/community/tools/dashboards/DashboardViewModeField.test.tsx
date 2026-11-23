/**
 * "Run dashboard as": Initiative is only offered to someone allowed to choose
 * it, and anyone who can edit may go back to Individual.
 */
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { writerCan } from "@/__tests__/factories/can";
import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderWithProviders } from "@/__tests__/helpers/render";
import type { DashboardRead } from "@/api/generated/initiativeAPI.schemas";

import { DashboardViewModeField } from "./DashboardViewModeField";

const dashboard = (overrides: Partial<DashboardRead> = {}) =>
  ({
    id: 3,
    name: "Sprint health",
    view_mode: "individual",
    can_run_as_initiative: true,
    can: writerCan(),
    ...overrides,
  }) as DashboardRead;

describe("DashboardViewModeField", () => {
  it("switches to Initiative for someone allowed to", async () => {
    let sent: unknown = null;
    server.use(
      communityHttp.put("/dashboards/:id/view-mode", async ({ request }) => {
        sent = await request.json();
        return HttpResponse.json(dashboard({ view_mode: "initiative" }));
      })
    );
    renderWithProviders(<DashboardViewModeField dashboard={dashboard()} />);
    const user = userEvent.setup();
    await user.click(screen.getByRole("combobox", { name: /run dashboard as/i }));
    await user.click(await screen.findByRole("option", { name: /^initiative$/i }));
    await waitFor(() => expect(sent).toEqual({ mode: "initiative" }));
  });

  it("does not offer Initiative to someone who may not choose it", async () => {
    renderWithProviders(
      <DashboardViewModeField dashboard={dashboard({ can_run_as_initiative: false })} />
    );
    expect(screen.getByText(/your role can't run dashboards as initiative/i)).toBeInTheDocument();
    const user = userEvent.setup();
    await user.click(screen.getByRole("combobox", { name: /run dashboard as/i }));
    expect(await screen.findByRole("option", { name: /^initiative$/i })).toHaveAttribute(
      "aria-disabled",
      "true"
    );
  });

  it("warns while it runs as the initiative", () => {
    renderWithProviders(
      <DashboardViewModeField dashboard={dashboard({ view_mode: "initiative" })} />
    );
    expect(screen.getByText(/use with caution/i)).toBeInTheDocument();
  });
});
