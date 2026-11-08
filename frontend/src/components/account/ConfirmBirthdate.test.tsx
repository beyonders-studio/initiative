/**
 * The screen an account meets once, with no date of birth on file.
 *
 * What it must say is the point: the date is kept encrypted, used only for age
 * limits, and not sold — and, where the deployment has a privacy policy (it is
 * linked to billing), that policy is one click away.
 */
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/__tests__/helpers/render";

const config = vi.hoisted(() => ({ billing: null as { url: string } | null }));
const logout = vi.fn();

vi.mock("@/api/client", () => ({ apiClient: { post: vi.fn() } }));
vi.mock("@/hooks/useAppConfig", () => ({
  useAppConfig: () => ({ billing: config.billing }),
}));
vi.mock("@/hooks/useLegalDocuments", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/hooks/useLegalDocuments")>()),
  useLegalIndex: () => ({
    enabled: Boolean(config.billing),
    documents: config.billing ? [{ slug: "privacy", title: "Privacy Policy" }] : [],
    requiredDocuments: [],
    isLoading: false,
  }),
}));

import { ConfirmBirthdate } from "@/components/account/ConfirmBirthdate";

const render = () => renderWithProviders(<ConfirmBirthdate />, { auth: { logout } });

describe("ConfirmBirthdate", () => {
  beforeEach(() => {
    config.billing = null;
    logout.mockReset();
  });

  it("says plainly what is done with the date, and that data is not sold", () => {
    render();

    expect(screen.getByText("How old are you?")).toBeInTheDocument();
    expect(screen.getByText(/We don't sell your data\./)).toBeInTheDocument();
    expect(screen.getByText(/encrypted and use it only to check age limits/)).toBeInTheDocument();
  });

  it("links the privacy policy where billing is linked", () => {
    config.billing = { url: "https://billing.example.test" };
    render();

    expect(screen.getByRole("link", { name: "Privacy Policy" })).toHaveAttribute(
      "href",
      "/legal/privacy"
    );
  });

  it("links nothing where there is no billing, and so no policy", () => {
    render();

    expect(screen.queryByRole("link", { name: "Privacy Policy" })).not.toBeInTheDocument();
  });

  it("asks nothing it can be talked past: the only other way off is signing out", async () => {
    render();

    expect(screen.getByRole("button", { name: "Continue" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Sign out" }));
    expect(logout).toHaveBeenCalled();
  });
});
