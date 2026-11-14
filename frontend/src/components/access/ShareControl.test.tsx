import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildUserPublic } from "@/__tests__/factories/user.factory";
import { renderWithProviders } from "@/__tests__/helpers/render";
import type {
  InitiativeRoleRead,
  ResourceGrantSchema,
} from "@/api/generated/initiativeAPI.schemas";

// ── Mock the data hooks ShareControl depends on ──────────────────────────────
// The component only reads ``.data`` off each query, so a simple stub is enough
// and keeps the test free of network/MSW plumbing.

const alice = buildUserPublic({ id: 101, display_name: "Alice" });
const bob = buildUserPublic({ id: 102, display_name: "Bob" });

const roles: InitiativeRoleRead[] = [
  {
    id: 201,
    name: "player",
    display_name: "Player",
    is_builtin: false,
    is_manager: false,
    override_share_restrictions: false,
    position: 0,
    permissions: {},
    plugin_permissions: [],
    member_count: 2,
  },
  {
    id: 202,
    name: "project_manager",
    display_name: "Project Manager",
    is_builtin: true,
    is_manager: true,
    override_share_restrictions: true,
    position: 1,
    permissions: {},
    plugin_permissions: [],
    member_count: 1,
  },
];

vi.mock("@/hooks/useInitiativeRoles", () => ({
  useInitiativeRoles: () => ({ data: roles }),
}));

// People are searched on the server — the initiative's members, or the
// community's — and the ones already named are looked up by id.
const memberSearch = vi.hoisted(() => vi.fn());
vi.mock("@/hooks/useUsers", () => ({
  USER_ID_LOOKUP_MAX: 100,
  useMemberSearch: (scope: unknown, options: { userIds?: number[] } = {}) => {
    memberSearch(scope, options);
    const { userIds } = options;
    return {
      data: {
        items: userIds?.length ? [alice, bob].filter((u) => userIds.includes(u.id)) : [alice, bob],
      },
      isFetching: false,
    };
  },
}));

// The community's installed plug-ins, which name a plug-in grantee.
vi.mock("@/hooks/useCommunityPlugins", () => ({
  useCommunityPlugins: () => ({
    data: {
      items: [
        { id: 301, name: "Automations", avatar_url: null },
        { id: 302, name: "Storefront", avatar_url: "/api/v1/marketplace/media/storefront.png" },
      ],
    },
  }),
}));

import { ShareControl } from "./ShareControl";

describe("ShareControl", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders 'All members' mode when an all_initiative_members grant is present", () => {
    const grants: ResourceGrantSchema[] = [{ all_initiative_members: true, level: "read" }];

    renderWithProviders(<ShareControl initiativeId={1} grants={grants} onChange={vi.fn()} />);

    // The general-access select shows the "All initiative members" option as
    // selected; the People/Roles lists are hidden in this mode.
    expect(screen.getByText("All initiative members")).toBeInTheDocument();
    expect(screen.queryByText("People")).not.toBeInTheDocument();
    expect(screen.queryByText("Roles")).not.toBeInTheDocument();
  });

  it("switching Share to 'Restricted' calls onChange with the user/role grants (no all-members)", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    // Start in All-members mode so there are no user/role grants to carry over.
    const grants: ResourceGrantSchema[] = [{ all_initiative_members: true, level: "read" }];

    renderWithProviders(<ShareControl initiativeId={1} grants={grants} onChange={onChange} />);

    // Open the Share mode picker (the green general-access bar) and pick "Restricted".
    await user.click(screen.getByRole("button", { name: /All initiative members/i }));
    await user.click(await screen.findByRole("button", { name: /Restricted/i }));

    expect(onChange).toHaveBeenCalledTimes(1);
    const next = onChange.mock.calls[0][0] as ResourceGrantSchema[];
    expect(next.some((g) => g.all_initiative_members)).toBe(false);
    // No prior user/role grants existed, so the restricted list is empty.
    expect(next).toEqual([]);
  });

  it("in restricted mode, adding a person calls onChange including a {user_id, level:'read'} grant", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    // Restricted mode = no all_initiative_members grant.
    const grants: ResourceGrantSchema[] = [];

    renderWithProviders(<ShareControl initiativeId={1} grants={grants} onChange={onChange} />);

    // Open the "Add people" picker and select Alice.
    await user.click(screen.getByRole("button", { name: "Add people" }));
    const aliceOption = await screen.findByText("Alice");
    await user.click(aliceOption);

    expect(onChange).toHaveBeenCalledTimes(1);
    const next = onChange.mock.calls[0][0] as ResourceGrantSchema[];
    expect(next).toContainEqual({ user_id: 101, level: "read" });
    // The picker searched the initiative's members, not the community's.
    expect(memberSearch).toHaveBeenCalledWith(
      { type: "initiative", initiativeId: 1 },
      expect.objectContaining({ enabled: true })
    );
  });

  it("renders a full-access role as a locked, non-removable Editor in restricted mode", () => {
    // Restricted mode (no all-members grant) and no stored role grant for the PM
    // role — its presence in the Roles list is purely from override_share_restrictions.
    const onChange = vi.fn();

    renderWithProviders(<ShareControl initiativeId={1} grants={[]} onChange={onChange} />);

    const rolesSection = screen.getByText("Roles").closest("div")?.parentElement as HTMLElement;
    expect(within(rolesSection).getByText("Project Manager")).toBeInTheDocument();
    expect(within(rolesSection).getByText("Full access")).toBeInTheDocument();
    expect(within(rolesSection).getByText("Editor")).toBeInTheDocument();
    // No remove control — a full-access role can't be removed from sharing.
    expect(within(rolesSection).queryByRole("button", { name: "Remove" })).not.toBeInTheDocument();
  });

  it("shows the owner as a fixed, non-editable row when ownerId is given", () => {
    const grants: ResourceGrantSchema[] = [];

    renderWithProviders(
      <ShareControl initiativeId={1} grants={grants} onChange={vi.fn()} ownerId={101} />
    );

    // Owner row appears under People with an "Owner" badge and no controls.
    const peopleSection = screen.getByText("People").closest("div")?.parentElement;
    expect(peopleSection).toBeTruthy();
    expect(within(peopleSection as HTMLElement).getByText("Alice")).toBeInTheDocument();
    expect(within(peopleSection as HTMLElement).getByText("Owner")).toBeInTheDocument();
  });
});

