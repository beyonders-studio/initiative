/**
 * What reaches the server when the seat grants a plug-in its scopes.
 *
 * Changing implies reading, so ticking a change ticks the read and unticking
 * the read unticks the change. A requested scope the server does not allow
 * cannot be ticked, and the save sends the whole set.
 */

import { screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderPage } from "@/__tests__/helpers/render";
import type { CommunityPluginDetail } from "@/api/generated/initiativeAPI.schemas";

import { PluginScopesPanel } from "./PluginScopesPanel";

/** Every set handed to the save, in order. */
const sent: string[][] = [];
const mutate = vi.fn(
  (granted: string[], handlers?: { onSuccess?: (read: { granted_scopes: string[] }) => void }) => {
    sent.push(granted);
    handlers?.onSuccess?.({ granted_scopes: [...granted].sort() });
  }
);

vi.mock("@/hooks/useCommunityPlugins", () => ({
  useSetPluginScopes: () => ({ mutate, isPending: false }),
}));

const plugin = (overrides: Partial<CommunityPluginDetail> = {}) =>
  ({
    id: 7,
    name: "WidgetCo",
    requested_scopes: ["projects:read", "projects:write", "comments:read"],
    grantable_scopes: ["projects:read", "projects:write", "comments:read"],
    granted_scopes: [],
    ...overrides,
  }) as unknown as CommunityPluginDetail;

/** The row for one resource, by its label. */
const row = async (label: string) => {
  const item = (await screen.findByText(label)).closest("li");
  if (!item) throw new Error(`no row for ${label}`);
  return within(item);
};

beforeEach(() => {
  sent.length = 0;
  mutate.mockClear();
});

describe("PluginScopesPanel", () => {
  it("includes the read when a change is granted", async () => {
    renderPage(() => <PluginScopesPanel plugin={plugin()} />);

    const projects = await row("Projects");
    projects.getByLabelText("Read and change").click();

    await waitFor(() => expect(projects.getByLabelText("Read")).toBeChecked());
    expect(projects.getByLabelText("Read and change")).toBeChecked();

    screen.getByRole("button", { name: "Save" }).click();
    await waitFor(() => expect(sent).toHaveLength(1));
    expect([...sent[0]].sort()).toEqual(["projects:read", "projects:write"]);
  });

  it("says acting as a moderator or an admin plainly, on rows of their own", async () => {
    const standings = ["initiatives:moderate", "community:admin"];
    renderPage(() => (
      <PluginScopesPanel
        plugin={plugin({
          requested_scopes: ["initiatives:read", ...standings],
          grantable_scopes: ["initiatives:read", ...standings],
          granted_scopes: ["initiatives:read"],
        })}
      />
    ));

    const initiatives = await row("Initiatives");
    expect(initiatives.getByLabelText("Read")).toBeChecked();
    expect(initiatives.queryByLabelText("Read and change")).not.toBeInTheDocument();
    expect(screen.queryByText("Community")).not.toBeInTheDocument();

    const moderate = screen.getByLabelText("Act as a moderator in the initiatives it's placed in");
    expect(moderate).not.toBeChecked();
    expect(screen.getByLabelText("Act as an admin across your whole community")).not.toBeChecked();

    moderate.click();
    await waitFor(() => expect(moderate).toBeChecked());
    screen.getByRole("button", { name: "Save" }).click();
    await waitFor(() => expect(sent).toHaveLength(1));
    expect([...sent[0]].sort()).toEqual(["initiatives:moderate", "initiatives:read"]);
  });

  it("takes the change away with the read", async () => {
    renderPage(() => (
      <PluginScopesPanel plugin={plugin({ granted_scopes: ["projects:read", "projects:write"] })} />
    ));

    const projects = await row("Projects");
    expect(projects.getByLabelText("Read and change")).toBeChecked();
    projects.getByLabelText("Read").click();

    await waitFor(() => expect(projects.getByLabelText("Read and change")).not.toBeChecked());
    screen.getByRole("button", { name: "Save" }).click();
    await waitFor(() => expect(sent).toEqual([[]]));
  });

  it("shows a scope the server does not allow, disabled, with the reason", async () => {
    renderPage(() => (
      <PluginScopesPanel
        plugin={plugin({ grantable_scopes: ["projects:read", "comments:read"] })}
      />
    ));

    const projects = await row("Projects");
    expect(projects.getByLabelText("Read and change")).toBeDisabled();
    expect(projects.getByText("This server doesn't allow it")).toBeTruthy();
    expect(projects.getByLabelText("Read")).toBeEnabled();
  });

  it("sends the whole set, keeping what was already granted", async () => {
    renderPage(() => <PluginScopesPanel plugin={plugin({ granted_scopes: ["comments:read"] })} />);

    const save = await screen.findByRole("button", { name: "Save" });
    // Nothing changed yet.
    expect(save).toBeDisabled();

    (await row("Projects")).getByLabelText("Read").click();
    await waitFor(() => expect(save).toBeEnabled());
    save.click();
    await waitFor(() => expect(sent).toHaveLength(1));
    expect([...sent[0]].sort()).toEqual(["comments:read", "projects:read"]);
  });

  it("offers the use of another plug-in as a row of its own", async () => {
    renderPage(() => (
      <PluginScopesPanel
        plugin={plugin({
          requested_scopes: ["projects:read", "plugins:acme.github"],
          grantable_scopes: ["projects:read", "plugins:acme.github"],
          plugin_names: { "acme.github": "GitHub" },
        })}
      />
    ));

    (await screen.findByLabelText("Use GitHub in this community")).click();
    const save = screen.getByRole("button", { name: "Save" });
    await waitFor(() => expect(save).toBeEnabled());
    save.click();
    await waitFor(() => expect(sent).toEqual([["plugins:acme.github"]]));
  });

  it("offers a change alone when the plug-in asks only to change", async () => {
    renderPage(() => (
      <PluginScopesPanel
        plugin={plugin({ requested_scopes: ["tags:write"], grantable_scopes: ["tags:write"] })}
      />
    ));

    const tags = await row("Tags");
    expect(tags.queryByLabelText("Read")).toBeNull();
    tags.getByLabelText("Read and change").click();
    const save = screen.getByRole("button", { name: "Save" });
    await waitFor(() => expect(save).toBeEnabled());
    save.click();
    await waitFor(() => expect(sent).toEqual([["tags:write"]]));
  });
});
