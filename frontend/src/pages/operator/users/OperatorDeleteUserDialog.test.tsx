import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildUser } from "@/__tests__/factories";
import { server } from "@/__tests__/helpers/msw-server";
import { renderWithProviders } from "@/__tests__/helpers/render";
import type {
  OperatorDeletionEligibilityResponse,
  OperatorUserRead,
} from "@/api/generated/initiativeAPI.schemas";

import { OperatorDeleteUserDialog } from "./OperatorDeleteUserDialog";

const targetUser: OperatorUserRead = {
  ...buildUser({ id: 42, status: "active" }),
  email: "sole-admin@example.com",
  purge_at: null,
  sign_in_locked_until: null,
  second_factor_enrolled: false,
  api_key_count: 0,
  allowed_actions: ["delete"],
  open_case_count: 0,
};

const eligibilityWithCommunityBlocker: OperatorDeletionEligibilityResponse = {
  can_delete: false,
  last_owner: false,
  community_blockers: [{ community_id: 77, community_name: "Lone Community" }],
};

const eligibilityClear: OperatorDeletionEligibilityResponse = {
  can_delete: true,
  last_owner: false,
  community_blockers: [],
};

describe("OperatorDeleteUserDialog community blocker resolution", () => {
  beforeEach(() => {
    let eligibilityCalls = 0;
    server.use(
      http.get("/api/v1/operator/users/42/deletion-eligibility", () => {
        eligibilityCalls += 1;
        // First check: blocked by the community. Once the seat is resolved
        // inside the community, checking again comes back clear.
        return HttpResponse.json(
          eligibilityCalls === 1 ? eligibilityWithCommunityBlocker : eligibilityClear
        );
      })
    );
  });

  it("sends the operator into the community and checks again", async () => {
    const user = userEvent.setup();
    renderWithProviders(
      <OperatorDeleteUserDialog
        open={true}
        onOpenChange={vi.fn()}
        onSuccess={vi.fn()}
        targetUser={targetUser}
      />,
      { auth: { user: buildUser({ role: "owner" }) } }
    );

    // Step 1 → Next runs the eligibility check and lands on resolve-blockers.
    await user.click(await screen.findByRole("button", { name: /next/i }));
    expect(await screen.findByText(/Lone Community/)).toBeInTheDocument();

    // The seat is resolved inside the community, under break-glass; the
    // dialog says so and offers nothing that acts on the community itself.
    expect(screen.getByText(/break glass into the community/i)).toBeInTheDocument();
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /delete community/i })).not.toBeInTheDocument();

    // Checking again picks up the resolved blocker and moves on to confirm.
    await user.click(screen.getByRole("button", { name: /check again/i }));
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: /check again/i })).not.toBeInTheDocument()
    );
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByLabelText(/Type\s+USER-\d+\s+to confirm/)).toBeInTheDocument();
  });
});
