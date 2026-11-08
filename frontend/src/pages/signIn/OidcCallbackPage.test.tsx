/**
 * What the callback says when a sign-in came back as a code.
 *
 * The backend redirects here with a machine-readable code in the query string.
 * The page used to print whatever it was handed, so a person met
 * `OIDC_ACCOUNT_INACTIVE` rather than a sentence. It reads the code through the
 * error messages now, and falls back to the code only where no sentence exists.
 */
import { screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderPage } from "@/__tests__/helpers/render";

import { OidcCallbackPage } from "./OidcCallbackPage";

const renderWithError = (error: string) =>
  renderPage(OidcCallbackPage, { initialRoute: "/oidc/callback", routerSearch: { error } });

describe("OidcCallbackPage", () => {
  it("says what a code it has a sentence for means", async () => {
    renderWithError("OIDC_ACCOUNT_INACTIVE");

    await waitFor(() => {
      expect(screen.getByText(/deactivated/i)).toBeInTheDocument();
    });
    expect(screen.queryByText(/OIDC_ACCOUNT_INACTIVE/)).not.toBeInTheDocument();
  });

  it("says what the session-store refusal means", async () => {
    renderWithError("OIDC_SESSION_STORE_UNAVAILABLE");

    await waitFor(() => {
      expect(screen.getByText(/couldn't start your session/i)).toBeInTheDocument();
    });
  });

  it("falls back to the code itself when there is no sentence for it", async () => {
    renderWithError("SOMETHING_NOBODY_WROTE_A_MESSAGE_FOR");

    await waitFor(() => {
      expect(screen.getByText(/SOMETHING_NOBODY_WROTE_A_MESSAGE_FOR/)).toBeInTheDocument();
    });
  });
});
