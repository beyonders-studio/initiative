/**
 * The screen an account meets when it never saw the signup form.
 *
 * It exists for one case — an account an identity provider provisioned on
 * first sign-in — and the thing it must not do is let somebody past without
 * the agreement being recorded. So the button is explicit here, both
 * documents are reachable from it, and the only other way off the screen is
 * signing out.
 */
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/__tests__/helpers/render";

const acceptLegalDocuments = vi.fn();
const refreshUser = vi.fn();
const logout = vi.fn();

vi.mock("@/api/generated/users/users", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/generated/users/users")>()),
  acceptLegalDocuments: () => acceptLegalDocuments(),
}));

vi.mock("@/hooks/useLegalDocuments", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/hooks/useLegalDocuments")>()),
  useLegalIndex: () => ({
    enabled: true,
    documents: [
      { slug: "terms", title: "Terms of Service" },
      { slug: "privacy", title: "Privacy Policy" },
    ],
    requiredDocuments: [
      { slug: "terms", title: "Terms of Service" },
      { slug: "privacy", title: "Privacy Policy" },
    ],
    isLoading: false,
  }),
}));

import { AcceptTerms } from "./AcceptTerms";

const render = () => renderWithProviders(<AcceptTerms />, { auth: { refreshUser, logout } });

describe("AcceptTerms", () => {
  beforeEach(() => {
    acceptLegalDocuments.mockReset().mockResolvedValue(undefined);
    refreshUser.mockReset().mockResolvedValue(undefined);
    logout.mockReset();
  });

  it("offers both documents to read before there is anything to agree to", () => {
    render();

    expect(screen.getByRole("link", { name: "Terms of Service" })).toHaveAttribute(
      "href",
      "/legal/terms"
    );
    expect(screen.getByRole("link", { name: "Privacy Policy" })).toHaveAttribute(
      "href",
      "/legal/privacy"
    );
  });

  it("records the agreement and re-reads the account", async () => {
    render();

    await userEvent.click(screen.getByRole("button", { name: /i agree/i }));

    await waitFor(() => expect(acceptLegalDocuments).toHaveBeenCalled());
    // The screen is drawn from the account's own record, so it only goes away
    // once the account has been read again.
    expect(refreshUser).toHaveBeenCalled();
  });

  it("offers signing out rather than a decline", () => {
    render();

    // A decline button would have to mean something — deleting the account, or
    // leaving it in a state nothing else in the app knows about. Signing out is
    // the honest version and they can already do it.
    expect(screen.getByRole("button", { name: /sign out/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /decline|no thanks/i })).not.toBeInTheDocument();
  });

  it("says so and stays put when the agreement could not be recorded", async () => {
    acceptLegalDocuments.mockRejectedValue(new Error("nope"));
    render();

    await userEvent.click(screen.getByRole("button", { name: /i agree/i }));

    expect(await screen.findByText(/couldn't record that/i)).toBeInTheDocument();
    expect(refreshUser).not.toHaveBeenCalled();
  });
});
