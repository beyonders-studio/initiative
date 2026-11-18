import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildUser } from "@/__tests__/factories";
import { renderPage, renderWithProviders } from "@/__tests__/helpers/render";
import type { PluginServiceRegistrationRead } from "@/api/generated/initiativeAPI.schemas";
import { formatDate } from "@/ui/lib/formatDate";

const buildRegistration = (
  overrides: Partial<PluginServiceRegistrationRead> = {}
): PluginServiceRegistrationRead => ({
  id: 1,
  public_id: "core.github",
  listing_uid: "gh7k2m9p4q1x8z",
  name: null,
  avatar_url: null,
  version: "1.0.0",
  first_party: false,
  kind: "container",
  publisher_id: 1,
  publisher_prefix: "core",
  publisher_name: "Core Plug-ins",
  publisher_enabled: true,
  base_url: "http://initiative-github:8080",
  page_origin: null,
  allowed_origins: [],
  jwks: { keys: [{ kty: "OKP", crv: "Ed25519", kid: "k1", x: "abc" }] },
  jwks_uri: null,
  scope_ceiling: [],
  mandatory: false,
  availability: "none",
  beta_communities: [],
  shared_routes: false,
  suspended_at: null,
  source: "operator",
  image_digest: null,
  compose_service: null,
  compose_base_url: null,
  vendor_fields: [],
  vendor_values: {},
  vendor_set: [],
  vendor_ready: true,
  vendor_setup: null,
  vendor_check: null,
  connection_callback_url: "https://initiative.example.com/api/v1/plugin-connections/callback",
  connection_setup_url: "https://initiative.example.com/api/v1/plugin-connections/setup",
  webhook_url: "https://initiative.example.com/api/v1/plugin-hooks/core.github",
  live: true,
  created_at: "2026-08-01T00:00:00.000Z",
  updated_at: "2026-08-12T09:00:00.000Z",
  ...overrides,
});

// Flipped per test before rendering; read lazily inside the mocked hooks.
let registrations: PluginServiceRegistrationRead[] = [];
// What the list asked the server for, last.
let listParams: Record<string, unknown> = {};

const createMutate = vi.fn();
const updateMutate = vi.fn();
const deleteMutate = vi.fn();
const readKeysMutate = vi.fn();
const connectMutate = vi.fn();
const startSetupMutate = vi.fn();
const completeSetupMutate = vi.fn();

vi.mock("@/lib/mascotToast", () => ({
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
}));

vi.mock("@/hooks/usePluginServices", () => ({
  usePluginServices: (params: Record<string, unknown>) => {
    listParams = params;
    return {
      data: {
        items: registrations,
        total_count: registrations.length,
        page: 1,
        page_size: 20,
        has_next: false,
        has_prev: false,
      },
      isLoading: false,
      isError: false,
    };
  },
  usePluginService: () => ({ data: registrations[0], isLoading: false, isError: false }),
  useCreatePluginService: () => ({ mutate: createMutate, isPending: false }),
  useUpdatePluginService: () => ({ mutate: updateMutate, isPending: false }),
  useDeletePluginService: () => ({ mutate: deleteMutate, isPending: false }),
  usePluginServiceKeys: () => ({ mutate: readKeysMutate, isPending: false }),
  useConnectPluginService: () => ({ mutate: connectMutate, isPending: false }),
  useStartVendorSetup: () => ({ mutate: startSetupMutate, isPending: false }),
  useCompleteVendorSetup: () => ({ mutate: completeSetupMutate, isPending: false }),
}));

// The beta's community picker searches every community on the server.
vi.mock(import("@/hooks/useSettings"), async (importOriginal) => ({
  ...(await importOriginal()),
  usePlatformCommunities: (() => ({
    data: {
      items: [
        { id: 7, name: "Riverside", status: "active" },
        { id: 8, name: "Hilltop", status: "active" },
      ],
    },
    isFetching: false,
  })) as unknown as typeof import("@/hooks/useSettings").usePlatformCommunities,
}));

import { PluginServicePage } from "./PluginServicePage";
import { PluginServicesPage } from "./PluginServicesPage";

const operator = { user: buildUser({ role: "owner", capabilities: ["plugins.manage"] }) };

/** The list, once it has rendered. */
const renderAsOperator = async () => {
  renderPage(PluginServicesPage, {
    auth: operator,
    initialRoute: "/settings/platform/integrations",
  });
  await screen.findByRole("button", { name: "Add plug-in service" });
};

/** The first registration's own page, once it has rendered. */
const renderPluginPage = async () => {
  renderPage(PluginServicePage, {
    auth: operator,
    initialRoute: "/settings/platform/integrations/plugins/$registrationId",
    routeParams: { registrationId: String(registrations[0].id) },
  });
  await screen.findByRole("heading", { name: registrations[0].public_id });
};

