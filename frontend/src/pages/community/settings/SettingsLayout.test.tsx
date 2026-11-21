import { screen, within } from "@testing-library/react";
import { HttpResponse } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildCommunity, buildUser, communityCan } from "@/__tests__/factories";
import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";
import {
  AdminSurface,
  type CommunityAuthOption,
  type CommunityBillingSummaryRead,
  type CommunityRole,
} from "@/api/generated/initiativeAPI.schemas";
import type { useAppConfig as useAppConfigType } from "@/hooks/useAppConfig";
import type { CommunityEntry } from "@/hooks/useCommunities";
import type { useCommunityBillingSummary as useCommunityBillingSummaryType } from "@/hooks/useCommunityBillingSummary";

// What this member is in this community, and what the operator has granted it.
// Flipped per test.
let communityRole: CommunityRole = "superadmin";
let grantSettingsLevel: "admin" | "superadmin" | null = null;
let reachesContent = true;
let authOptions: CommunityAuthOption[] = ["restrictions", "providers"];
// The server's answer to whether the settings may be changed; left unset, the
// factory answers the way the server does for a member.
let canWriteSettings: boolean | undefined;
// The deployment's billing portal; null on a self-hosted install.
let billing: { url: string } | null = null;
// Whether the deployment allows guests, and how many this community takes.
let guestsEnabled = true;
let maxGuests: number | null = null;

// What the billing service said of the plan; undefined is "not asked".
let summary: CommunityBillingSummaryRead | undefined;
// What the server says this member holds; null leaves it unanswered, so the
// rung answers.
let held: AdminSurface[] | null = null;

vi.mock(import("@/hooks/useAppConfig"), async (importOriginal) => ({
  ...(await importOriginal()),
  useAppConfig: () =>
    ({ billing, guestsEnabled }) as unknown as ReturnType<typeof useAppConfigType>,
}));
vi.mock(import("@/hooks/useCommunityBillingSummary"), () => ({
  useCommunityBillingSummary: () =>
    ({ data: summary }) as unknown as ReturnType<typeof useCommunityBillingSummaryType>,
}));

import { SettingsLayout } from "./SettingsLayout";

const render = () => {
  const activeCommunity: CommunityEntry = {
    ...buildCommunity({
      id: 4,
      role: communityRole,
      auth_options: authOptions,
      max_guests: maxGuests,
      can: communityCan(communityRole, {
        content: reachesContent,
        ...(canWriteSettings === undefined ? {} : { configure: canWriteSettings }),
      }),
    }),
    grantSettingsLevel,
  };
  return renderPage(SettingsLayout, {
    auth: { user: buildUser() },
    communities: { communities: [activeCommunity], activeCommunity, activeCommunityId: 4 },
  });
};

