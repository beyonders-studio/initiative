import { fireEvent, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/__tests__/helpers/render";
import type {
  AuthProviderOwnerRead,
  AuthProviderProbeResult,
} from "@/api/generated/initiativeAPI.schemas";

const createMutate = vi.fn();
const updateMutate = vi.fn();
const deleteMutate = vi.fn();
const testMutate = vi.fn();
const discoverMutate = vi.fn();

let providersData: AuthProviderOwnerRead[] = [];

vi.mock("@/hooks/useSettings", () => ({
  useAuthProviders: () => ({ data: providersData, isLoading: false }),
  useCreateAuthProvider: () => ({ mutate: createMutate, isPending: false }),
  useUpdateAuthProvider: () => ({ mutate: updateMutate, isPending: false }),
  useDeleteAuthProvider: () => ({ mutate: deleteMutate, isPending: false }),
  useTestAuthProvider: () => ({ mutate: testMutate, isPending: false }),
  useDiscoverAuthProvider: () => ({ mutate: discoverMutate, isPending: false }),
}));

import { AuthProvidersSection } from "./AuthProvidersSection";

const platformRow: AuthProviderOwnerRead = {
  id: 1,
  slug: "oidc",
  display_name: "Okta",
  kind: "oidc",
  enabled: true,
  issuer: "https://idp.example.com",
  client_id: "client-1",
  scopes: "openid email",
  role_claim_path: null,
  allow_jit: true,
  asserts_second_factor: false,
  icon: null,
  button_style: null,
  secret_set: true,
  callback_url: "https://app.example.com/api/v1/auth/oidc/callback",
};

const corpRow: AuthProviderOwnerRead = {
  ...platformRow,
  id: 2,
  slug: "corp",
  display_name: "Corp SSO",
  secret_set: true,
  callback_url: "https://app.example.com/api/v1/auth/corp/callback",
};

const reachable: AuthProviderProbeResult = {
  ok: true,
  error_code: null,
  issuer: "https://id.acme.example",
  authorization_endpoint: "https://id.acme.example/authorize",
  token_endpoint: "https://id.acme.example/token",
  jwks_uri: "https://id.acme.example/jwks",
  userinfo_endpoint: null,
  signing_algs: ["RS256"],
  scopes_supported: ["openid", "email", "profile", "groups"],
  claims_supported: ["sub", "email", "groups"],
  callback_url_template: "https://app.example.com/api/v1/auth/{slug}/callback",
};

const rowFor = (name: string) => screen.getByText(name).closest("li") as HTMLElement;

/** Choose one of a provider row's actions from its menu. */
const choose = async (provider: string, action: string) => {
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: `Actions for ${provider}` }));
  await user.click(screen.getByRole("menuitem", { name: action }));
};

/** Answer the next Verify with `result`. */
const verifyWith = (result: AuthProviderProbeResult) =>
  discoverMutate.mockImplementation((_vars, options) => options?.onSuccess?.(result));

