import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildUser } from "@/__tests__/factories";
import { renderPage, renderWithProviders } from "@/__tests__/helpers/render";
import type { PluginServiceRegistrationRead } from "@/api/generated/initiativeAPI.schemas";

const buildRegistration = (
  overrides: Partial<PluginServiceRegistrationRead> = {}
): PluginServiceRegistrationRead => ({
  id: 1,
  public_id: "core.github",
  listing_uid: "gh7k2m9p4q1x8z",
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
  operations_only: false,
  shared_routes: false,
  enabled: true,
  source: "operator",
  image_digest: null,
  compose_service: null,
  compose_base_url: null,
  vendor_fields: [],
  vendor_values: {},
  vendor_set: [],
  vendor_ready: true,
  vendor_setup: null,
  connection_callback_url: "https://initiative.example.com/api/v1/plugin-connections/callback",
  connection_setup_url: "https://initiative.example.com/api/v1/plugin-connections/setup",
  webhook_url: "https://initiative.example.com/api/v1/plugin-hooks/core.github",
  live: true,
  created_at: "2026-08-01T00:00:00.000Z",
  updated_at: "2026-08-12T09:00:00.000Z",
  ...overrides,
});

// Flipped per test before rendering; read lazily inside the mocked hook.
let registrations: PluginServiceRegistrationRead[] = [];

const createMutate = vi.fn();
const updateMutate = vi.fn();
const deleteMutate = vi.fn();
const readKeysMutate = vi.fn();
const connectMutate = vi.fn();
const startSetupMutate = vi.fn();
const completeSetupMutate = vi.fn();