describe("PluginServicesPage", () => {
  beforeEach(() => {
    registrations = [];
    listParams = {};
    createMutate.mockReset();
    updateMutate.mockReset();
    deleteMutate.mockReset();
    readKeysMutate.mockReset();
    connectMutate.mockReset();
    startSetupMutate.mockReset();
    completeSetupMutate.mockReset();
  });

  describe("capability gate", () => {
    it("offers nothing to manage without plugins.manage", () => {
      registrations = [buildRegistration()];
      // A platform owner still sees nothing: the gate is the capability, never
      // the role.
      renderWithProviders(<PluginServicesPage />, {
        auth: { user: buildUser({ role: "owner", capabilities: [] }) },
      });

      expect(
        screen.getByText("Only platform owners can manage plug-in services.")
      ).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Add plug-in service" })).toBeNull();
      expect(screen.queryByText("core.github")).toBeNull();
    });
  });

  describe("the list", () => {
    it("gives each plug-in one row: its publisher, its version and whether it is live", async () => {
      registrations = [
        buildRegistration({ id: 1, public_id: "core.github", version: "1.4.0", live: true }),
        // No key set, pasted or by address, so it cannot be live.
        buildRegistration({
          id: 2,
          public_id: "core.slack",
          listing_uid: null,
          version: null,
          jwks: null,
          live: false,
        }),
      ];
      await renderAsOperator();

      const github = screen.getByRole("row", { name: /core\.github/ });
      expect(within(github).getByRole("link", { name: "core.github" })).toBeInTheDocument();
      expect(within(github).getByText("Core Plug-ins")).toBeInTheDocument();
      expect(within(github).getByText("1.4.0")).toBeInTheDocument();
      expect(within(github).getByText("Live")).toBeInTheDocument();

      const slack = screen.getByRole("row", { name: /core\.slack/ });
      expect(within(slack).getByText("Waiting for its listing")).toBeInTheDocument();
      expect(within(slack).getByText("Not live")).toBeInTheDocument();
    });

    it("leads a row with its listing's name and art, the identifier under it", async () => {
      registrations = [
        buildRegistration({
          name: "GitHub",
          avatar_url: "/marketplace/github.svg",
          source: "registry",
          first_party: true,
        }),
      ];
      await renderAsOperator();

      const row = screen.getByRole("row", { name: /GitHub/ });
      expect(within(row).getByRole("link", { name: "GitHub" })).toBeInTheDocument();
      expect(within(row).getByText(/core\.github/)).toBeInTheDocument();
      expect(row.querySelector('img[src$="/marketplace/github.svg"]')).not.toBeNull();
      // Signed by the registry, and published by this project.
      expect(within(row).getByText("Verified")).toBeInTheDocument();
      expect(within(row).getByText("Built by Initiative")).toBeInTheDocument();
    });

    it("tags neither on a plug-in this deployment added itself", async () => {
      registrations = [buildRegistration({ source: "operator", first_party: false })];
      await renderAsOperator();

      expect(screen.queryByText("Verified")).toBeNull();
      expect(screen.queryByText("Built by Initiative")).toBeNull();
    });

    it("asks the server for what was searched, rather than filtering one page", async () => {
      const user = userEvent.setup();
      registrations = [buildRegistration()];
      await renderAsOperator();

      await user.type(screen.getByPlaceholderText("Search by identifier or publisher"), "github");

      await waitFor(() => expect(listParams).toMatchObject({ search: "github", page: 1 }));
    });

    it("tags beta and operations-only plug-ins, and mandatory ones", async () => {
      registrations = [
        buildRegistration({ id: 1, public_id: "core.automation", mandatory: true }),
        buildRegistration({ id: 2, public_id: "acme.shopify", availability: "beta" }),
        buildRegistration({ id: 3, public_id: "acme.sales", availability: "operations" }),
        buildRegistration({
          id: 4,
          public_id: "acme.intake",
          availability: "operations",
          mandatory: true,
        }),
      ];
      await renderAsOperator();

      expect(
        within(screen.getByRole("row", { name: /core\.automation/ })).getByText(
          "In every community"
        )
      ).toBeInTheDocument();
      expect(
        within(screen.getByRole("row", { name: /acme\.shopify/ })).getByText("Beta")
      ).toBeInTheDocument();
      expect(
        within(screen.getByRole("row", { name: /acme\.sales/ })).getByText(
          "Operations community only"
        )
      ).toBeInTheDocument();
      const intake = screen.getByRole("row", { name: /acme\.intake/ });
      expect(within(intake).getByText("In the operations community")).toBeInTheDocument();
      expect(within(intake).queryByText("In every community")).toBeNull();
    });

    it("says when the publisher is switched off", async () => {
      registrations = [
        buildRegistration({ publisher_name: "Acme", publisher_enabled: false, live: false }),
      ];
      await renderAsOperator();

      expect(screen.getByText("Not live")).toBeInTheDocument();
      expect(screen.getByText("Publisher switched off")).toBeInTheDocument();
    });

    it("says since when a plug-in is suspended", async () => {
      registrations = [buildRegistration({ suspended_at: "2026-11-15T12:00:00Z" })];
      await renderAsOperator();

      expect(
        screen.getByText(`Suspended since ${formatDate("2026-11-15T12:00:00Z")}`)
      ).toBeInTheDocument();
    });
  });

  describe("registering", () => {
    const fillNewService = async () => {
      const user = userEvent.setup();
      await renderAsOperator();

      await user.click(screen.getByRole("button", { name: "Add plug-in service" }));

      await user.type(await screen.findByLabelText("Plug-in identifier"), "acme.shopify");
      await user.type(screen.getByLabelText("Base URL"), "https://shopify.example.com");
      await user.type(
        screen.getByLabelText("Key set address"),
        "https://shopify.example.com/.well-known/jwks.json"
      );
      return user;
    };

    it("registers a new service with its keys, leaving the listing to the plug-in", async () => {
      const user = await fillNewService();

      expect(screen.queryByLabelText("Listing")).toBeNull();
      await user.click(screen.getByRole("button", { name: "Save" }));

      expect(createMutate).toHaveBeenCalledWith(
        {
          public_id: "acme.shopify",
          base_url: "https://shopify.example.com",
          // Left blank: the plug-in answers both surfaces at the base URL.
          page_origin: null,
          allowed_origins: null,
          // Nothing pasted: the keys come from the address.
          jwks: null,
          jwks_uri: "https://shopify.example.com/.well-known/jwks.json",
          mandatory: false,
        },
        expect.anything()
      );
    });

    it("asks for no shared secret, and confers no powers beyond the scope ceiling", async () => {
      const user = userEvent.setup();
      await renderAsOperator();

      await user.click(screen.getByRole("button", { name: "Add plug-in service" }));
      await screen.findByLabelText("Plug-in identifier");

      expect(screen.queryByText(/shared secret/i)).toBeNull();
      expect(document.querySelector('input[type="password"]')).toBeNull();
      // Connect reads from a saved base URL, so a new one has nothing to read.
      expect(screen.queryByRole("button", { name: "Connect" })).toBeNull();
      // One switch in the operator's box: whether every community gets it.
      expect(within(screen.getByRole("dialog")).getAllByRole("switch")).toHaveLength(1);
    });

    it("sends the browser address when the plug-in is published somewhere else", async () => {
      const user = userEvent.setup();
      await renderAsOperator();

      await user.click(screen.getByRole("button", { name: "Add plug-in service" }));

      await user.type(await screen.findByLabelText("Plug-in identifier"), "acme.shopify");
      await user.type(screen.getByLabelText("Base URL"), "http://shopify:8080");
      await user.type(screen.getByLabelText("Browser address"), "https://shop.example.com");
      await user.click(screen.getByRole("button", { name: "Save" }));

      expect(createMutate).toHaveBeenCalledWith(
        expect.objectContaining({
          base_url: "http://shopify:8080",
          page_origin: "https://shop.example.com",
        }),
        expect.anything()
      );
    });
  });
});

