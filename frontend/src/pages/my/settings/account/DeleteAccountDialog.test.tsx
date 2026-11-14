import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { describe, expect, it, vi } from "vitest";

import { buildUser } from "@/__tests__/factories";
import { server } from "@/__tests__/helpers/msw-server";
import { renderWithProviders } from "@/__tests__/helpers/render";
import type { DeletionEligibilityResponse } from "@/api/generated/initiativeAPI.schemas";

import { DeleteAccountDialog } from "./DeleteAccountDialog";

const answer = (eligibility: DeletionEligibilityResponse) =>
  server.use(http.get("/api/v1/me/deletion-eligibility", () => HttpResponse.json(eligibility)));

const renderDialog = () =>
  renderWithProviders(
    <DeleteAccountDialog
      open={true}
      onOpenChange={vi.fn()}
      onSuccess={vi.fn()}
      user={buildUser({ password_required: false })}
      initialAction="soft_delete"
    />
  );

describe("DeleteAccountDialog", () => {
  it("names the last owner and each community the account is the only superadmin of", async () => {
    answer({
      can_delete: false,
      last_owner: true,
      sole_superadmin_communities: ["Lone Community"],
    });
    renderDialog();

    expect(
      await screen.findByText(
        "You are the only superadmin of Lone Community. Make another member superadmin, or delete the community, first."
      )
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "This is the platform's last owner, and the platform keeps one. Make someone else an owner first."
      )
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /next/i })).toBeDisabled();
  });

  it("goes on to the typed phrase once nothing is in the way", async () => {
    const user = userEvent.setup();
    answer({ can_delete: true, last_owner: false, sole_superadmin_communities: [] });
    renderDialog();

    const phrase = await screen.findByLabelText(/DELETE MY ACCOUNT/);
    const submit = screen.getByRole("button", { name: "Delete Account" });
    expect(submit).toBeDisabled();

    await user.type(phrase, "DELETE MY ACCOUNT");
    expect(submit).toBeEnabled();
  });
});
