/**
 * The owner's intake settings.
 *
 * Two things matter here and neither is cosmetic: nothing below the community
 * picker is offered until a community is named, because every id in it belongs
 * to that community; and a stream that has never been set up offers both ways
 * of setting one up rather than only the blueprint.
 */
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildPage, buildUser } from "@/__tests__/factories";
import { renderWithProviders } from "@/__tests__/helpers/render";

const importMutate = vi.fn();
const upsertMutate = vi.fn();
const deleteMutate = vi.fn();
const communityMutate = vi.fn();
const generalContactMutate = vi.fn();
const streamContactMutate = vi.fn();

const state = vi.hoisted(() => ({
  operationsCommunityId: null as number | null,
  bindings: [] as Array<Record<string, unknown>>,
  isError: false,
  optionsError: false,
  isFetching: false,
  generalContact: null as string | null,
  contactEmails: {} as Record<string, string>,
}));

const unbound = (stream: string) => ({
  stream,
  binding_id: null,
  project_id: null,
  project_name: null,
  initiative_id: null,
  initiative_name: null,
  default_status_id: null,
  default_status_name: null,
  enabled: false,
  last_case_at: null,
  project_archived: false,
});

const STREAMS = ["security", "moderation", "support", "feedback"];

vi.mock("@/hooks/useIntakeSettings", () => ({
  useIntakeSettings: () => ({
    data: state.isError
      ? undefined
      : {
          operations_community_id: state.operationsCommunityId,
          operations_community_name: state.operationsCommunityId ? "Operations" : null,
          bindings: state.bindings,
          general_contact_email: state.generalContact,
          contact_emails: state.contactEmails,
        },
    isLoading: false,
    isFetching: state.isFetching,
    isError: state.isError,
    refetch: vi.fn(),
  }),
  useIntakeOptions: () => ({
    isFetching: false,
    isError: state.optionsError,
    refetch: vi.fn(),
    data: {
      initiatives: [
        {
          id: 7,
          name: "Trust and Safety",
          projects: [
            {
              id: 21,
              name: "Security",
              statuses: [
                { id: 31, name: "Triage" },
                { id: 32, name: "Confirmed" },
              ],
              task_types: [
                { id: 41, name: "Task" },
                { id: 42, name: "Bug" },
              ],
            },
          ],
        },
      ],
    },
  }),
  useUpdateOperationsCommunity: () => ({ mutate: communityMutate, isPending: false }),
  useUpsertIntakeBinding: () => ({ mutate: upsertMutate, isPending: false }),
  useImportIntakeBlueprint: () => ({ mutate: importMutate, isPending: false }),
  useDeleteIntakeBinding: () => ({ mutate: deleteMutate, isPending: false }),
  useUpdateIntakeGeneralContact: () => ({ mutateAsync: generalContactMutate, isPending: false }),
  useUpdateIntakeStreamContact: () => ({ mutateAsync: streamContactMutate, isPending: false }),
  useUpdateFeedbackSwitch: () => ({ mutate: vi.fn(), isPending: false }),
}));

vi.mock("@/hooks/useSettings", () => ({
  usePlatformCommunities: () => ({ data: buildPage([{ id: 3, name: "Operations" }]) }),
}));

import { SettingsIntakePage } from "./SettingsIntakePage";

const renderPage = (role: "owner" | "operator" = "owner") =>
  renderWithProviders(<SettingsIntakePage />, { auth: { user: buildUser({ role }) } });

