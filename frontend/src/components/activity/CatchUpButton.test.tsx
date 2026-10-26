import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { createTestQueryClient, renderPage } from "@/__tests__/helpers/render";
import { Tool } from "@/api/generated/initiativeAPI.schemas";

import { CatchUpButton } from "./CatchUpButton";

const SINCE = "2026-10-20T09:30:00Z";

/** The answer, one JSON line at a time, and the bodies asked with. */
const answering = (...events: object[]) => {
  const asked: unknown[] = [];
  server.use(
    communityHttp.get("/settings/ai/resolved", () =>
      HttpResponse.json({ enabled: true, source: "platform" })
    ),
    communityHttp.post("/activity/catch-up", async ({ request }) => {
      asked.push(await request.json());
      return new HttpResponse(events.map((event) => `${JSON.stringify(event)}\n`).join(""), {
        headers: { "Content-Type": "application/jsonl" },
      });
    })
  );
  return asked;
};

const catchUp = async () => {
  renderPage(() => <CatchUpButton since={SINCE} scope={{ tool: Tool.project, toolId: 7 }} />, {
    queryClient: createTestQueryClient(),
  });
  await userEvent.click(await screen.findByRole("button", { name: "Catch me up" }));
  const sheet = await screen.findByRole("dialog");
  await userEvent.click(
    [...sheet.querySelectorAll("button")].find((b) => b.textContent === "Catch me up")!
  );
};

describe("CatchUpButton", () => {
  it("asks about the tool since the last visit, and writes the answer in", async () => {
    const asked = answering({ since: SINCE }, { text: "The hall is booked." });

    await catchUp();

    expect(await screen.findByText("The hall is booked.")).toBeInTheDocument();
    expect(screen.getByText(/^Since /)).toBeInTheDocument();
    expect(asked).toEqual([{ since: SINCE, tool: "project", tool_id: 7 }]);
  });

  it("says so when nothing changed", async () => {
    answering({ since: SINCE });

    await catchUp();

    expect(await screen.findByText("Nothing new since you were last here.")).toBeInTheDocument();
  });
});