describe("SettingsLayout", () => {
  beforeEach(() => {
    communityRole = "superadmin";
    grantSettingsLevel = null;
    reachesContent = true;
    authOptions = ["restrictions", "providers"];
    canWriteSettings = undefined;
    billing = null;
    guestsEnabled = true;
    maxGuests = null;
    summary = undefined;
    held = null;
    server.use(
      communityHttp.get("/custom-roles/held", () =>
        held === null
          ? HttpResponse.json({ detail: "NOT_FOUND" }, { status: 404 })
          : HttpResponse.json({ surfaces: held })
      )
    );
  });

  it("gives an admin the tabs an admin has always had, and Roles after Users", async () => {
    communityRole = "admin";
    held = Object.values(AdminSurface);
    render();

    await screen.findByRole("tab", { name: "Community" });
    expect(screen.getAllByRole("tab").map((tab) => tab.textContent)).toEqual([
      "Community",
      "Users",
      "Roles",
      "Guests",
      "Initiatives",
      "Trash",
    ]);
  });

  it("gives a member holding invites the Users tab and nothing else", async () => {
    communityRole = "member";
    held = ["invites"];
    render();

    await screen.findByRole("tab", { name: "Users" });
    // Guest invites can open any initiative, which takes the admin rung.
    expect(screen.getAllByRole("tab").map((tab) => tab.textContent)).toEqual(["Users"]);
    // What they hold, they may change.
    expect(screen.getByRole("group")).toBeEnabled();
  });

  it("narrows an admin to what their custom role holds", async () => {
    communityRole = "admin";
    held = ["profile", "trash"];
    render();

    await screen.findByRole("tab", { name: "Community" });
    expect(screen.getAllByRole("tab").map((tab) => tab.textContent)).toEqual([
      "Community",
      "Trash",
    ]);
  });

  it.each([
    ["the server does not allow guests", false, null],
    ["the community takes none", true, 0],
  ])("hides Guests where %s", async (_label, enabled, max) => {
    guestsEnabled = enabled;
    maxGuests = max;
    render();

    expect(await screen.findByRole("tab", { name: /users/i })).toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "Guests" })).not.toBeInTheDocument();
  });

  it("puts Usage first for the seat, with Security, Integrations and Data", async () => {
    // What the community uses against its caps, its sign-in, what it hands to
    // somebody outside it and taking it out in one file are all the seat's. An
    // ordinary admin's bar (the first test) has none of them.
    render();
    const tabs = await screen.findAllByRole("tab");
    expect(tabs[0]).toHaveAccessibleName("Usage");
    expect(screen.getByRole("tab", { name: /security/i })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /integrations/i })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /data/i })).toBeInTheDocument();
  });

  it("names it for the plan where there is a billing portal", async () => {
    billing = { url: "https://billing.example.com" };
    render();
    const tabs = await screen.findAllByRole("tab");
    expect(tabs[0]).toHaveAccessibleName("Plan & usage");
  });

  it("marks the tab while a trial runs", async () => {
    billing = { url: "https://billing.example.com" };
    const now = new Date();
    const end = new Date(now.getFullYear(), now.getMonth(), now.getDate() + 3);
    const pad = (n: number) => String(n).padStart(2, "0");
    summary = {
      available: true,
      trial_ends_on: `${end.getFullYear()}-${pad(end.getMonth() + 1)}-${pad(end.getDate())}`,
      payment_failed: false,
    };
    render();
    expect(await screen.findByRole("tab", { name: /plan & usage/i })).toHaveTextContent(
      "Trial · 3 days"
    );
  });

  it("marks the tab when a payment failed", async () => {
    billing = { url: "https://billing.example.com" };
    summary = { available: true, payment_failed: true };
    render();
    const tab = await screen.findByRole("tab", { name: /plan & usage/i });
    expect(within(tab).getByRole("img", { name: "Payment failed" })).toBeInTheDocument();
  });

  it("leaves the tab plain when billing could not say", async () => {
    billing = { url: "https://billing.example.com" };
    summary = { available: false, payment_failed: false };
    render();
    const tab = await screen.findByRole("tab", { name: /plan & usage/i });
    expect(tab).toHaveAccessibleName("Plan & usage");
  });

  it.each<[CommunityAuthOption[], boolean]>([
    [["providers"], true],
    [["restrictions"], true],
    [[], false],
  ])("offers the seat Security on the grants %j: %s", async (options, offered) => {
    // The two grants are independent, and either one puts something on the
    // page worth reaching; with neither there is nothing on it for anybody.
    authOptions = options;
    render();

    expect(await screen.findByRole("tab", { name: /community/i })).toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: /security/i }) !== null).toBe(offered);
  });

  it("gives a superadmin settings grantee every tab the seat holds", async () => {
    // The rung is "what the seat holds", and the seat sits above admin — so
    // the community's own configuration comes with it, Data and the danger
    // zone included. The entry carries the rung the server recorded on the
    // grant, which is what the seat is read from.
    communityRole = "superadmin";
    grantSettingsLevel = "superadmin";
    // A grantee's entry carries none of the community's own options; the page
    // reads the real ones for itself.
    authOptions = [];
    render();

    expect(await screen.findByRole("tab", { name: /security/i })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /integrations/i })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /community/i })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /users/i })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /data/i })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /danger/i })).toBeInTheDocument();
    expect(screen.queryByText(/permission/i)).not.toBeInTheDocument();
  });

  it("gives an admin settings grantee what an admin administers, and no more", async () => {
    communityRole = "admin";
    grantSettingsLevel = "admin";
    render();

    expect(await screen.findByRole("tab", { name: /community/i })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /users/i })).toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: /security/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: /integrations/i })).not.toBeInTheDocument();
    expect(screen.queryByText(/permission/i)).not.toBeInTheDocument();
  });

  it("drops the content-backed tabs from a settings-only grant", async () => {
    // Initiatives and Trash are built on routes the server refuses to a grant
    // carrying no content level, so they are not offered.
    communityRole = "superadmin";
    grantSettingsLevel = "superadmin";
    reachesContent = false;
    render();

    expect(await screen.findByRole("tab", { name: /community/i })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /security/i })).toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: /initiatives/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: /trash/i })).not.toBeInTheDocument();
  });

  it.each([false, true])(
    "lets a superadmin grantee change the settings only when the server says so (%s)",
    async (writes) => {
      // A settings grant with no read/write grant beside it reads what its rung
      // reaches; every control on the pages is disabled, and the page says why.
      grantSettingsLevel = "superadmin";
      canWriteSettings = writes;
      render();

      expect(await screen.findByRole("tab", { name: /security/i })).toBeInTheDocument();
      expect(screen.queryByText(/read\/write grant/i) === null).toBe(writes);
      expect(screen.getByRole("group").matches(":disabled")).toBe(!writes);
    }
  );

  it("turns a member with nothing away", async () => {
    communityRole = "member";
    held = [];
    render();

    expect(await screen.findByText(/permission/i)).toBeInTheDocument();
  });
});