describe("AuthProvidersSection", () => {
  beforeEach(() => {
    createMutate.mockReset();
    updateMutate.mockReset();
    deleteMutate.mockReset();
    testMutate.mockReset();
    discoverMutate.mockReset();
    providersData = [platformRow, corpRow];
  });

  it("offers every provider the same actions, and says whether it is on", async () => {
    providersData = [platformRow, { ...corpRow, enabled: false }];
    const user = userEvent.setup();
    renderWithProviders(<AuthProvidersSection />);

    expect(within(rowFor("Okta")).getByText("On")).toBeInTheDocument();
    expect(within(rowFor("Corp SSO")).getByText("Off")).toBeInTheDocument();

    // The row an install started with is a row: the same menu on each.
    await user.click(screen.getByRole("button", { name: "Actions for Okta" }));
    expect(screen.getAllByRole("menuitem").map((item) => item.textContent)).toEqual([
      "Test",
      "Edit",
      "Delete",
    ]);
  });

  it("shows each provider the address its IdP sends the browser back to", () => {
    renderWithProviders(<AuthProvidersSection />);

    // The address follows the slug, and this row is where the page states it —
    // which is what an operator registers with their IdP.
    expect(
      screen.getByText("https://app.example.com/api/v1/auth/oidc/callback")
    ).toBeInTheDocument();
    expect(
      screen.getByText("https://app.example.com/api/v1/auth/corp/callback")
    ).toBeInTheDocument();
  });

  it("tests a saved provider against the address on its row", async () => {
    renderWithProviders(<AuthProvidersSection />);

    await choose("Corp SSO", "Test");

    // By id: the address is the server's to read off the row, not ours to send.
    expect(testMutate).toHaveBeenCalledTimes(1);
    expect(testMutate.mock.calls[0][0]).toBe(2);
  });

  describe("connecting one", () => {
    const openWizard = () => fireEvent.click(screen.getByRole("button", { name: "Add provider" }));

    /** The preset card, by its accessible name — which is the label, since
     *  the mark beside it is decorative. Scoped to the wizard, because a
     *  provider's name can also be a row's display name behind it. */
    const pickPreset = async (name: string) =>
      fireEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name }));

    it("builds the address from what the preset asks for", async () => {
      verifyWith({ ...reachable, issuer: "https://keycloak.example.com/realms/main" });
      renderWithProviders(<AuthProvidersSection />);
      openWizard();

      await pickPreset("Keycloak");
      fireEvent.change(screen.getByLabelText("Address"), {
        target: { value: "keycloak.example.com" },
      });
      fireEvent.change(screen.getByLabelText("Realm"), { target: { value: "main" } });

      // Nobody edits the middle of a URL: the realm is its own field and the
      // address is assembled from it.
      expect(screen.getByText("https://keycloak.example.com/realms/main")).toBeInTheDocument();
    });

    it("will not go on until the address has answered", async () => {
      renderWithProviders(<AuthProvidersSection />);
      openWizard();

      await pickPreset("Google");

      // Google needs nothing filling in, so Verify is available immediately —
      // but the way forward is not, because nothing has answered yet.
      expect(screen.getByRole("button", { name: "Verify" })).toBeEnabled();
      expect(screen.getByRole("button", { name: /Next: credentials/ })).toBeDisabled();
    });

    it("reports what it found and fills the scopes in from it", async () => {
      verifyWith(reachable);
      renderWithProviders(<AuthProvidersSection />);
      openWizard();

      await pickPreset("Google");
      fireEvent.click(screen.getByRole("button", { name: "Verify" }));

      expect(await screen.findByText("Reachable")).toBeInTheDocument();
      expect(screen.getByText("https://id.acme.example/token")).toBeInTheDocument();

      fireEvent.click(screen.getByRole("button", { name: /Next: credentials/ }));
      fireEvent.change(screen.getByLabelText("Client ID"), { target: { value: "c" } });
      fireEvent.click(screen.getByRole("button", { name: /Next: how it behaves/ }));

      // `groups` was offered, `offline_access` was not, so one is taken and
      // the other is not invented.
      expect((screen.getByLabelText("Scopes") as HTMLInputElement).value).toBe(
        "openid email profile groups"
      );
    });

    it("says what went wrong in the reader's language, not the server's", async () => {
      verifyWith({
        ...reachable,
        ok: false,
        error_code: "AUTH_PROVIDER_DISCOVERY_ISSUER_MISMATCH",
        issuer: null,
      });
      renderWithProviders(<AuthProvidersSection />);
      openWizard();

      await pickPreset("Google");
      fireEvent.click(screen.getByRole("button", { name: "Verify" }));

      expect(await screen.findByText(/answers for a different issuer/i)).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /Next: credentials/ })).toBeDisabled();
    });

    it("puts the tick away when the address is edited after verifying", async () => {
      verifyWith(reachable);
      renderWithProviders(<AuthProvidersSection />);
      openWizard();

      await pickPreset("Okta");
      fireEvent.change(screen.getByLabelText("Okta domain"), {
        target: { value: "dev-1.okta.com" },
      });
      fireEvent.click(screen.getByRole("button", { name: "Verify" }));
      expect(await screen.findByText("Reachable")).toBeInTheDocument();

      fireEvent.change(screen.getByLabelText("Okta domain"), {
        target: { value: "dev-2.okta.com" },
      });

      // A tick beside an address that has since changed would be vouching for
      // something else.
      expect(screen.queryByText("Reachable")).not.toBeInTheDocument();
      expect(screen.getByRole("button", { name: /Next: credentials/ })).toBeDisabled();
    });

    it("connects a provider, carrying the mark its preset chose", async () => {
      verifyWith(reachable);
      renderWithProviders(<AuthProvidersSection />);
      openWizard();

      await pickPreset("Google");
      fireEvent.click(screen.getByRole("button", { name: "Verify" }));
      await screen.findByText("Reachable");
      fireEvent.click(screen.getByRole("button", { name: /Next: credentials/ }));

      // The server's own answer, built from APP_URL — not this page's origin.
      expect(
        screen.getByText("https://app.example.com/api/v1/auth/google/callback")
      ).toBeInTheDocument();

      fireEvent.change(screen.getByLabelText("Client ID"), {
        target: { value: "acme-client" },
      });
      fireEvent.change(screen.getByLabelText("Client secret"), {
        target: { value: "acme-secret" },
      });
      fireEvent.click(screen.getByRole("button", { name: /Next: how it behaves/ }));
      fireEvent.click(screen.getByRole("button", { name: "Connect provider" }));

      expect(createMutate).toHaveBeenCalledTimes(1);
      expect(createMutate.mock.calls[0][0]).toMatchObject({
        slug: "google",
        display_name: "Google",
        // The address discovery reported, which is the one that answered.
        issuer: "https://id.acme.example",
        client_id: "acme-client",
        client_secret: "acme-secret",
        enabled: true,
        allow_jit: true,
        icon: "google",
      });
    });

    it("does not let a late answer vouch for an address that has moved on", async () => {
      // Verify address A, edit to B before the answer lands, and the answer
      // about A must not unlock a form that now shows B.
      let land: () => void = () => {};
      discoverMutate.mockImplementation((vars, options) => {
        land = () =>
          options?.onSuccess?.({
            ...reachable,
            issuer: (vars as { issuer: string }).issuer,
          });
      });

      renderWithProviders(<AuthProvidersSection />);
      openWizard();
      await pickPreset("Okta");

      fireEvent.change(screen.getByLabelText("Okta domain"), {
        target: { value: "dev-1.okta.com" },
      });
      fireEvent.click(screen.getByRole("button", { name: "Verify" }));

      fireEvent.change(screen.getByLabelText("Okta domain"), {
        target: { value: "dev-2.okta.com" },
      });
      land();

      expect(screen.queryByText("Reachable")).not.toBeInTheDocument();
      expect(screen.getByRole("button", { name: /Next: credentials/ })).toBeDisabled();
    });

    it("refuses a slug the server would refuse", async () => {
      verifyWith(reachable);
      renderWithProviders(<AuthProvidersSection />);
      openWizard();

      await pickPreset("Google");
      fireEvent.click(screen.getByRole("button", { name: "Verify" }));
      await screen.findByText("Reachable");
      fireEvent.click(screen.getByRole("button", { name: /Next: credentials/ }));
      fireEvent.change(screen.getByLabelText("Client ID"), { target: { value: "c" } });
      fireEvent.click(screen.getByRole("button", { name: /Next: how it behaves/ }));

      fireEvent.change(screen.getByLabelText("Slug"), { target: { value: "bad-" } });
      fireEvent.click(screen.getByRole("button", { name: "Connect provider" }));

      expect(createMutate).not.toHaveBeenCalled();
      expect(screen.getByText(/no leading or trailing dash/i)).toBeInTheDocument();

      fireEvent.change(screen.getByLabelText("Slug"), { target: { value: "bad" } });
      expect(screen.queryByText(/no leading or trailing dash/i)).not.toBeInTheDocument();
    });
  });

  it("keeps the stored secret when the edit form leaves it blank", async () => {
    renderWithProviders(<AuthProvidersSection />);

    await choose("Corp SSO", "Edit");
    const secret = (await screen.findByLabelText("Client secret")) as HTMLInputElement;
    expect(secret.value).toBe("");
    expect(secret.placeholder).toMatch(/keep the current secret/i);
    fireEvent.change(screen.getByLabelText("Display name"), {
      target: { value: "Corp Renamed" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(updateMutate).toHaveBeenCalledTimes(1);
    const call = updateMutate.mock.calls[0][0];
    expect(call.providerId).toBe(2);
    expect(call.data.display_name).toBe("Corp Renamed");
    expect("client_secret" in call.data).toBe(false);
  });

  it("verifies from the edit form too, without saving anything", async () => {
    verifyWith(reachable);
    renderWithProviders(<AuthProvidersSection />);

    await choose("Corp SSO", "Edit");
    fireEvent.click(await screen.findByRole("button", { name: "Verify" }));

    expect(await screen.findByText("Reachable")).toBeInTheDocument();
    expect(updateMutate).not.toHaveBeenCalled();
  });

  it("deletes after confirmation", async () => {
    renderWithProviders(<AuthProvidersSection />);

    await choose("Corp SSO", "Delete");
    const dialog = await screen.findByRole("alertdialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Delete" }));

    expect(deleteMutate).toHaveBeenCalledTimes(1);
    expect(deleteMutate.mock.calls[0][0]).toBe(2);
  });
});
