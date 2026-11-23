/**
 * The platform owner's community-directory switch.
 *
 * The switch reflects the deployment's boot config rather than a settings read
 * of its own, so the interesting part is that the two stay one value: what the
 * page shows is what every other page reads to decide whether to offer the
 * directory.
 */
import { fireEvent, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildUser } from "@/__tests__/factories";
import { renderWithProviders } from "@/__tests__/helpers/render";

const updateMutate = vi.fn();
const config = vi.hoisted(() => ({
  communityDirectory: false,
  ageGate: true,
  defaultDmPolicy: "private" as "private" | "community" | "public",
  directMessages: true,
  retentionDays: 90 as number | null,
  holdDays: 30 as number | null,
  guests: false,
  creation: true,
}));

vi.mock("@/hooks/useAppConfig", () => ({
  useAppConfig: () => ({
    communityDirectoryEnabled: config.communityDirectory,
    communityAgeGateEnabled: config.ageGate,
    directMessagesEnabled: config.directMessages,
    guestsEnabled: config.guests,
    isLoading: false,
  }),
}));

vi.mock("@/hooks/useSettings", () => ({
  useUpdateCommunitySettings: () => ({ mutate: updateMutate, isPending: false }),
  useCommunitySettings: () => ({
    data: {
      community_directory_enabled: config.communityDirectory,
      age_gate_enabled: config.ageGate,
      default_dm_policy: config.defaultDmPolicy,
      direct_messages_enabled: config.directMessages,
      deleted_community_retention_days: config.retentionDays,
      on_hold_community_deletion_days: config.holdDays,
      deleted_account_retention_days: null,
      engagement_ranking_enabled: true,
      guests_enabled: config.guests,
      max_guest_days: 365,
      public_registration_enabled: true,
      community_creation_enabled: config.creation,
      community_creation_daily_limit: 5,
      community_export_cooldown_hours: 48,
    },
  }),
}));

import { CommunityPage } from "./CommunityPage";

const renderPage = (role: "owner" | "operator" = "owner") =>
  renderWithProviders(<CommunityPage />, {
    auth: { user: buildUser({ role }) },
  });

// For every test in the file, so none starts on what another left.
beforeEach(() => {
  updateMutate.mockClear();
  config.communityDirectory = false;
  config.ageGate = true;
  config.defaultDmPolicy = "private";
  config.directMessages = true;
  config.retentionDays = 90;
  config.holdDays = 30;
  config.guests = false;
  config.creation = true;
});

describe("CommunityPage", () => {
  // Each switch writes only its own half beside the directory value: omitting
  // the others is what leaves them as they were (the age gate on, messaging
  // and guests off here), since they are separate decisions on one endpoint.
  it.each([
    ["Run a community directory", {}, { community_directory_enabled: true }],
    [
      "Run a community directory",
      { communityDirectory: true, directMessages: false },
      { community_directory_enabled: false },
    ],
    ["Let communities rank results by engagement", {}, { engagement_ranking_enabled: false }],
    ["Check members' age", { ageGate: false }, { age_gate_enabled: true }],
    ["Let people message each other", { directMessages: false }, { direct_messages_enabled: true }],
    ["Allow guests", {}, { guests_enabled: true }],
    ["Let anyone sign up", {}, { public_registration_enabled: false }],
    ["Let anyone create a community", {}, { community_creation_enabled: false }],
  ] as const)("flips %s without asking (%o)", (label, overrides, patch) => {
    Object.assign(config, overrides);
    renderPage();
    const value = Object.values(patch).at(-1);
    const toggle = screen.getByRole("switch", { name: label, checked: !value });

    fireEvent.click(toggle);

    expect(updateMutate).toHaveBeenCalledWith({
      community_directory_enabled: config.communityDirectory,
      ...patch,
    });
  });

  it("only stops asking once the owner asserts everyone here is an adult", async () => {
    renderPage();
    const ageToggle = screen.getByLabelText("Check members' age");
    expect(ageToggle).toBeChecked();
    fireEvent.click(ageToggle);

    // The switch alone writes nothing — the assertion is the confirmation.
    expect(updateMutate).not.toHaveBeenCalled();

    fireEvent.click(await screen.findByRole("button", { name: "Everyone here is 18 or older" }));

    expect(updateMutate).toHaveBeenCalledWith({
      community_directory_enabled: false,
      age_gate_enabled: false,
    });
  });

  it("only turns messaging off once the owner confirms", async () => {
    renderPage();
    // On, matching a deployment that upgraded into the switch.
    const messagesToggle = screen.getByLabelText("Let people message each other");
    expect(messagesToggle).toBeChecked();
    fireEvent.click(messagesToggle);

    // The switch alone writes nothing: this takes a feature away from
    // everybody using it.
    expect(updateMutate).not.toHaveBeenCalled();

    fireEvent.click(await screen.findByRole("button", { name: "Turn off direct messages" }));

    expect(updateMutate).toHaveBeenCalledWith({
      community_directory_enabled: false,
      direct_messages_enabled: false,
    });
  });

  it("is not offered below the owner tier", () => {
    renderPage("operator");

    expect(screen.queryByLabelText("Run a community directory")).not.toBeInTheDocument();
    expect(
      screen.getByText("You need the platform owner role to run a community directory.")
    ).toBeInTheDocument();
  });
});

