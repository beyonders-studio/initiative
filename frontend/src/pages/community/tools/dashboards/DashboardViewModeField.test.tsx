/**
 * "Run dashboard as": Initiative is only offered to someone allowed to choose
 * it, and anyone who can edit may go back to Individual.
 */
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { writerCan } from "@/__tests__/factories/can";
import { renderWithProviders } from "@/__tests__/helpers/render";
import type { DashboardRead } from "@/api/generated/initiativeAPI.schemas";

import { DashboardViewModeField } from "./DashboardViewModeField";

const mutate = vi.fn();

vi.mock("@/hooks/useDashboards", () => ({
  useSetDashboardViewMode: () => ({ mutate, isPending: false }),
}));

const dashboard = (overrides: Partial<DashboardRead> = {}) =>
  ({
    id: 3,
    name: "Sprint health",
    view_mode: "individual",
    can_run_as_initiative: true,
    can: writerCan(),
    ...overrides,
  }) as DashboardRead;

beforeEach(() => mutate.mockReset());

describe("DashboardViewModeField", () => {
  it("switches to Initiative for someone allowed to", async () => {
    renderWithProviders(<DashboardViewModeField dashboard={dashboard()} />);
    const user = userEvent.setup();
    await user.click(screen.getByRole("combobox", { name: /run dashboard as/i }));
    await user.click(await screen.findByRole("option", { name: /^initiative$/i }));
    expect(mutate).toHaveBeenCalledWith("initiative");
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