/**
 * The community view of the same control.
 *
 * A community-level resource is shared with the community's members, and a community has no
 * roles — the roles this control grants to belong to an initiative. So the
 * community view is a narrower control, not the same one relabelled.
 */
describe("ShareControl in its community view", () => {
  const communityProps = { initiativeId: null, onChange: vi.fn() };

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("names the community rather than an initiative", () => {
    const grants: ResourceGrantSchema[] = [{ all_initiative_members: true, level: "read" }];

    renderWithProviders(<ShareControl {...communityProps} grants={grants} />);

    expect(screen.getByText("Everyone in the community")).toBeInTheDocument();
    expect(screen.queryByText("All initiative members")).toBeNull();
  });

  it("offers no roles to add", () => {
    // Restricted mode is where the initiative view shows its Roles section.
    renderWithProviders(<ShareControl {...communityProps} grants={[]} />);

    expect(screen.getByText("People")).toBeInTheDocument();
    expect(screen.queryByText("Roles")).toBeNull();
    expect(screen.queryByRole("button", { name: "Add roles" })).toBeNull();
    // And the restricted hint says so, rather than promising roles.
    expect(screen.getByText("Only people you add can access this.")).toBeInTheDocument();
  });

  it("still shares with everyone, which is how a community calendar arrives", async () => {
    const onChange = vi.fn();
    renderWithProviders(<ShareControl initiativeId={null} grants={[]} onChange={onChange} />);

    await userEvent.click(screen.getByText("Restricted"));
    await userEvent.click(
      within(document.body).getAllByText("Everyone in the community").at(-1) as HTMLElement
    );

    expect(onChange).toHaveBeenCalledWith([{ all_initiative_members: true, level: "read" }]);
  });

  it("drops a role grant rather than carrying it through an edit", async () => {
    // The server cannot resolve one on a community-level resource, so a stray
    // stored grant must not survive a save made from this view.
    const onChange = vi.fn();
    const grants: ResourceGrantSchema[] = [
      { role_id: 201, level: "write" },
      { user_id: alice.id, level: "read" },
    ];

    renderWithProviders(<ShareControl initiativeId={null} grants={grants} onChange={onChange} />);

    // The grantee is named from a lookup by id, with no roster held.
    expect(await screen.findByText("Alice")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Add people" }));
    await userEvent.click(await screen.findByText("Bob"));

    expect(onChange).toHaveBeenCalledWith([
      { user_id: alice.id, level: "read" },
      { user_id: bob.id, level: "read" },
    ]);
  });
});

describe("ShareControl with a plug-in", () => {
  it("shows the owning plug-in by name and picture in the Owner row", () => {
    const grants: ResourceGrantSchema[] = [{ plugin_install_id: 302, level: "owner" }];

    renderWithProviders(
      <ShareControl
        initiativeId={1}
        grants={grants}
        ownerId={null}
        ownerPlugin={{ id: 302, name: "Storefront", avatar_url: "/media/storefront.png" }}
        onChange={vi.fn()}
      />
    );

    const row = screen.getByText("Storefront").closest("div") as HTMLElement;
    expect(within(row).getByText("Owner")).toBeInTheDocument();
    expect(within(row).getByText("Plug-in")).toBeInTheDocument();
    expect(row.querySelector("img")).not.toBeNull();
    // It is not offered as a person to add, and not editable.
    expect(within(row).queryByRole("combobox")).not.toBeInTheDocument();
  });

  it("names an owning plug-in from the community's plug-ins when the read model does not", () => {
    const grants: ResourceGrantSchema[] = [{ plugin_install_id: 301, level: "owner" }];

    renderWithProviders(
      <ShareControl initiativeId={1} grants={grants} ownerId={null} onChange={vi.fn()} />
    );

    const row = screen.getByText("Automations").closest("div") as HTMLElement;
    expect(within(row).getByText("Owner")).toBeInTheDocument();
  });

  it("lists a plug-in grantee by name, read-only, and never sends it back", async () => {
    const onChange = vi.fn();
    const grants: ResourceGrantSchema[] = [
      { plugin_install_id: 301, level: "write" },
      { user_id: alice.id, level: "read" },
    ];

    renderWithProviders(<ShareControl initiativeId={1} grants={grants} onChange={onChange} />);

    expect(screen.getByText("Plug-ins")).toBeInTheDocument();
    const row = screen.getByText("Automations").closest("div") as HTMLElement;
    expect(within(row).getByText("Editor")).toBeInTheDocument();
    expect(within(row).queryByRole("button")).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Add people" }));
    await userEvent.click(await screen.findByText("Bob"));

    expect(onChange).toHaveBeenCalledWith([
      { user_id: alice.id, level: "read" },
      { user_id: bob.id, level: "read" },
    ]);
  });
});
