/**
 * A connection is used once it names a model, and the model comes from its
 * provider's list, which is read with the saved details. So a connection
 * without one says so, its details save on their own (a mistyped key is
 * corrected before its list can be read), and the dialog stays on the model.
 */

import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/__tests__/helpers/render";
import type { AIConnectionResponse } from "@/api/generated/initiativeAPI.schemas";

import { AIConnectionManager } from "./AIConnectionManager";
import type { ConnectionMutations } from "./aiConnection.types";

const connection = (overrides: Partial<AIConnectionResponse> = {}): AIConnectionResponse => ({
  id: 1,
  scope: "community",
  label: "Team",
  provider: "anthropic",
  base_url: null,
  model: null,
  has_api_key: true,
  enabled: true,
  is_default: true,
  communities: [],
  last_error: null,
  last_error_at: null,
  ...overrides,
});

const mutation = () => ({ mutate: vi.fn(), isPending: false });

const mutations = () =>
  ({
    create: mutation(),
    update: mutation(),
    remove: mutation(),
    test: mutation(),
    fetchModels: mutation(),
  }) as unknown as ConnectionMutations;

const render = (connections: AIConnectionResponse[], given = mutations(), locked = false) =>
  renderWithProviders(
    <AIConnectionManager
      scope="community"
      connections={connections}
      isLoading={false}
      isError={false}
      providers={["anthropic", "openai"]}
      mutations={given}
      locked={locked}
    />
  );

describe("AIConnectionManager", () => {
  it("saves a connection's details and stays on the model until one is picked", async () => {
    const given = mutations();
    vi.mocked(given.update.mutate).mockImplementation((_variables, options) =>
      options?.onSuccess?.(connection(), _variables, undefined, undefined as never)
    );
    render([connection()], given);

    expect(screen.getByText("Needs a model")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Edit" }));
    expect(
      await screen.findByText("Pick a model to finish setting up this connection.")
    ).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Save connection" }));
    expect(given.update.mutate).toHaveBeenCalledOnce();
    expect(screen.getByRole("dialog", { name: "Edit connection" })).toBeInTheDocument();
  });

  it("leaves a connection with a model alone", () => {
    render([connection({ model: "claude-haiku-5-5" })]);

    expect(screen.queryByText("Needs a model")).not.toBeInTheDocument();
    expect(screen.getByText(/claude-haiku-5-5/)).toBeInTheDocument();
    expect(screen.queryByText(/Failing since/)).not.toBeInTheDocument();
  });

  it("turns a connection off from its row and nothing else about it", async () => {
    const given = mutations();
    render([connection({ model: "claude-haiku-5-5" })], given);

    await userEvent.click(screen.getByRole("switch", { name: "Use Team" }));

    expect(given.update.mutate).toHaveBeenCalledWith(
      { connectionId: 1, data: { enabled: false } },
      expect.anything()
    );
  });

  it("keeps every connection off while AI is off, and says where to turn it on", () => {
    render([connection({ model: "claude-haiku-5-5" })], mutations(), true);

    const toggle = screen.getByRole("switch", { name: "Use Team" });
    expect(toggle).not.toBeChecked();
    expect(toggle).toBeDisabled();
    expect(
      screen.getByText("Turn AI on under Security to use these connections.")
    ).toBeInTheDocument();
  });

  it("says who a connection serves and how its last request went", () => {
    render([
      connection({
        model: "claude-haiku-5-5",
        communities: [
          { id: 4, name: "Legal" },
          { id: 5, name: "Design" },
        ],
        last_error: "AI_OUT_OF_CREDIT",
        last_error_at: "2026-10-21T14:02:00Z",
      }),
    ]);

    expect(screen.getByText("Only for Legal and Design")).toBeInTheDocument();
    expect(
      screen.getByText(/^Failing since .+: The AI provider's account is out of credit/)
    ).toBeInTheDocument();
  });
});
