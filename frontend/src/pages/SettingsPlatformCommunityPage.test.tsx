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

import { SettingsPlatformCommunityPage } from "./SettingsPlatformCommunityPage";

const renderPage = (role: "owner" | "operator" = "owner") =>
  renderWithProviders(<SettingsPlatformCommunityPage />, {
    auth: { user: buildUser({ role }) },
  });

const toggle = () => screen.getByLabelText("Run a community directory");

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

describe("SettingsPlatformCommunityPage", () => {
  it("starts off, matching a deployment that has never turned it on", async () => {
    renderPage();

    expect(await screen.findByLabelText("Run a community directory")).not.toBeChecked();
  });

  it("turns the directory on", async () => {
    renderPage();
    fireEvent.click(await screen.findByLabelText("Run a community directory"));

    expect(updateMutate).toHaveBeenCalledWith({ community_directory_enabled: true });
  });

  it("turns it back off", async () => {
    config.communityDirectory = true;
    renderPage();

    expect(toggle()).toBeChecked();
    fireEvent.click(toggle());

    expect(updateMutate).toHaveBeenCalledWith({ community_directory_enabled: false });
  });

  it("turns engagement ranking off for every community", async () => {
    renderPage();
    const ranking = await screen.findByLabelText("Let communities rank results by engagement");

    expect(ranking).toBeChecked();
    fireEvent.click(ranking);

    expect(updateMutate).toHaveBeenCalledWith({
      community_directory_enabled: false,
      engagement_ranking_enabled: false,
    });
  });

  const ageToggle = () => screen.getByLabelText("Check members' age");

  it("starts asking members their age", async () => {
    renderPage();

    expect(await screen.findByLabelText("Check members' age")).toBeChecked();
  });

  it("only stops asking once the owner asserts everyone here is an adult", async () => {
    renderPage();
    fireEvent.click(ageToggle());

    // The switch alone writes nothing — the assertion is the confirmation.
    expect(updateMutate).not.toHaveBeenCalled();

    fireEvent.click(await screen.findByRole("button", { name: "Everyone here is 18 or older" }));

    expect(updateMutate).toHaveBeenCalledWith({
      community_directory_enabled: false,
      age_gate_enabled: false,
    });
  });

  it("turns the question back on without asking anything", () => {
    config.ageGate = false;
    renderPage();

    expect(ageToggle()).not.toBeChecked();
    fireEvent.click(ageToggle());

    expect(updateMutate).toHaveBeenCalledWith({
      community_directory_enabled: false,
      age_gate_enabled: true,
    });
  });

  it("carries the age gate through a directory toggle unchanged", () => {
    renderPage();
    fireEvent.click(toggle());

    // The directory switch writes only its own half; omitting the other is
    // what leaves the owner's assertion alone.
    expect(updateMutate).toHaveBeenCalledWith({ community_directory_enabled: true });
  });

  const messagesToggle = () => screen.getByLabelText("Let people message each other");

  it("starts on, matching a deployment that upgraded into the switch", async () => {
    renderPage();

    expect(await screen.findByLabelText("Let people message each other")).toBeChecked();
  });

  it("only turns messaging off once the owner confirms", async () => {
    renderPage();
    fireEvent.click(messagesToggle());

    // The switch alone writes nothing: this takes a feature away from
    // everybody using it.
    expect(updateMutate).not.toHaveBeenCalled();

    fireEvent.click(await screen.findByRole("button", { name: "Turn off direct messages" }));

    expect(updateMutate).toHaveBeenCalledWith({
      community_directory_enabled: false,
      direct_messages_enabled: false,
    });
  });

  it("turns messaging back on without asking anything", () => {
    config.directMessages = false;
    renderPage();

    expect(messagesToggle()).not.toBeChecked();
    fireEvent.click(messagesToggle());

    expect(updateMutate).toHaveBeenCalledWith({
      community_directory_enabled: false,
      direct_messages_enabled: true,
    });
  });

  it("leaves messaging alone when the directory is toggled", () => {
    config.directMessages = false;
    renderPage();
    fireEvent.click(toggle());

    // Omitting it is what leaves it as it was; the two are separate decisions
    // on one endpoint.
    expect(updateMutate).toHaveBeenCalledWith({ community_directory_enabled: true });
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
  it("shows what this deployment ships with", async () => {
    renderPage();
    expect(await screen.findByLabelText("Direct messages for new accounts")).toHaveTextContent(
      "Private"
    );
  });

  it("changes it without disturbing the directory switch", async () => {
    config.communityDirectory = true;
    renderPage();

    await userEvent.click(screen.getByLabelText("Direct messages for new accounts"));
    await userEvent.click(await screen.findByRole("option", { name: "My communities" }));

    // The directory value is carried through: the endpoint takes it on every
    // write, and this control is not a decision about it.
    expect(updateMutate).toHaveBeenCalledWith({
      community_directory_enabled: true,
      default_dm_policy: "community",
    });
  });

  it("states the policy while messaging is off, rather than offering it", () => {
    config.directMessages = false;
    renderPage();

    expect(screen.queryByLabelText("Direct messages for new accounts")).not.toBeInTheDocument();
    expect(screen.getByText("Private")).toBeInTheDocument();
    expect(screen.getByText(/used once direct messages are on/)).toBeInTheDocument();
  });
});

describe("how long deleted communities are kept", () => {
  it("shows the deployment's window and saves a new one", async () => {
    config.communityDirectory = true;
    renderPage();
    expect(screen.getByText("90 days")).toBeInTheDocument();

    await change("Keeping deleted communities");
    const box = screen.getByLabelText("Keep communities for (days)") as HTMLInputElement;
    expect(box.value).toBe("90");

    await userEvent.clear(box);
    await userEvent.type(box, "30");
    await userEvent.click(save());

    expect(updateMutate).toHaveBeenCalledWith({
      community_directory_enabled: true,
      deleted_community_retention_days: 30,
    });
  });

  it("takes a blank box as never destroy", async () => {
    renderPage();

    await change("Keeping deleted communities");
    await userEvent.clear(screen.getByLabelText("Keep communities for (days)"));
    await userEvent.click(save());

    expect(updateMutate).toHaveBeenCalledWith({
      community_directory_enabled: false,
      deleted_community_retention_days: null,
    });
  });

  it("shows a blank box where the deployment keeps them", async () => {
    config.retentionDays = null;
    renderPage();
    expect(screen.getByText("Never destroy")).toBeInTheDocument();

    await change("Keeping deleted communities");
    const box = screen.getByLabelText("Keep communities for (days)") as HTMLInputElement;
    expect(box.value).toBe("");
    // Nothing to save until it is changed.
    expect(save()).toBeDisabled();
  });
});

describe("how long communities stay on hold", () => {
  it("shows the deployment's window and saves a new one", async () => {
    renderPage();

    await change("Deleting communities on hold");
    const box = screen.getByLabelText("Delete after (days on hold)") as HTMLInputElement;
    expect(box.value).toBe("30");

    await userEvent.clear(box);
    await userEvent.type(box, "60");
    await userEvent.click(save());

    expect(updateMutate).toHaveBeenCalledWith({
      community_directory_enabled: false,
      on_hold_community_deletion_days: 60,
    });
  });

  it("takes a blank box as never delete", async () => {
    renderPage();

    await change("Deleting communities on hold");
    await userEvent.clear(screen.getByLabelText("Delete after (days on hold)"));
    await userEvent.click(save());

    expect(updateMutate).toHaveBeenCalledWith({
      community_directory_enabled: false,
      on_hold_community_deletion_days: null,
    });
  });
});

describe("guests", () => {
  it("lets communities have guests", async () => {
    renderPage();
    fireEvent.click(await screen.findByLabelText("Allow guests"));

    expect(updateMutate).toHaveBeenCalledWith({
      community_directory_enabled: false,
      guests_enabled: true,
    });
  });

  it("states the longest stay while guests are off, rather than offering it", () => {
    renderPage();

    expect(screen.getByText("365 days")).toBeInTheDocument();
    expect(screen.getByText(/used once guests are allowed/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Change Longest guest stay" })).toBeNull();
  });

  it("saves the longest a guest may stay", async () => {
    config.guests = true;
    renderPage();

    await change("Longest guest stay");
    const box = screen.getByLabelText("Longest a guest may stay (days)") as HTMLInputElement;
    expect(box.value).toBe("365");

    await userEvent.clear(box);
    await userEvent.type(box, "30");
    await userEvent.click(save());

    expect(updateMutate).toHaveBeenCalledWith({
      community_directory_enabled: false,
      max_guest_days: 30,
    });
  });
});

describe("who may join and create", () => {
  it("closes sign-up to people without an invite", async () => {
    renderPage();
    const registration = await screen.findByLabelText("Let anyone sign up");

    expect(registration).toBeChecked();
    fireEvent.click(registration);

    expect(updateMutate).toHaveBeenCalledWith({
      community_directory_enabled: false,
      public_registration_enabled: false,
    });
  });

  it("stops accounts creating communities", async () => {
    renderPage();
    fireEvent.click(await screen.findByLabelText("Let anyone create a community"));

    expect(updateMutate).toHaveBeenCalledWith({
      community_directory_enabled: false,
      community_creation_enabled: false,
    });
  });

  it("saves 0 as no daily limit", async () => {
    renderPage();
    expect(screen.getByText("5 communities a day")).toBeInTheDocument();

    await change("Daily limit per account");
    const box = screen.getByLabelText(
      "Communities one account may create per day"
    ) as HTMLInputElement;
    expect(box.value).toBe("5");

    await userEvent.clear(box);
    await userEvent.type(box, "0");
    await userEvent.click(save());

    expect(updateMutate).toHaveBeenCalledWith({
      community_directory_enabled: false,
      community_creation_daily_limit: 0,
    });
  });

  it("states the daily limit while creation is off, rather than offering it", () => {
    config.creation = false;
    renderPage();

    expect(screen.getByText("5 communities a day")).toBeInTheDocument();
    expect(screen.getByText(/used once anyone can create a community/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Change Daily limit per account" })).toBeNull();
  });
});

describe("the time between community exports", () => {
  it("saves a new wait", async () => {
    renderPage();
    expect(screen.getByText("48 hours")).toBeInTheDocument();

    await change("Time between exports");
    const box = screen.getByLabelText("Hours between community exports") as HTMLInputElement;
    expect(box.value).toBe("48");

    await userEvent.clear(box);
    await userEvent.type(box, "24");
    await userEvent.click(save());

    expect(updateMutate).toHaveBeenCalledWith({
      community_directory_enabled: false,
      community_export_cooldown_hours: 24,
    });
  });

  it("will not save a blank box", async () => {
    renderPage();

    await change("Time between exports");
    await userEvent.clear(screen.getByLabelText("Hours between community exports"));

    expect(save()).toBeDisabled();
  });
});