vi.mock("@/lib/mascotToast", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

vi.mock("@/hooks/usePluginServices", () => ({
  usePluginServices: () => ({ data: registrations, isLoading: false, isError: false }),
  useCreatePluginService: () => ({ mutate: createMutate, isPending: false }),
  useUpdatePluginService: () => ({ mutate: updateMutate, isPending: false }),
  useDeletePluginService: () => ({ mutate: deleteMutate, isPending: false }),
  usePluginServiceKeys: () => ({ mutate: readKeysMutate, isPending: false }),
  useConnectPluginService: () => ({ mutate: connectMutate, isPending: false }),
  useStartVendorSetup: () => ({ mutate: startSetupMutate, isPending: false }),
  useCompleteVendorSetup: () => ({ mutate: completeSetupMutate, isPending: false }),
}));

import { PluginServicesPage } from "./PluginServicesPage";

const renderAsOperator = () =>
  renderWithProviders(<PluginServicesPage />, {
    auth: { user: buildUser({ role: "owner", capabilities: ["plugins.manage"] }) },
  });

describe("PluginServicesPage", () => {
  beforeEach(() => {
    registrations = [];
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

  describe("whether a plug-in is live", () => {
    it("labels each registration live or not, with its publisher and listing", () => {
      registrations = [
        buildRegistration({
          id: 1,
          public_id: "core.github",
          live: true,
          scope_ceiling: ["projects:read", "projects:write"],
        }),
        // No key set, pasted or by address, so it cannot be live.
        buildRegistration({
          id: 2,
          public_id: "core.slack",
          listing_uid: "sl4ck0000000aa",
          jwks: null,
          jwks_uri: null,
          live: false,
        }),
      ];
      renderAsOperator();

      const [github, slack] = screen.getAllByRole("listitem");
      expect(within(github).getByText("Live")).toBeInTheDocument();
      expect(within(github).getByText(/Publisher: Core Plug-ins/)).toBeInTheDocument();
      expect(within(github).getByText("gh7k2m9p4q1x8z")).toBeInTheDocument();
      // The ceiling is the listing's, shown and not edited.
      expect(
        within(github).getByText("Scopes, from its listing: projects:read, projects:write")
      ).toBeInTheDocument();
      expect(within(github).queryByText(/Not live until it has signing keys/)).toBeNull();

      expect(within(slack).getByText("Not live")).toBeInTheDocument();
      expect(within(slack).getByText("sl4ck0000000aa")).toBeInTheDocument();
      expect(within(slack).getByText(/Not live until it has signing keys/)).toBeInTheDocument();
    });

    it("says when the publisher is switched off", () => {
      registrations = [
        buildRegistration({ publisher_name: "Acme", publisher_enabled: false, live: false }),
      ];
      renderAsOperator();

      expect(screen.getByText("Not live")).toBeInTheDocument();
      expect(screen.getByText("Publisher switched off")).toBeInTheDocument();
      expect(
        screen.getByText(/Every plug-in from Acme is stopped because its publisher is switched off/)
      ).toBeInTheDocument();
    });

    it("offers no handshake to run", () => {
      registrations = [buildRegistration()];
      renderAsOperator();

      expect(screen.queryByRole("button", { name: "Verify" })).toBeNull();
    });
  });

  describe("reach", () => {
    it("shows mandatory and operations-only on the registrations that carry them", () => {
      registrations = [
        buildRegistration({ id: 1, public_id: "core.automation", mandatory: true }),
        buildRegistration({ id: 2, public_id: "acme.shopify" }),
        buildRegistration({ id: 3, public_id: "acme.sales", operations_only: true }),
      ];
      renderAsOperator();

      // Scannable on the row...
      expect(screen.getByText("In every community")).toBeInTheDocument();
      // ...and spelled out, because a reviewer has to know what it means.
      expect(
        screen.getByText(
          "Installed into every community automatically. Community admins cannot remove it or turn it off."
        )
      ).toBeInTheDocument();
      expect(screen.getByText("Operations community only")).toBeInTheDocument();
    });

    it("says a mandatory operations-only plug-in is installed in the operations community alone", () => {
      registrations = [buildRegistration({ mandatory: true, operations_only: true })];
      renderAsOperator();

      expect(screen.getByText("In the operations community")).toBeInTheDocument();
      expect(screen.queryByText("In every community")).toBeNull();
      expect(screen.queryByText("Operations community only")).toBeNull();
      expect(screen.queryByText(/Installed into every community/)).toBeNull();
      expect(
        screen.getByText(/added to the operations community only, and its admins cannot remove it/)
      ).toBeInTheDocument();
    });

    it("confers no powers beyond the scope ceiling", async () => {
      const user = userEvent.setup();
      renderAsOperator();

      await user.click(screen.getByRole("button", { name: "Add plug-in service" }));
      await screen.findByLabelText("Plug-in identifier");

      // Two switches in the operator's box: whether only the operations
      // community gets it, and whether every community does.
      expect(within(screen.getByRole("dialog")).getAllByRole("switch")).toHaveLength(2);
    });
  });

  describe("registering", () => {
    const fillNewService = async () => {
      const user = userEvent.setup();
      renderAsOperator();

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
          operations_only: false,
        },
        expect.anything()
      );
    });

    it("registers it for the operations community only", async () => {
      const user = await fillNewService();

      await user.click(screen.getByRole("switch", { name: "Only the operations community" }));
      await user.click(screen.getByRole("button", { name: "Save" }));

      expect(createMutate).toHaveBeenCalledWith(
        expect.objectContaining({ operations_only: true, mandatory: false }),
        expect.anything()
      );
    });

    it("asks for no shared secret", async () => {
      const user = userEvent.setup();
      renderAsOperator();

      await user.click(screen.getByRole("button", { name: "Add plug-in service" }));
      await screen.findByLabelText("Plug-in identifier");

      expect(screen.queryByText(/shared secret/i)).toBeNull();
      expect(document.querySelector('input[type="password"]')).toBeNull();
      // Connect reads from a saved base URL, so a new one has nothing to read.
      expect(screen.queryByRole("button", { name: "Connect" })).toBeNull();
    });

    it("sends the browser address when the plug-in is published somewhere else", async () => {
      const user = userEvent.setup();
      renderAsOperator();

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

  describe("editing", () => {
    it("sends the key set address and keeps the pasted set", async () => {
      const user = userEvent.setup();
      registrations = [buildRegistration({ jwks_uri: "https://gh.example.com/jwks.json" })];
      renderAsOperator();

      await user.click(screen.getByRole("button", { name: "Edit" }));
      // Emptying the address clears it rather than leaving it stored.
      await user.clear(await screen.findByLabelText("Key set address"));
      await user.click(screen.getByRole("button", { name: "Save" }));

      const data = updateMutate.mock.calls[0][0].data;
      expect(data).toMatchObject({ jwks_uri: "" });
      expect(data).not.toHaveProperty("listing_uid");
      // The stored key set is shown in the box and sent back as it was.
      expect(data.jwks).toEqual(registrations[0].jwks);
      expect(data).not.toHaveProperty("secret");
    });

    it("keeps operations-only through an unrelated edit", async () => {
      const user = userEvent.setup();
      registrations = [buildRegistration({ operations_only: true })];
      renderAsOperator();

      await user.click(screen.getByRole("button", { name: "Edit" }));
      await user.type(
        await screen.findByLabelText("Key set address"),
        "https://gh.example.com/jwks.json"
      );
      await user.click(screen.getByRole("button", { name: "Save" }));

      expect(updateMutate.mock.calls[0][0].data).toMatchObject({
        jwks_uri: "https://gh.example.com/jwks.json",
        operations_only: true,
      });
    });

    it("saves operations-only off once switched off", async () => {
      const user = userEvent.setup();
      registrations = [buildRegistration({ operations_only: true })];
      renderAsOperator();

      await user.click(screen.getByRole("button", { name: "Edit" }));
      const operationsOnly = await screen.findByRole("switch", {
        name: "Only the operations community",
      });
      expect(operationsOnly).toBeChecked();
      await user.click(operationsOnly);
      await user.click(screen.getByRole("button", { name: "Save" }));

      expect(updateMutate.mock.calls[0][0].data).toMatchObject({ operations_only: false });
    });

    it("asks for the vendor values and sharing, keeping a secret left alone", async () => {
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
      renderAsOperator();

      await user.click(screen.getByRole("button", { name: "Edit" }));
      const clientId = await screen.findByLabelText(/Client id/);
      expect(clientId).toHaveValue("gh-app");
      // A stored secret is never sent back, only that it is set.
      const secret = screen.getByLabelText(/Secret/);
      expect(secret).toHaveValue("");
      expect(secret).toHaveAttribute("placeholder", "Set. Type to replace it.");
      // Where the vendor sends people back, to register with it.
      expect(screen.getByLabelText("Callback address")).toHaveValue(
        "https://initiative.example.com/api/v1/plugin-connections/callback"
      );
      expect(screen.getByLabelText("Setup address")).toHaveValue(
        "https://initiative.example.com/api/v1/plugin-connections/setup"
      );
      expect(screen.getByLabelText("Webhook address")).toHaveValue(
        "https://initiative.example.com/api/v1/plugin-hooks/core.github"
      );

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
      renderAsOperator();

      expect(screen.getByText(/makes this plug-in's calls itself/)).toBeInTheDocument();
      expect(screen.queryByText(/give the address where you run it/)).toBeNull();
      await user.click(screen.getByRole("button", { name: "Edit" }));
      await user.type(await screen.findByLabelText(/Client id/), "gh-app");
      expect(screen.queryByLabelText("Base URL")).toBeNull();
      expect(screen.queryByLabelText("Pasted key set (JWKS)")).toBeNull();
      await user.click(screen.getByRole("button", { name: "Save" }));

      expect(updateMutate.mock.calls[0][0].data).toEqual({
        mandatory: false,
        operations_only: false,
        shared_routes: false,
        vendor_values: { client_id: "gh-app" },
      });
    });

    it("shows the compose service to copy, and its address as the base URL", async () => {
      const user = userEvent.setup();
      const service = "github:\n  image: ghcr.io/beyonders-studio/github@sha256:abc\n";
      registrations = [
        buildRegistration({
          base_url: null,
          compose_service: service,
          compose_base_url: "http://github:8080",
        }),
      ];
      renderAsOperator();

      await user.click(screen.getByRole("button", { name: "Edit" }));
      const snippet = await screen.findByLabelText("Compose service");
      expect(snippet).toHaveValue(service);
      expect(snippet).toHaveAttribute("readonly");
      expect(screen.getByRole("button", { name: "Copy" })).toBeInTheDocument();
      expect(screen.getByLabelText("Base URL")).toHaveValue("http://github:8080");
    });

    it("creates the GitHub App at GitHub, posting its manifest there", async () => {
      const user = userEvent.setup();
      const submit = vi.spyOn(HTMLFormElement.prototype, "submit").mockImplementation(() => {});
      registrations = [
        buildRegistration({
          vendor_setup: "github_app_manifest",
          vendor_fields: [{ key: "client_id", type: "string", required: true, label: {} }],
        }),
      ];
      startSetupMutate.mockImplementation((_vars, { onSuccess }) =>
        onSuccess({
          action: "https://github.com/organizations/acme/settings/apps/new",
          manifest: '{"name":"GitHub"}',
          state: "st/ate",
        })
      );
      renderAsOperator();

      await user.click(screen.getByRole("button", { name: "Edit" }));
      await user.type(await screen.findByLabelText("GitHub organization"), "acme");
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
    });

    it("offers no GitHub App to a plug-in whose listing has no setup", async () => {
      const user = userEvent.setup();
      registrations = [
        buildRegistration({
          vendor_fields: [{ key: "client_id", type: "string", required: true, label: {} }],
        }),
      ];
      renderAsOperator();

      await user.click(screen.getByRole("button", { name: "Edit" }));
      await screen.findByLabelText(/client_id/);
      expect(screen.queryByRole("button", { name: "Create the GitHub App" })).toBeNull();
    });

    it("says a registration waits on its vendor values", () => {
      registrations = [buildRegistration({ vendor_ready: false, live: false })];
      renderAsOperator();

      expect(screen.getByText(/Not live until its vendor client is set/)).toBeInTheDocument();
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
      renderAsOperator();

      await user.click(screen.getByRole("button", { name: "Edit" }));
      await user.click(await screen.findByRole("button", { name: "Connect" }));

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
      renderAsOperator();

      await user.click(screen.getByRole("button", { name: "Edit" }));
      const baseUrl = await screen.findByLabelText("Base URL");
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
        renderAsOperator();

        await user.click(screen.getByRole("button", { name: "Edit" }));
        await user.click(await screen.findByRole("button", { name: "Connect" }));
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
      renderAsOperator();

      await user.click(screen.getByRole("button", { name: "Edit" }));
      await user.click(await screen.findByRole("button", { name: "Connect" }));
      await user.click(screen.getByRole("button", { name: "Pin these keys" }));

      expect(
        await screen.findByText(/The plug-in's keys changed after you checked them/)
      ).toBeInTheDocument();
      expect(screen.queryByRole("region", { name: "Keys the plug-in serves" })).toBeNull();
    });

    it("clears the pasted key set when the box is emptied", async () => {
      const user = userEvent.setup();
      registrations = [buildRegistration()];
      renderAsOperator();

      await user.click(screen.getByRole("button", { name: "Edit" }));
      await user.clear(await screen.findByLabelText("Pasted key set (JWKS)"));
      await user.click(screen.getByRole("button", { name: "Save" }));

      expect(updateMutate.mock.calls[0][0].data.jwks).toEqual({});
    });
  });

  describe("the operator kill switch", () => {
    it("confirms before stopping a plug-in, and says what stopping means", async () => {
      const user = userEvent.setup();
      registrations = [buildRegistration()];
      renderAsOperator();

      await user.click(screen.getByRole("switch"));

      // Nothing has happened yet.
      expect(updateMutate).not.toHaveBeenCalled();

      const dialog = await screen.findByRole("alertdialog");
      expect(within(dialog).getByText("Disable core.github?")).toBeInTheDocument();
      expect(within(dialog).getByText(/stops reaching it immediately/)).toBeInTheDocument();
      expect(within(dialog).getByText(/Nothing is deleted/)).toBeInTheDocument();

      await user.click(within(dialog).getByRole("button", { name: "Disable plug-in service" }));

      expect(updateMutate).toHaveBeenCalledWith(
        { registrationId: 1, data: { enabled: false } },
        expect.anything()
      );
    });

    it("turns a plug-in back on without a confirmation", async () => {
      const user = userEvent.setup();
      registrations = [buildRegistration({ enabled: false })];
      renderAsOperator();

      await user.click(screen.getByRole("switch"));

      expect(screen.queryByRole("alertdialog")).toBeNull();
      expect(updateMutate).toHaveBeenCalledWith(
        { registrationId: 1, data: { enabled: true } },
        expect.anything()
      );
    });
  });

  describe("delete", () => {
    it("names what is lost and holds out for the plug-in identifier", async () => {
      const user = userEvent.setup();
      registrations = [buildRegistration()];
      renderAsOperator();

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
    const { VendorSetupPage } = await import("@/pages/platform/integrations/VendorSetupPage");
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
    const { VendorSetupPage } = await import("@/pages/platform/integrations/VendorSetupPage");
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