describe("SettingsIntakePage", () => {
  beforeEach(() => {
    importMutate.mockClear();
    upsertMutate.mockClear();
    deleteMutate.mockClear();
    communityMutate.mockClear();
    generalContactMutate.mockReset().mockResolvedValue({});
    streamContactMutate.mockReset().mockResolvedValue({});
    state.generalContact = null;
    state.contactEmails = {};
    state.operationsCommunityId = null;
    state.bindings = STREAMS.map(unbound);
    state.isError = false;
    state.optionsError = false;
    state.isFetching = false;
  });

  it("offers nothing to bind until a community is named", () => {
    renderPage();
    expect(
      screen.getByText("Choose a community above, then say where each stream lands.")
    ).toBeInTheDocument();
    expect(screen.queryByText("Set this up for me")).not.toBeInTheDocument();
  });

  it("lists every stream once a community is named, bound or not", () => {
    state.operationsCommunityId = 3;
    renderPage();
    for (const title of ["Security", "Moderation", "Support", "Feedback"]) {
      expect(screen.getByRole("region", { name: title })).toBeInTheDocument();
    }
    expect(screen.getAllByText("Not set up")).toHaveLength(STREAMS.length);
  });

  it("sets a stream up from its blueprint", async () => {
    state.operationsCommunityId = 3;
    renderPage();
    const user = userEvent.setup();

    // Each stream's card is a region named after the stream, so "the security
    // one" is unambiguous without reaching into the DOM.
    const card = screen.getByRole("region", { name: "Security" });
    const setUp = () => within(card).getByRole("button", { name: "Set this up for me" });

    // Disabled until an initiative is chosen: the import has to land somewhere.
    expect(setUp()).toBeDisabled();
    await user.click(within(card).getByRole("combobox", { name: "Initiative" }));
    await user.click(await screen.findByRole("option", { name: "Trust and Safety" }));
    await user.click(setUp());

    expect(importMutate).toHaveBeenCalledWith({ stream: "security", initiativeId: 7 });
  });

  it("shows where a bound stream lands and when it last opened a case", () => {
    state.operationsCommunityId = 3;
    state.bindings = [
      {
        ...unbound("security"),
        binding_id: 1,
        project_id: 21,
        project_name: "Security",
        initiative_id: 7,
        initiative_name: "Trust and Safety",
        default_status_id: 31,
        default_status_name: "Triage",
        enabled: true,
        last_case_at: "2026-09-15T10:00:00Z",
      },
      ...STREAMS.slice(1).map(unbound),
    ];
    renderPage();

    expect(screen.getByText("Receiving")).toBeInTheDocument();
    expect(screen.getByText(/Last case opened/)).toBeInTheDocument();
  });

  it("files a stream's cases as the type chosen, or the project's default", async () => {
    state.operationsCommunityId = 3;
    state.bindings = [
      {
        ...unbound("security"),
        binding_id: 1,
        project_id: 21,
        project_name: "Security",
        initiative_id: 7,
        initiative_name: "Trust and Safety",
        enabled: true,
      },
      ...STREAMS.slice(1).map(unbound),
    ];
    renderPage();
    const user = userEvent.setup();
    const card = screen.getByRole("region", { name: "Security" });
    const picker = within(card).getByRole("combobox", { name: "New cases are" });

    expect(picker).toHaveTextContent("The project's default type");
    await user.click(picker);
    await user.click(await screen.findByRole("option", { name: "Bug" }));

    expect(upsertMutate).toHaveBeenCalledWith({
      stream: "security",
      body: expect.objectContaining({ project_id: 21, task_type_id: 42 }),
    });
  });

  it("tells a non-owner this is not theirs to configure", () => {
    renderPage("operator");
    expect(
      screen.getByText("Only platform owners can configure where operations work lands.")
    ).toBeInTheDocument();
  });

  it("says the read failed rather than showing an unconfigured deployment", () => {
    // The page shows the failure and withholds the picker, so a change is only
    // made against a value that was actually read.
    state.isError = true;
    state.operationsCommunityId = 3;
    renderPage();

    expect(screen.getByText("Could not load these settings")).toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: "Community" })).not.toBeInTheDocument();
    expect(
      screen.queryByText("Choose a community above, then say where each stream lands.")
    ).not.toBeInTheDocument();
  });

  it("offers no destination while the two reads disagree", () => {
    // Mid-refetch the bindings and the projects they could name can be from
    // different communities.
    state.operationsCommunityId = 3;
    state.isFetching = true;
    renderPage();

    expect(screen.getByRole("combobox", { name: "Community" })).toBeDisabled();
    const card = screen.getByRole("region", { name: "Security" });
    expect(within(card).getByRole("button", { name: "Set this up for me" })).toBeDisabled();
  });

  it("says so when the options read is the one that failed", () => {
    // The two reads describe one community between them, so a page that acted
    // on only one would offer destinations it could not name.
    state.optionsError = true;
    state.operationsCommunityId = 3;
    renderPage();

    expect(screen.getByText("Could not load these settings")).toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: "Community" })).not.toBeInTheDocument();
  });

  it("says a stream whose project was archived receives nothing", () => {
    state.operationsCommunityId = 3;
    state.bindings = [
      {
        ...unbound("security"),
        binding_id: 1,
        project_id: 99,
        project_name: "Old Security",
        initiative_id: 7,
        initiative_name: "Trust and Safety",
        enabled: true,
        project_archived: true,
      },
      ...STREAMS.slice(1).map(unbound),
    ];
    renderPage();

    const card = screen.getByRole("region", { name: "Security" });
    expect(within(card).getByText("Destination archived")).toBeInTheDocument();
    expect(within(card).queryByText("Receiving")).not.toBeInTheDocument();
    expect(
      within(card).getByText(
        "This project has been archived, so nothing can land in it. Bring it back, or point this stream at a live project."
      )
    ).toBeInTheDocument();
  });

  it("says who to contact before any community is named", async () => {
    state.generalContact = "ops@example.com";
    state.contactEmails = { moderation: "trust@example.com" };
    const { rerender } = renderPage();
    const user = userEvent.setup();

    const general = screen.getByLabelText("General contact");
    expect(general).toHaveValue("ops@example.com");
    expect(screen.getByLabelText("Moderation")).toHaveValue("trust@example.com");
    expect(screen.getByLabelText("Support")).toHaveValue("");

    const save = screen.getByRole("button", { name: "Save contacts" });
    expect(save).toBeDisabled();

    await user.type(screen.getByLabelText("Support"), "help@example.com");
    // A refetch while the form is being filled in keeps what was typed.
    rerender(<SettingsIntakePage />);
    expect(screen.getByLabelText("Support")).toHaveValue("help@example.com");
    await user.clear(screen.getByLabelText("Moderation"));
    await user.click(save);

    expect(generalContactMutate).not.toHaveBeenCalled();
    expect(streamContactMutate).toHaveBeenCalledWith({
      stream: "moderation",
      body: { email: null },
    });
    expect(streamContactMutate).toHaveBeenCalledWith({
      stream: "support",
      body: { email: "help@example.com" },
    });
  });
});