describe("PluginServicePage", () => {
  beforeEach(() => {
    registrations = [];
    updateMutate.mockReset();
    deleteMutate.mockReset();
    readKeysMutate.mockReset();
    connectMutate.mockReset();
    startSetupMutate.mockReset();
  });

  describe("what it is", () => {
    it("shows its listing's facts, and what keeps it from being live", async () => {
      registrations = [
        buildRegistration({
          version: "1.4.0",
          jwks: null,
          live: false,
          scope_ceiling: ["projects:read", "projects:write"],
        }),
      ];
      await renderPluginPage();

      expect(screen.getByText("Core Plug-ins")).toBeInTheDocument();
      expect(screen.getByText("1.4.0")).toBeInTheDocument();
      expect(screen.getByText("gh7k2m9p4q1x8z")).toBeInTheDocument();
      // The ceiling is the listing's, shown and not edited.
      expect(screen.getByText("projects:read, projects:write")).toBeInTheDocument();
      expect(screen.getByText(/Not live until it has signing keys/)).toBeInTheDocument();
      // The identifier is the page's heading, not a box to edit.
      expect(screen.queryByLabelText("Plug-in identifier")).toBeNull();
    });

    it("says why a switched-off publisher stops it", async () => {
      registrations = [
        buildRegistration({ publisher_name: "Acme", publisher_enabled: false, live: false }),
      ];
      await renderPluginPage();

      expect(
        screen.getByText(/Every plug-in from Acme is stopped because its publisher is switched off/)
      ).toBeInTheDocument();
    });

    it("says a registration waits on its vendor values", async () => {
      registrations = [buildRegistration({ vendor_ready: false, live: false })];
      await renderPluginPage();

      expect(screen.getByText(/Not live until its vendor client is set/)).toBeInTheDocument();
    });

    it("offers no handshake to run", async () => {
      registrations = [buildRegistration()];
      await renderPluginPage();

      expect(screen.queryByRole("button", { name: "Verify" })).toBeNull();
    });
  });

  describe("reach", () => {
    it("spells out what mandatory means", async () => {
      registrations = [buildRegistration({ mandatory: true })];
      await renderPluginPage();

      expect(
        screen.getByText(
          "Installed into every community automatically. Community admins cannot remove it or turn it off."
        )
      ).toBeInTheDocument();
    });

    it("says a mandatory operations-only plug-in is installed in the operations community alone", async () => {
      registrations = [buildRegistration({ mandatory: true, availability: "operations" })];
      await renderPluginPage();

      expect(
        screen.getByText(/added to the operations community only, and its admins cannot remove it/)
      ).toBeInTheDocument();
    });

    it.each([
      ["none", "Every community"],
      ["operations", "The operations community"],
    ] as const)(
      "says a plug-in declaring %s reaches %s, with nothing to pick",
      async (availability, reach) => {
        const user = userEvent.setup();
        registrations = [buildRegistration({ availability })];
        await renderPluginPage();

        expect(screen.getByText(reach)).toBeInTheDocument();
        expect(screen.queryByRole("combobox")).toBeNull();
        await user.click(screen.getByRole("button", { name: "Save" }));

        expect(updateMutate.mock.calls[0][0].data).not.toHaveProperty("beta_community_ids");
      }
    );

    it("says nobody can use a beta plug-in until communities are picked", async () => {
      registrations = [buildRegistration({ availability: "beta" })];
      await renderPluginPage();

      expect(screen.getByText("Beta")).toBeInTheDocument();
      expect(
        screen.getByText("Nobody can use this plug-in until you pick communities.")
      ).toBeInTheDocument();
    });

    it("replaces a beta plug-in's communities with those picked", async () => {
      const user = userEvent.setup();
      registrations = [
        buildRegistration({
          availability: "beta",
          beta_communities: [{ id: 7, name: "Riverside" }],
        }),
      ];
      await renderPluginPage();

      expect(screen.getByText("Riverside (#7)")).toBeInTheDocument();
      await user.click(screen.getByRole("combobox", { name: "Communities in the beta" }));
      await user.click(await screen.findByRole("option", { name: /Hilltop/ }));
      await user.keyboard("{Escape}");
      await user.click(screen.getByRole("button", { name: "Remove Riverside (#7)" }));
      await user.click(screen.getByRole("button", { name: "Save" }));

      expect(updateMutate.mock.calls[0][0].data).toMatchObject({ beta_community_ids: [8] });
    });
  });

  describe("editing", () => {
    it("sends the key set address and keeps the pasted set", async () => {
      const user = userEvent.setup();
      registrations = [buildRegistration({ jwks_uri: "https://gh.example.com/jwks.json" })];
      await renderPluginPage();

      // Emptying the address clears it rather than leaving it stored.
      await user.clear(screen.getByLabelText("Key set address"));
      await user.click(screen.getByRole("button", { name: "Save" }));

      const data = updateMutate.mock.calls[0][0].data;
      expect(data).toMatchObject({ jwks_uri: "" });
      expect(data).not.toHaveProperty("listing_uid");
      // The stored key set is shown in the box and sent back as it was.
      expect(data.jwks).toEqual(registrations[0].jwks);
      expect(data).not.toHaveProperty("secret");
    });

    it("lists the addresses to register, then asks for the vendor values, keeping a secret left alone", async () => {
      const user = userEvent.setup();
      registrations = [
        buildRegistration({
          vendor_fields: [
            { key: "client_id", type: "string", required: true, label: { en: "Client id" } },
            { key: "client_secret", type: "secret", required: true, label: { en: "Secret" } },
          ],
          vendor_values: { client_id: "gh-app" },
          vendor_set: ["client_id", "client_secret"],
        }),
      ];
      await renderPluginPage();

      // Where the vendor sends people back, to register with it, each to copy.
      for (const address of [
        "https://initiative.example.com/api/v1/plugin-connections/callback",
        "https://initiative.example.com/api/v1/plugin-connections/setup",
        "https://initiative.example.com/api/v1/plugin-hooks/core.github",
      ]) {
        expect(screen.getByText(address)).toBeInTheDocument();
      }
      expect(screen.getByRole("button", { name: "Copy the Callback address" })).toBeInTheDocument();
      expect(screen.getByText("Set up")).toBeInTheDocument();

      const clientId = screen.getByLabelText(/Client id/);
      expect(clientId).toHaveValue("gh-app");
      // A stored secret is never sent back, only that it is set.
      const secret = screen.getByLabelText(/Secret/);
      expect(secret).toHaveValue("");
      expect(secret).toHaveAttribute("placeholder", "Set. Type to replace it.");

      await user.clear(clientId);
      await user.type(clientId, "gh-app-2");
      await user.click(
        screen.getByRole("switch", { name: "Share installations between communities" })
      );
      await user.click(screen.getByRole("button", { name: "Save" }));

      expect(updateMutate.mock.calls[0][0].data).toMatchObject({
        shared_routes: true,
        vendor_values: { client_id: "gh-app-2" },
      });
    });

    it("asks a declarative plug-in for its vendor values and nothing about where it runs", async () => {
      const user = userEvent.setup();
      registrations = [
        buildRegistration({
          kind: "declarative",
          base_url: null,
          jwks: null,
          vendor_fields: [
            { key: "client_id", type: "string", required: true, label: { en: "Client id" } },
          ],
        }),
      ];
      await renderPluginPage();

      expect(screen.queryByText(/Not live until it has an address/)).toBeNull();
      expect(screen.queryByText(/Not live until it has signing keys/)).toBeNull();
      await user.type(screen.getByLabelText(/Client id/), "gh-app");
      expect(screen.queryByLabelText("Base URL")).toBeNull();
      expect(screen.queryByLabelText("Pasted key set (JWKS)")).toBeNull();
      await user.click(screen.getByRole("button", { name: "Save" }));

      expect(updateMutate.mock.calls[0][0].data).toEqual({
        mandatory: false,
        shared_routes: false,
        vendor_values: { client_id: "gh-app" },
      });
    });

    it("shows the compose service to copy, and its address as the base URL", async () => {
      const service = "github:\n  image: ghcr.io/beyonders-studio/github@sha256:abc\n";
      registrations = [
        buildRegistration({
          base_url: null,
          compose_service: service,
          compose_base_url: "http://github:8080",
        }),
      ];
      await renderPluginPage();

      const snippet = screen.getByLabelText("Compose service");
      expect(snippet).toHaveValue(service);
      expect(snippet).toHaveAttribute("readonly");
      expect(screen.getByRole("button", { name: "Copy" })).toBeInTheDocument();
      expect(screen.getByLabelText("Base URL")).toHaveValue("http://github:8080");
    });

    it("leads with creating the GitHub App, posting its manifest there", async () => {
      const user = userEvent.setup();
      const submit = vi.spyOn(HTMLFormElement.prototype, "submit").mockImplementation(() => {});
      registrations = [
        buildRegistration({
          vendor_setup: "github_app_manifest",
          vendor_fields: [
            { key: "client_id", type: "string", required: true, label: { en: "Client id" } },
          ],
          vendor_ready: false,
        }),
      ];
      startSetupMutate.mockImplementation((_vars, { onSuccess }) =>
        onSuccess({
          action: "https://github.com/organizations/acme/settings/apps/new",
          manifest: '{"name":"GitHub"}',
          state: "st/ate",
        })
      );
      await renderPluginPage();

      expect(screen.getByText("Values missing")).toBeInTheDocument();
      // Typing them in is the other way, folded away until asked for.
      expect(screen.queryByLabelText(/Client id/)).toBeNull();
      await user.type(screen.getByLabelText("GitHub organization"), "acme");
      await user.click(screen.getByRole("button", { name: "Create the GitHub App" }));

      expect(startSetupMutate).toHaveBeenCalledWith(
        { registrationId: 1, organization: "acme" },
        expect.anything()
      );
      const posted = submit.mock.contexts[0] as HTMLFormElement;
      expect(posted.method).toBe("post");
      expect(posted.action).toBe(
        "https://github.com/organizations/acme/settings/apps/new?state=st%2Fate"
      );
      expect(posted.elements.namedItem("manifest")).toHaveValue('{"name":"GitHub"}');
      submit.mockRestore();
      posted.remove();

      await user.click(screen.getByRole("button", { name: "Or enter the values yourself" }));
      expect(screen.getByLabelText(/Client id/)).toBeInTheDocument();
    });

    it("offers no GitHub App to a plug-in whose listing has no setup", async () => {
      registrations = [
        buildRegistration({
          vendor_fields: [{ key: "client_id", type: "string", required: true, label: {} }],
        }),
      ];
      await renderPluginPage();

      expect(screen.getByLabelText(/client_id/)).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Create the GitHub App" })).toBeNull();
    });

    it("leads with the values once they are set, folding a new app away", async () => {
      const user = userEvent.setup();
      registrations = [
        buildRegistration({
          vendor_setup: "github_app_manifest",
          vendor_fields: [
            { key: "client_id", type: "string", required: true, label: { en: "Client id" } },
          ],
          vendor_values: { client_id: "Iv1.abc" },
          vendor_set: ["client_id"],
          vendor_ready: true,
        }),
      ];
      await renderPluginPage();

      expect(screen.getByLabelText(/Client id/)).toHaveValue("Iv1.abc");
      expect(screen.queryByRole("button", { name: "Create the GitHub App" })).toBeNull();
      await user.click(
        screen.getByRole("button", { name: "Or replace them with a new app from the vendor" })
      );
      expect(screen.getByRole("button", { name: "Create the GitHub App" })).toBeInTheDocument();
    });

    it("marks the fields a vendor check blames, with what the vendor has", async () => {
      const user = userEvent.setup();
      const { toast } = await import("@/lib/mascotToast");
      registrations = [
        buildRegistration({
          vendor_fields: [
            { key: "app_slug", type: "string", required: true, label: { en: "App name" } },
            { key: "app_id", type: "string", required: true, label: { en: "App id" } },
          ],
          vendor_values: { app_slug: "widgets", app_id: "7" },
          vendor_set: ["app_slug", "app_id"],
        }),
      ];
      updateMutate.mockImplementation((_vars, { onError }) =>
        onError({
          isAxiosError: true,
          response: {
            status: 400,
            data: {
              detail: "PLUGIN_SERVICE_VENDOR_CHECK_REFUSED",
              params: {
                fields: "app_slug",
                message: JSON.stringify({ en: "The id and key belong to another name." }),
                shows: "widgets-for-acme",
              },
            },
          },
        })
      );
      await renderPluginPage();

      await user.click(screen.getByRole("button", { name: "Save" }));

      const alert = await screen.findByRole("alert");
      expect(alert).toHaveTextContent("The id and key belong to another name.");
      expect(alert).toHaveTextContent("widgets-for-acme");
      expect(screen.getByLabelText(/App name/)).toHaveAttribute("aria-invalid", "true");
      expect(screen.getByLabelText(/App id/)).not.toHaveAttribute("aria-invalid");
      expect(toast.error).toHaveBeenCalledWith("The id and key belong to another name.");
    });

    it("says when the vendor could not be asked about the values", async () => {
      const user = userEvent.setup();
      const { toast } = await import("@/lib/mascotToast");
      registrations = [
        buildRegistration({
          vendor_fields: [
            { key: "app_id", type: "string", required: true, label: { en: "App id" } },
          ],
        }),
      ];
      updateMutate.mockImplementation((_vars, { onSuccess }) =>
        onSuccess({ ...registrations[0], vendor_check: "not_run" })
      );
      await renderPluginPage();

      await user.type(screen.getByLabelText(/App id/), "4735814");
      await user.click(screen.getByRole("button", { name: "Save" }));

      await waitFor(() => expect(toast.warning).toHaveBeenCalled());
      // Kept, so saving again sends it again and the vendor is asked again.
      expect(screen.getByLabelText(/App id/)).toHaveValue("4735814");
      await user.click(screen.getByRole("button", { name: "Save" }));
      expect(updateMutate.mock.calls[1][0].data.vendor_values).toEqual({ app_id: "4735814" });
    });

    it("connects: shows the fingerprints the plug-in serves and pins them once confirmed", async () => {
      const user = userEvent.setup();
      registrations = [
        buildRegistration({ jwks: null, jwks_uri: "https://gh.example.com/jwks.json" }),
      ];
      const pinned = { keys: [{ kty: "OKP", crv: "Ed25519", kid: "gh-1", x: "def" }] };
      readKeysMutate.mockImplementation((_id, { onSuccess }) =>
        onSuccess([{ kid: "gh-1", fingerprint: "NzbLsXh8uDCcd-6MNwXF4W_7noWXFZAfHkxZsRGC9Xs" }])
      );
      connectMutate.mockImplementation((_vars, { onSuccess }) =>
        onSuccess(buildRegistration({ jwks: pinned }))
      );
      await renderPluginPage();

      await user.click(screen.getByRole("button", { name: "Connect" }));

      expect(readKeysMutate).toHaveBeenCalledWith(1, expect.anything());
      const shown = screen.getByRole("region", { name: "Keys the plug-in serves" });
      expect(within(shown).getByText("Key id: gh-1")).toBeInTheDocument();
      expect(
        within(shown).getByText("NzbLsXh8uDCcd-6MNwXF4W_7noWXFZAfHkxZsRGC9Xs")
      ).toBeInTheDocument();
      // Reading stores nothing.
      expect(connectMutate).not.toHaveBeenCalled();

      await user.click(within(shown).getByRole("button", { name: "Pin these keys" }));

      expect(connectMutate).toHaveBeenCalledWith(
        {
          registrationId: 1,
          keys: [{ kid: "gh-1", fingerprint: "NzbLsXh8uDCcd-6MNwXF4W_7noWXFZAfHkxZsRGC9Xs" }],
        },
        expect.anything()
      );
      expect(screen.queryByRole("region", { name: "Keys the plug-in serves" })).toBeNull();
      // The pinned set is what the box now holds, in place of the address.
      expect(screen.getByLabelText("Key set address")).toHaveValue("");
      expect(
        JSON.parse(
          String(screen.getByLabelText<HTMLTextAreaElement>("Pasted key set (JWKS)").value)
        )
      ).toEqual(pinned);
    });

    it("waits to connect until a new base URL is saved", async () => {
      const user = userEvent.setup();
      registrations = [buildRegistration()];
      await renderPluginPage();

      const baseUrl = screen.getByLabelText("Base URL");
      await user.clear(baseUrl);
      await user.type(baseUrl, "http://initiative-github-2:8080");

      expect(screen.getByRole("button", { name: "Connect" })).toBeDisabled();
      expect(screen.getByText("Save the new base URL, then connect.")).toBeInTheDocument();

      await user.clear(baseUrl);
      await user.type(baseUrl, "http://initiative-github:8080/");

      expect(screen.getByRole("button", { name: "Connect" })).toBeEnabled();
      expect(screen.queryByText("Save the new base URL, then connect.")).toBeNull();
    });

    describe("a base URL moved after its keys were pinned", () => {
      const pinned = { keys: [{ kty: "OKP", crv: "Ed25519", kid: "gh-1", x: "def" }] };

      const pinThenMove = async () => {
        const user = userEvent.setup();
        registrations = [buildRegistration({ jwks: null })];
        readKeysMutate.mockImplementation((_id, { onSuccess }) =>
          onSuccess([{ kid: "gh-1", fingerprint: "abc" }])
        );
        connectMutate.mockImplementation((_vars, { onSuccess }) =>
          onSuccess(buildRegistration({ jwks: pinned }))
        );
        await renderPluginPage();

        await user.click(screen.getByRole("button", { name: "Connect" }));
        await user.click(screen.getByRole("button", { name: "Pin these keys" }));
        const baseUrl = screen.getByLabelText("Base URL");
        await user.clear(baseUrl);
        await user.type(baseUrl, "http://initiative-github-2:8080");
        return user;
      };

      it("clears the pinned set, so the new address is connected on its own", async () => {
        const user = await pinThenMove();

        await user.click(screen.getByRole("button", { name: "Save" }));

        const data = updateMutate.mock.calls[0][0].data;
        expect(data.base_url).toBe("http://initiative-github-2:8080");
        expect(data.jwks).toEqual({});
      });

      it("sends a set the operator pasted in its place", async () => {
        const user = await pinThenMove();
        const pasted = { keys: [{ kty: "OKP", crv: "Ed25519", kid: "gh-2", x: "ghi" }] };

        const box = screen.getByLabelText("Pasted key set (JWKS)");
        await user.clear(box);
        await user.click(box);
        await user.paste(JSON.stringify(pasted));
        await user.click(screen.getByRole("button", { name: "Save" }));

        expect(updateMutate.mock.calls[0][0].data.jwks).toEqual(pasted);
      });
    });

    it("says why a connect was refused and asks for a fresh look", async () => {
      const user = userEvent.setup();
      registrations = [buildRegistration()];
      readKeysMutate.mockImplementation((_id, { onSuccess }) =>
        onSuccess([{ kid: "gh-1", fingerprint: "abc" }])
      );
      connectMutate.mockImplementation((_vars, { onError }) =>
        onError({
          isAxiosError: true,
          response: { data: { detail: "PLUGIN_SERVICE_KEYS_CHANGED" } },
        })
      );
      await renderPluginPage();

      await user.click(screen.getByRole("button", { name: "Connect" }));
      await user.click(screen.getByRole("button", { name: "Pin these keys" }));

      expect(
        await screen.findByText(/The plug-in's keys changed after you checked them/)
      ).toBeInTheDocument();
      expect(screen.queryByRole("region", { name: "Keys the plug-in serves" })).toBeNull();
    });

    it("clears the pasted key set when the box is emptied", async () => {
      const user = userEvent.setup();
      registrations = [buildRegistration()];
      await renderPluginPage();

      await user.clear(screen.getByLabelText("Pasted key set (JWKS)"));
      await user.click(screen.getByRole("button", { name: "Save" }));

      expect(updateMutate.mock.calls[0][0].data.jwks).toEqual({});
    });
  });

  describe("suspending everywhere", () => {
    it("confirms before suspending a plug-in, and says what suspending means", async () => {
      const user = userEvent.setup();
      registrations = [buildRegistration()];
      await renderPluginPage();

      await user.click(screen.getByRole("button", { name: "Suspend everywhere" }));

      // Nothing has happened yet.
      expect(updateMutate).not.toHaveBeenCalled();

      const dialog = await screen.findByRole("alertdialog");
      expect(within(dialog).getByText("Suspend core.github everywhere?")).toBeInTheDocument();
      expect(
        within(dialog).getByText(/in every community at once and hides it/)
      ).toBeInTheDocument();
      expect(within(dialog).getByText(/Nothing is deleted/)).toBeInTheDocument();

      await user.click(within(dialog).getByRole("button", { name: "Suspend everywhere" }));

      expect(updateMutate).toHaveBeenCalledWith(
        { registrationId: 1, data: { suspended: true } },
        expect.anything()
      );
    });

    it("lifts a suspension without a confirmation", async () => {
      const user = userEvent.setup();
      registrations = [buildRegistration({ suspended_at: "2026-11-15T12:00:00Z" })];
      await renderPluginPage();

      expect(screen.getByText(/cut off in every community/)).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Suspend everywhere" })).toBeNull();
      await user.click(screen.getByRole("button", { name: "Lift suspension" }));

      expect(screen.queryByRole("alertdialog")).toBeNull();
      expect(updateMutate).toHaveBeenCalledWith(
        { registrationId: 1, data: { suspended: false } },
        expect.anything()
      );
    });
  });

  describe("delete", () => {
    it("names what is lost and holds out for the plug-in identifier", async () => {
      const user = userEvent.setup();
      registrations = [buildRegistration()];
      await renderPluginPage();

      await user.click(screen.getByRole("button", { name: "Delete" }));

      const dialog = await screen.findByRole("alertdialog");
      expect(within(dialog).getByText(/removed for good/)).toBeInTheDocument();

      const confirm = within(dialog).getByRole("button", { name: "Delete" });
      expect(confirm).toBeDisabled();

      await user.type(
        within(dialog).getByLabelText("Type the plug-in identifier to confirm"),
        "core.github"
      );
      await user.click(confirm);

      expect(deleteMutate).toHaveBeenCalledWith(1, expect.anything());
    });
  });
});

describe("IndexPage", () => {
  it("does not land an plugins-only operator on settings they cannot manage", async () => {
    const { IndexPage } = await import("@/pages/platform/IndexPage");
    renderPage(IndexPage, {
      auth: { user: buildUser({ role: "owner", capabilities: ["plugins.manage"] }) },
      initialRoute: "/settings/platform",
    });
    // Authentication settings belong to config.manage. Rendering them here
    // would contradict the tab this operator's own capability selects.
    await waitFor(() =>
      expect(screen.queryByRole("heading", { name: /authentication/i })).toBeNull()
    );
  });
});

describe("VendorSetupPage", () => {
  it("hands GitHub's code and the setup's state to the server once", async () => {
    const { VendorSetupPage } = await import("./VendorSetupPage");
    renderPage(VendorSetupPage, {
      auth: { user: buildUser({ role: "owner", capabilities: ["plugins.manage"] }) },
      initialRoute: "/settings/platform/integrations/vendor-setup/$registrationId",
      routeParams: { registrationId: "7" },
      routerSearch: { code: "abc123", state: "st" },
    });

    await waitFor(() =>
      expect(completeSetupMutate).toHaveBeenCalledWith(
        { registrationId: 7, code: "abc123", state: "st" },
        expect.anything()
      )
    );
    expect(completeSetupMutate).toHaveBeenCalledTimes(1);
  });

  it("says the setup failed when GitHub sent no code", async () => {
    const { VendorSetupPage } = await import("./VendorSetupPage");
    renderPage(VendorSetupPage, {
      auth: { user: buildUser({ role: "owner", capabilities: ["plugins.manage"] }) },
      initialRoute: "/settings/platform/integrations/vendor-setup/$registrationId",
      routeParams: { registrationId: "7" },
    });

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Could not save the GitHub App's values."
    );
    expect(completeSetupMutate).not.toHaveBeenCalled();
  });
});
