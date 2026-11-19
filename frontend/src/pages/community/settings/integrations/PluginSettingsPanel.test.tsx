/**
 * A plug-in's settings, as the seat changes them: each shows what it holds and
 * what it is for, a unique one the earlier values that still work, and a value
 * the server refuses says why in the reader's language.
 */
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { HttpResponse } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";
import type { CommunityPluginSettingRead } from "@/api/generated/initiativeAPI.schemas";
import { toast } from "@/lib/mascotToast";

import { PluginSettingsPanel } from "./PluginSettingsPanel";

/** Answers the setting's save with `reply`, recording what was sent. */
const answerSave = (reply: () => Response) => {
  const sent = vi.fn();
  server.use(
    communityHttp.put("/plugins/:pluginId/settings/:key", async ({ params, request }) => {
      sent(params.key, await request.json());
      return reply();
    })
  );
  return sent;
};

vi.mock("@/lib/mascotToast", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

const prefix: CommunityPluginSettingRead = {
  key: "task_prefix",
  label: { en: "Task prefix" },
  description: { en: "Starts each task's reference." },
  unique: true,
  value: "acme",
  aliases: ["acmeold", "acorp"],
};

const render = () => renderPage(() => <PluginSettingsPanel pluginId={3} settings={[prefix]} />);

const rename = async (value: string) => {
  fireEvent.change(await screen.findByLabelText("Task prefix"), { target: { value } });
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
};

beforeEach(() => {
  vi.mocked(toast.error).mockReset();
});

describe("PluginSettingsPanel", () => {
  it("shows what a setting holds, what it is for, and the earlier values", async () => {
    render();

    expect(await screen.findByLabelText("Task prefix")).toHaveValue("acme");
    expect(screen.getByText("Starts each task's reference.")).toBeInTheDocument();
    expect(screen.getByText(/acmeold, acorp/)).toBeInTheDocument();
    // Nothing to save until it changes.
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
  });

  it("saves the new value", async () => {
    const sent = answerSave(() => HttpResponse.json({}));
    render();

    await rename("acmeco");

    await waitFor(() => expect(sent).toHaveBeenCalledWith("task_prefix", { value: "acmeco" }));
  });

  it("says why a value was refused", async () => {
    answerSave(() =>
      HttpResponse.json({ detail: "COMMUNITY_PLUGIN_SETTING_UNAVAILABLE" }, { status: 409 })
    );
    render();

    await rename("taken");

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith("That value can't be used. Try another.")
    );
  });
});
