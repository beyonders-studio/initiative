import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { useState } from "react";
import { describe, expect, it } from "vitest";

import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { createTestQueryClient, renderPage } from "@/__tests__/helpers/render";
import { generateSummary } from "@/api/generated/files/files";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";

import { type AISummary, SummarySheet } from "./SummarySheet";

/** The answer, one JSON line at a time, as the server writes it. */
const lines = (...events: object[]) =>
  new HttpResponse(
    new ReadableStream({
      start(controller) {
        for (const event of events) {
          controller.enqueue(new TextEncoder().encode(`${JSON.stringify(event)}\n`));
        }
        controller.close();
      },
    }),
    { headers: { "Content-Type": "application/jsonl" } }
  );

const answering = (reply: () => Response) =>
  server.use(
    communityHttp.get("/settings/ai/resolved", () =>
      HttpResponse.json({ enabled: true, source: "platform" })
    ),
    communityHttp.post("/files/:fileId/ai/summary", reply)
  );

const Page = () => {
  const communityId = useActiveCommunityId();
  const [summary, setSummary] = useState<AISummary | null>(null);
  return (
    <SummarySheet
      open
      onOpenChange={() => {}}
      request={(options, signal) => generateSummary(communityId, 5, options, signal)}
      summary={summary}
      onSummaryChange={setSummary}
    />
  );
};

const summarize = async () => {
  renderPage(Page, { queryClient: createTestQueryClient() });
  await userEvent.click(await screen.findByRole("button", { name: /Generate Summary/ }));
};

describe("SummarySheet", () => {
  it("writes the summary in as it arrives, and says how much it read", async () => {
    answering(() => lines({ cut: { percent: 62 } }, { text: "The rota " }, { text: "is sorted." }));

    await summarize();

    expect(await screen.findByText("The rota is sorted.")).toBeInTheDocument();
    expect(
      screen.getByText("Written from the first 62% of it. The rest did not fit.")
    ).toBeInTheDocument();
  });

  it("keeps what was written when the answer stops part-way", async () => {
    answering(() => lines({ text: "The rota " }, { error: "AI_RATE_LIMITED" }));

    await summarize();

    expect(await screen.findByText(/getting too many requests/)).toBeInTheDocument();
    expect(screen.getByText("The rota")).toBeInTheDocument();
  });

  it("says why when nothing could be written", async () => {
    answering(() => HttpResponse.json({ detail: "AI_DOCUMENT_EMPTY" }, { status: 400 }));

    await summarize();

    expect(
      await screen.findByText("This document has no content to summarize.")
    ).toBeInTheDocument();
  });
});
