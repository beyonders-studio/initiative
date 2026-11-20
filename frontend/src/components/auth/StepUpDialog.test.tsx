import { act, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";

import { server } from "@/__tests__/helpers/msw-server";
import { renderWithProviders } from "@/__tests__/helpers/render";
import { AUTH_STEP_UP_EVENT } from "@/api/client";

import { StepUpDialog } from "./StepUpDialog";

const providersResponse = {
  providers: [
    {
      id: 7,
      slug: "corp",
      display_name: "Corp SSO",
      kind: "oidc",
      login_url: "/api/v1/auth/corp/login",
      icon: null,
      button_style: null,
    },
  ],
};

const fireStepUp = (providerSlug: string) => {
  act(() => {
    window.dispatchEvent(new CustomEvent(AUTH_STEP_UP_EVENT, { detail: { providerSlug } }));
  });
};

describe("StepUpDialog", () => {
  it("opens on a step-up event naming the required provider, and dismisses without navigating", async () => {
    server.use(http.get("/api/v1/auth/providers", () => HttpResponse.json(providersResponse)));
    renderWithProviders(<StepUpDialog />);

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    fireStepUp("corp");

    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    // The action button names the provider once the listing resolves the slug
    // to its display name.
    expect(
      await screen.findByRole("button", { name: /sign in with Corp SSO/i })
    ).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /not now/i }));

    await waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });
  });
});
