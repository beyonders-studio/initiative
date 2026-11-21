/**
 * The filer's view of their own ticket: only what was said to them, the team
 * unnamed, and a box to answer in only where the ticket takes an answer.
 */
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";

import { buildUser } from "@/__tests__/factories";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";
import type { FiledTicketDetailRead } from "@/api/generated/initiativeAPI.schemas";

import { TicketPage } from "./TicketPage";

const now = new Date().toISOString();
const ticket = (overrides: Partial<FiledTicketDetailRead> = {}): FiledTicketDetailRead => ({
  task_id: 7,
  stream: "support",
  topic: "account",
  subject: "Lost my phone",
  state: "waiting_on_you",
  opened_at: now,
  updated_at: now,
  conversation: "open",
  can_reply: true,
  evidence: { max_files: 5, max_bytes: 10 * 1024 * 1024, types: ["image/png", "image/jpeg"] },
  messages: [
    { id: 1, mine: true, content: "Help.", created_at: now },
    { id: 2, mine: false, content: "Which phone?", created_at: now },
  ],
  ...overrides,
});

/** Serves the tickets by id, and records each reply as its body and file names. */
const serve = (...tickets: FiledTicketDetailRead[]) => {
  const replies: { body: unknown; files: string[] }[] = [];
  server.use(
    http.get("/api/v1/me/tickets/:taskId", ({ params }) =>
      HttpResponse.json(tickets.find((one) => one.task_id === Number(params.taskId)))
    ),
    http.post("/api/v1/me/tickets/:taskId/replies", async ({ request }) => {
      // Read as text: newer Node's multipart parser refuses jsdom's File.
      const raw = await request.text();
      replies.push({
        body: raw.split('name="body"\r\n\r\n')[1]?.split("\r\n")[0],
        files: [...raw.matchAll(/filename="([^"]+)"/g)].map(([, name]) => name),
      });
      return HttpResponse.json(tickets[0]);
    })
  );
  return replies;
};

const open = () =>
  renderPage(TicketPage, {
    initialRoute: "/my-tickets/$taskId",
    routeParams: { taskId: "7" },
    auth: { user: buildUser() },
  });

describe("TicketPage", () => {
  it("shows the conversation, the team unnamed", async () => {
    serve(ticket());
    open();
    expect(await screen.findByRole("heading", { name: "Lost my phone" })).toBeInTheDocument();
    expect(screen.getByText("Which phone?")).toBeInTheDocument();
    expect(screen.getByText(/^The team ·/)).toBeInTheDocument();
    expect(screen.getByText("Waiting on you")).toBeInTheDocument();
  });

  it("sends an answer", async () => {
    const replies = serve(ticket());
    const user = userEvent.setup();
    open();
    await user.type(await screen.findByRole("textbox"), "The work one.");
    await user.click(screen.getByRole("button", { name: "Send reply" }));
    await waitFor(() => expect(replies).toEqual([{ body: "The work one.", files: [] }]));
  });

  it("sends an answer with a picture, and refuses a kind the ticket does not take", async () => {
    const replies = serve(ticket());
    const user = userEvent.setup({ applyAccept: false });
    open();
    const input = await screen.findByTestId("evidence-input");
    const photo = new File(["png"], "screen.png", { type: "image/png" });
    const script = new File(["#!"], "run.sh", { type: "text/x-sh" });
    await user.upload(input, [photo, script]);
    expect(screen.getByRole("img", { name: "screen.png" })).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("run.sh");
    await user.type(screen.getByRole("textbox"), "This one.");
    await user.click(screen.getByRole("button", { name: "Send reply" }));
    await waitFor(() => expect(replies).toEqual([{ body: "This one.", files: ["screen.png"] }]));
  });

  it("starts another ticket's page without the last one's draft", async () => {
    serve(ticket(), ticket({ task_id: 8, subject: "Another one" }));
    const user = userEvent.setup();
    const { router } = open();
    const photo = new File(["png"], "screen.png", { type: "image/png" });
    await user.upload(await screen.findByTestId("evidence-input"), photo);
    await user.type(screen.getByRole("textbox"), "Half an answer");
    expect(screen.getByRole("img", { name: "screen.png" })).toBeInTheDocument();

    await router.navigate({ to: "/my-tickets/$taskId", params: { taskId: "8" } });

    expect(await screen.findByRole("heading", { name: "Another one" })).toBeInTheDocument();
    expect(screen.queryByRole("img", { name: "screen.png" })).toBeNull();
    expect(screen.getByRole("textbox")).toHaveValue("");
  });

  it("shows what the reader sent beside what they said", async () => {
    serve(
      ticket({
        messages: [
          {
            id: 1,
            mine: true,
            content: "Help.",
            created_at: now,
            attachments: [
              {
                id: 9,
                display_name: "notes.pdf",
                content_type: "application/pdf",
                size_bytes: 2048,
                created_at: now,
              },
            ],
          },
        ],
      })
    );
    open();
    const link = await screen.findByRole("link", { name: "Open notes.pdf" });
    expect(link).toHaveAttribute("href", "/api/v1/me/tickets/7/evidence/9");
  });

  it("explains why a closed ticket takes no answer", async () => {
    serve(ticket({ state: "closed", can_reply: false }));
    open();
    expect(await screen.findByText(/This ticket is closed/)).toBeInTheDocument();
    expect(screen.queryByRole("textbox")).toBeNull();
  });
});
