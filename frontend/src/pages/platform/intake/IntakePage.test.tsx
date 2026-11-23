/**
 * The owner's intake settings.
 *
 * Two things matter here and neither is cosmetic: no stream is routed until a
 * community is named, because every id it would take belongs to that
 * community; and a stream that has never been set up offers both ways of
 * setting one up rather than only the blueprint. Contacts work either way.
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
  deletePending: false,
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
  useUpsertIntakeBinding: () => ({
    mutate: upsertMutate,
    mutateAsync: upsertMutate,
    isPending: false,
  }),
  useImportIntakeBlueprint: () => ({ mutate: importMutate, isPending: false }),
  useDeleteIntakeBinding: () => ({ mutate: deleteMutate, isPending: state.deletePending }),
  useUpdateIntakeGeneralContact: () => ({ mutateAsync: generalContactMutate, isPending: false }),
  useUpdateIntakeStreamContact: () => ({ mutateAsync: streamContactMutate, isPending: false }),
  useUpdateFeedbackSwitch: () => ({ mutate: vi.fn(), isPending: false }),
}));

vi.mock("@/hooks/useSettings", () => ({
  usePlatformCommunities: () => ({ data: buildPage([{ id: 3, name: "Operations" }]) }),
}));

import { IntakePage } from "./IntakePage";

const renderPage = (role: "owner" | "operator" = "owner") =>
  renderWithProviders(<IntakePage />, { auth: { user: buildUser({ role }) } });

describe("IntakePage", () => {
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
    state.deletePending = false;
  });

  const boundSecurity = (overrides: Record<string, unknown> = {}) => [
    {
      ...unbound("security"),
      binding_id: 1,
      project_id: 21,
      project_name: "Security",
      initiative_id: 7,
      initiative_name: "Trust and Safety",
      enabled: true,
      ...overrides,
    },
    ...STREAMS.slice(1).map(unbound),
  ];

  /** The stream's row, named by its title. */
  const row = (title: string) => screen.getByRole("listitem", { name: title });

  it("routes nothing until a community is named, but still lists every stream", () => {
    renderPage();
    expect(screen.getByText(/^Choose a community to route cases/)).toBeVisible();
    for (const title of ["Security", "Moderation", "Support", "Feedback"]) {
      expect(within(row(title)).getByText("—")).toBeVisible();
    }
    expect(screen.queryByRole("button", { name: /^Set up/ })).not.toBeInTheDocument();
  });

  it("offers each unrouted stream a Set up once a community is named, from its blueprint", async () => {
    state.operationsCommunityId = 3;
    renderPage();
    const user = userEvent.setup();
    expect(screen.getAllByText("Not set up")).toHaveLength(STREAMS.length);

    await user.click(screen.getByRole("button", { name: "Set up Security" }));
    const dialog = await screen.findByRole("dialog");
    const setUp = () => within(dialog).getByRole("button", { name: "Set this up for me" });

    // Disabled until an initiative is chosen: the import has to land somewhere.
    expect(setUp()).toBeDisabled();
    await user.click(within(dialog).getByRole("combobox", { name: "Initiative" }));
    await user.click(await screen.findByRole("option", { name: "Trust and Safety" }));
    await user.click(setUp());

    expect(importMutate).toHaveBeenCalledWith({ stream: "security", initiativeId: 7 });
  });

  it("shows where a bound stream lands on its row, and switches it there", async () => {
    state.operationsCommunityId = 3;
    state.bindings = boundSecurity({ last_case_at: "2026-09-15T10:00:00Z" });
    renderPage();
    const user = userEvent.setup();

    expect(within(row("Security")).getByText("Trust and Safety › Security")).toBeVisible();
    const receiving = screen.getByRole("switch", { name: "Receive new Security cases" });
    expect(receiving).toBeChecked();
    await user.click(receiving);
    expect(upsertMutate).toHaveBeenCalledWith({
      stream: "security",
      body: expect.objectContaining({ project_id: 21, enabled: false }),
    });

    // When it last opened a case is in its dialog, with the rest.
    await user.click(screen.getByRole("button", { name: "Edit Security" }));
    expect(await screen.findByText(/Last case opened/)).toBeInTheDocument();
  });

  it("files a stream's cases as the type chosen, once saved", async () => {
    state.operationsCommunityId = 3;
    state.bindings = boundSecurity();
    renderPage();
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Edit Security" }));
    const dialog = await screen.findByRole("dialog");
    const picker = within(dialog).getByRole("combobox", { name: "New cases are" });
    expect(picker).toHaveTextContent("The project's default type");
    await user.click(picker);
    await user.click(await screen.findByRole("option", { name: "Bug" }));

    // Nothing is sent until Save.
    expect(upsertMutate).not.toHaveBeenCalled();
    await user.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(upsertMutate).toHaveBeenCalledWith({
      stream: "security",
      body: expect.objectContaining({ project_id: 21, task_type_id: 42 }),
    });
  });

  it("sends nothing over a Stop routing still under way", async () => {
    state.operationsCommunityId = 3;
    state.bindings = boundSecurity();
    const { rerender } = renderPage();
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Edit Security" }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("combobox", { name: "New cases are" }));
    await user.click(await screen.findByRole("option", { name: "Bug" }));
    expect(within(dialog).getByRole("button", { name: "Save" })).toBeEnabled();

    // A binding written after the delete would route the stream again.
    state.deletePending = true;
    rerender(<IntakePage />);
    expect(within(screen.getByRole("dialog")).getByRole("button", { name: "Save" })).toBeDisabled();
    expect(upsertMutate).not.toHaveBeenCalled();
  });

  it("keeps a contact typed before the stream is set up", async () => {
    state.operationsCommunityId = 3;
    const { rerender } = renderPage();
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Set up Security" }));
    await user.type(
      within(await screen.findByRole("dialog")).getByLabelText("Contact"),
      "sec@example.com"
    );

    // Setting it up lands it on a project, which remounts the routing form.
    state.bindings = boundSecurity();
    rerender(<IntakePage />);
    expect(within(screen.getByRole("dialog")).getByLabelText("Contact")).toHaveValue(
      "sec@example.com"
    );
  });

  it("tells a non-owner this is not theirs to configure", () => {
    renderPage("operator");
    expect(
      screen.getByText("Only platform owners can configure where operations work lands.")
    ).toBeInTheDocument();
  });

  // The page shows the failure and withholds the picker, so a change is only
  // made against a value that was actually read. The two reads describe one
  // community between them, so a page that acted on only one would offer
  // destinations it could not name.
  it.each(["isError", "optionsError"] as const)(
    "says the read failed (%s) rather than showing an unconfigured deployment",
    (failed) => {
      state[failed] = true;
      state.operationsCommunityId = 3;
      renderPage();

      expect(screen.getByRole("alert")).toBeInTheDocument();
      expect(screen.queryByRole("combobox", { name: "Community" })).not.toBeInTheDocument();
      expect(screen.queryByRole("list")).not.toBeInTheDocument();
    }
  );

  it("offers no destination while the two reads disagree", () => {
    // Mid-refetch the bindings and the projects they could name can be from
    // different communities.
    state.operationsCommunityId = 3;
    state.isFetching = true;
    renderPage();

    expect(screen.getByRole("combobox", { name: "Community" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Set up Security" })).toBeDisabled();
  });

  it("says a stream whose project was archived receives nothing", async () => {
    state.operationsCommunityId = 3;
    state.bindings = boundSecurity({
      project_id: 99,
      project_name: "Old Security",
      project_archived: true,
    });
    renderPage();
    const user = userEvent.setup();

    expect(within(row("Security")).getByText("Destination archived")).toBeVisible();
    expect(screen.getByRole("switch", { name: "Receive new Security cases" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Edit Security" }));
    expect(
      await screen.findByText(
        "This project has been archived, so nothing can land in it. Bring it back, or point this stream at a live project."
      )
    ).toBeInTheDocument();
  });

  it("shows each stream's contact on its row and edits it in its dialog", async () => {
    state.contactEmails = { moderation: "trust@example.com" };
    renderPage();
    const user = userEvent.setup();

    expect(within(row("Moderation")).getByText("trust@example.com")).toBeVisible();
    expect(within(row("Support")).getByText("General contact")).toBeVisible();

    await user.click(screen.getByRole("button", { name: "Edit Moderation" }));
    const dialog = await screen.findByRole("dialog");
    const contact = within(dialog).getByLabelText("Contact");
    expect(contact).toHaveValue("trust@example.com");
    await user.clear(contact);
    await user.click(within(dialog).getByRole("button", { name: "Save" }));

    expect(streamContactMutate).toHaveBeenCalledWith({
      stream: "moderation",
      body: { email: null },
    });
    expect(upsertMutate).not.toHaveBeenCalled();
  });

  it("saves the general contact on its own", async () => {
    state.generalContact = "ops@example.com";
    renderPage();
    const user = userEvent.setup();

    const general = screen.getByLabelText("General contact");
    expect(general).toHaveValue("ops@example.com");
    const save = screen.getByRole("button", { name: "Save contacts" });
    expect(save).toBeDisabled();

    await user.clear(general);
    await user.type(general, "hello@example.com");
    await user.click(save);

    expect(generalContactMutate).toHaveBeenCalledWith({ email: "hello@example.com" });
    expect(streamContactMutate).not.toHaveBeenCalled();
  });
});
