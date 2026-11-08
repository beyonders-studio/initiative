/**
 * The operator's sign-in placement page: one card per provider with the rules
 * written on it, and the owner's switch that applies them to every community.
 */

import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http, type PathParams } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { buildUser } from "@/__tests__/factories";
import { server } from "@/__tests__/helpers/msw-server";
import { renderWithProviders } from "@/__tests__/helpers/render";
import type {
  ProviderPlacementResponse,
  ProviderPlacementRuleRead,
} from "@/api/generated/initiativeAPI.schemas";

vi.mock("@/lib/mascotToast", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import { queryClient } from "@/lib/queryClient";

import { OperatorDashboardPlacementPage } from "./OperatorDashboardPlacementPage";

const PLACEMENT_URL = "/api/v1/settings/placement/";
const REQUESTS_URL = "/api/v1/settings/placement/requests";

const rule = (overrides: Partial<ProviderPlacementRuleRead> = {}): ProviderPlacementRuleRead => ({
  id: 1,
  provider_id: 11,
  provider_display_name: "Entra",
  provider_icon: null,
  claim_value: "eng",
  scope_claim: null,
  scope_value: null,
  community_id: 7,
  community_name: "Engineering",
  community_role: "member",
  initiative_id: null,
  initiative_name: null,
  initiative_role_id: null,
  initiative_role_name: null,
  applies: true,
  ...overrides,
});

let placement: ProviderPlacementResponse;

const servePlacement = () => {
  server.use(
    http.get(PLACEMENT_URL, () => HttpResponse.json(placement)),
    http.get(REQUESTS_URL, () => HttpResponse.json([]))
  );
};

// The placement hooks refresh through the app's own client, as the app does.
const renderPage = (role: "owner" | "operator" = "owner") =>
  renderWithProviders(<OperatorDashboardPlacementPage />, {
    auth: { user: buildUser({ role }) },
    queryClient,
  });

afterEach(() => queryClient.clear());

const everywhereSwitch = () =>
  screen.getByRole("switch", { name: /apply placement rules to every community/i });

describe("OperatorDashboardPlacementPage", () => {
  beforeEach(() => {
    placement = {
      placement_everywhere: false,
      providers: [
        { id: 11, display_name: "Entra", icon: null, reports_groups: true },
        { id: 21, display_name: "Keycloak", icon: null, reports_groups: false },
      ],
      rules: [
        rule(),
        rule({
          id: 2,
          claim_value: "eng-leads",
          initiative_id: 3,
          initiative_name: "Roadmap",
          initiative_role_id: 30,
          initiative_role_name: "Project Manager",
        }),
        rule({
          id: 3,
          provider_id: 21,
          provider_display_name: "Keycloak",
          claim_value: null,
          scope_claim: "idp",
          scope_value: "acme-adfs",
          community_id: 8,
          community_name: "Partners",
          community_role: "admin",
          applies: false,
        }),
      ],
    };
    servePlacement();
  });

  it("lists each provider with the rules written on it", async () => {
    renderPage();

    expect(await screen.findByText("Group eng")).toBeInTheDocument();
    expect(screen.getByText("Joins Engineering as a member")).toBeInTheDocument();
    expect(
      screen.getByText("Joins Engineering as a member, and Roadmap as Project Manager")
    ).toBeInTheDocument();
    expect(screen.getByText("Everybody from idp = acme-adfs")).toBeInTheDocument();
    expect(screen.getByText("Joins Partners as an admin")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add a rule for Entra" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add a rule for Keycloak" })).toBeInTheDocument();
  });

  it("marks only the rule that is not applying", async () => {
    renderPage();

    await screen.findByText("Everybody from idp = acme-adfs");
    expect(screen.getAllByText("Not applying")).toHaveLength(1);
    const partnersRow = screen.getByText("Joins Partners as an admin").closest("li");
    expect(partnersRow).not.toBeNull();
    expect(within(partnersRow as HTMLElement).getByText("Not applying")).toBeInTheDocument();
  });

  it("notes a provider that reports no groups", async () => {
    renderPage();

    expect(await screen.findByText(/this provider reports no groups yet/i)).toBeInTheDocument();
    // Only Keycloak lacks a groups claim.
    expect(screen.getAllByText(/this provider reports no groups yet/i)).toHaveLength(1);
  });

  it("shows the switch to an operator, disabled, with the owner's note", async () => {
    renderPage("operator");

    await screen.findByText("Group eng");
    expect(everywhereSwitch()).toBeDisabled();
    expect(screen.getByText(/the platform owner sets this/i)).toBeInTheDocument();
  });

  it("asks an owner to confirm before applying the rules everywhere", async () => {
    const user = userEvent.setup();
    let sent: unknown = null;
    server.use(
      http.put("/api/v1/settings/placement/everywhere", async ({ request }) => {
        sent = await request.json();
        return HttpResponse.json({ enabled: true });
      })
    );
    renderPage();

    await screen.findByText("Group eng");
    expect(everywhereSwitch()).toBeEnabled();
    await user.click(everywhereSwitch());

    // Nothing is sent until the dialog is confirmed.
    expect(
      await screen.findByText("Apply placement rules to every community?")
    ).toBeInTheDocument();
    expect(sent).toBeNull();

    await user.click(screen.getByRole("button", { name: "Apply everywhere" }));
    await waitFor(() => expect(sent).toEqual({ enabled: true }));
  });

  it("deletes a rule once confirmed", async () => {
    const user = userEvent.setup();
    let deleted: string | null = null;
    server.use(
      http.delete("/api/v1/settings/placement/rules/:ruleId", ({ params }) => {
        deleted = String(params.ruleId);
        return new HttpResponse(null, { status: 204 });
      })
    );
    renderPage();

    const row = (await screen.findByText("Joins Partners as an admin")).closest("li");
    await user.click(within(row as HTMLElement).getByRole("button", { name: "Delete rule" }));
    expect(await screen.findByText("Delete this rule?")).toBeInTheDocument();
    expect(deleted).toBeNull();

    await user.click(screen.getByRole("button", { name: "Delete rule" }));
    await waitFor(() => expect(deleted).toBe("3"));
  });

  it("lists the communities waiting for an answer, and agrees to one", async () => {
    const user = userEvent.setup();
    let waiting = [
      {
        connection_id: 41,
        community_id: 7,
        community_name: "Engineering",
        provider_display_name: "Google",
        claim: "hd",
        claim_values: ["acme.com"],
        auto_join: true,
        agreed: false,
      },
    ];
    let sent: { agreed: boolean } | null = null;
    server.use(
      http.get(REQUESTS_URL, () => HttpResponse.json(waiting)),
      http.put<PathParams, { agreed: boolean }>(
        "/api/v1/settings/communities/7/narrowings/41",
        async ({ request }) => {
          sent = await request.json();
          waiting = [];
          return HttpResponse.json({ ...sent, connection_id: 41 });
        }
      )
    );
    renderPage("operator");

    expect(await screen.findByText("Waiting for an answer")).toBeInTheDocument();
    expect(screen.getByText("Google: hd is acme.com")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Agree" }));

    await waitFor(() => expect(sent).toEqual({ agreed: true }));
    await waitFor(() => expect(screen.queryByText("Waiting for an answer")).toBeNull());
  });
});