/** Open a figure's dialog from its row. */
const change = (rule: string) =>
  userEvent.click(screen.getByRole("button", { name: `Change ${rule}` }));

const save = () => screen.getByRole("button", { name: "Save" });

describe("the policy new accounts start on", () => {
  it("shows what this deployment ships with, and changes it without disturbing the directory switch", async () => {
    config.communityDirectory = true;
    renderPage();

    const policy = screen.getByLabelText("Direct messages for new accounts");
    expect(policy).toHaveTextContent("Private");
    await userEvent.click(policy);
    await userEvent.click(await screen.findByRole("option", { name: "My communities" }));

    // The directory value is carried through: the endpoint takes it on every
    // write, and this control is not a decision about it.
    expect(updateMutate).toHaveBeenCalledWith({
      community_directory_enabled: true,
      default_dm_policy: "community",
    });
  });
});

describe("the figures", () => {
  it.each([
    [
      "Keeping deleted communities",
      "Keep communities for (days)",
      {},
      "90 days",
      "90",
      "30",
      { deleted_community_retention_days: 30 },
    ],
    // A blank box is never destroy.
    [
      "Keeping deleted communities",
      "Keep communities for (days)",
      {},
      "90 days",
      "90",
      "",
      { deleted_community_retention_days: null },
    ],
    [
      "Deleting communities on hold",
      "Delete after (days on hold)",
      {},
      "30 days",
      "30",
      "60",
      { on_hold_community_deletion_days: 60 },
    ],
    // A blank box is never delete.
    [
      "Deleting communities on hold",
      "Delete after (days on hold)",
      {},
      "30 days",
      "30",
      "",
      { on_hold_community_deletion_days: null },
    ],
    [
      "Longest guest stay",
      "Longest a guest may stay (days)",
      { guests: true },
      "365 days",
      "365",
      "30",
      { max_guest_days: 30 },
    ],
    // 0 is no daily limit.
    [
      "Daily limit per account",
      "Communities one account may create per day",
      {},
      "5 communities a day",
      "5",
      "0",
      { community_creation_daily_limit: 0 },
    ],
    [
      "Time between exports",
      "Hours between community exports",
      {},
      "48 hours",
      "48",
      "24",
      { community_export_cooldown_hours: 24 },
    ],
  ] as const)(
    "saves %s from its box %s",
    async (rule, label, overrides, shown, start, typed, patch) => {
      Object.assign(config, overrides);
      renderPage();
      expect(screen.getByText(shown)).toBeInTheDocument();

      await change(rule);
      const box = screen.getByLabelText(label) as HTMLInputElement;
      expect(box.value).toBe(start);

      await userEvent.clear(box);
      if (typed) await userEvent.type(box, typed);
      await userEvent.click(save());

      expect(updateMutate).toHaveBeenCalledWith({ community_directory_enabled: false, ...patch });
    }
  );

  it("shows a blank box where the deployment keeps deleted communities", async () => {
    config.retentionDays = null;
    renderPage();
    expect(screen.getByText("Never destroy")).toBeInTheDocument();

    await change("Keeping deleted communities");
    const box = screen.getByLabelText("Keep communities for (days)") as HTMLInputElement;
    expect(box.value).toBe("");
    // Nothing to save until it is changed.
    expect(save()).toBeDisabled();
  });

  it("will not save a blank time between exports", async () => {
    renderPage();

    await change("Time between exports");
    await userEvent.clear(screen.getByLabelText("Hours between community exports"));

    expect(save()).toBeDisabled();
  });

  it.each([
    [
      { directMessages: false },
      "Private",
      /used once direct messages are on/,
      () => screen.queryByLabelText("Direct messages for new accounts"),
    ],
    [
      {},
      "365 days",
      /used once guests are allowed/,
      () => screen.queryByRole("button", { name: "Change Longest guest stay" }),
    ],
    [
      { creation: false },
      "5 communities a day",
      /used once anyone can create a community/,
      () => screen.queryByRole("button", { name: "Change Daily limit per account" }),
    ],
  ])(
    "states a figure whose switch is off, rather than offering it (%o)",
    (overrides, shown, note, control) => {
      Object.assign(config, overrides);
      renderPage();

      expect(screen.getByText(shown)).toBeInTheDocument();
      expect(screen.getByText(note)).toBeInTheDocument();
      expect(control()).toBeNull();
    }
  );
});
