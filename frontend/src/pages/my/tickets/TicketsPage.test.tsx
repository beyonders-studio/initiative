/**
 * The reader's own tickets, each leading to its own page.
 */
import { screen } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";

import { buildUser } from "@/__tests__/factories";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";
import type { FiledTicketList } from "@/api/generated/initiativeAPI.schemas";

import { TicketsPage } from "./TicketsPage";

/** Serves the reader's tickets, where security reports are taken by a form. */
const serve = (list: FiledTicketList = { items: [] }) =>
  server.use(
    http.get("/api/v1/me/tickets", () => HttpResponse.json(list)),
    http.get("/api/v1/me/tickets/availability", () =>
      HttpResponse.json({
        support: { mode: "none", contact: null, evidence: null },
        moderation: { mode: "form", contact: null, evidence: null },
        feedback: { mode: "none", contact: null, evidence: null },
        security: { mode: "form", contact: null, evidence: null },
      })
    )
  );

const now = new Date().toISOString();

const open = () =>
  renderPage(TicketsPage, { initialRoute: "/my-tickets/", auth: { user: buildUser() } });

describe("TicketsPage", () => {
  it("lists each ticket with where it stands", async () => {
    serve({
      items: [
        {
          task_id: 7,
          stream: "support",
          topic: "account",
          subject: "Lost my phone",
          state: "waiting_on_you",
          opened_at: now,
          updated_at: now,
        },
        {
          task_id: 9,
          stream: "feedback",
          topic: "idea",
          subject: null,
          state: "closed",
          opened_at: now,
          updated_at: null,
        },
      ],
    });
    open();
    const link = await screen.findByRole("link", { name: /Lost my phone/ });
    expect(link).toHaveAttribute("href", "/my-tickets/7");
    expect(screen.getByText("Waiting on you")).toBeInTheDocument();
    // An untitled ticket whose topic has no name of its own goes by its stream.
    expect(screen.getByRole("link", { name: /^Feedback Feedback/ })).toHaveAttribute(
      "href",
      "/my-tickets/9"
    );
  });

  it("explains an empty list, and offers reporting a security problem where the server takes it", async () => {
    serve();
    open();
    expect(await screen.findByText(/haven't filed any tickets/)).toBeInTheDocument();
    expect(
      await screen.findByRole("button", { name: "Report a security problem" })
    ).toBeInTheDocument();
  });

  it("opens the security form when a link asks for it", async () => {
    serve();
    renderPage(TicketsPage, {
      initialRoute: "/my-tickets/",
      routerSearch: { report: "security" },
      auth: { user: buildUser() },
    });
    expect(
      await screen.findByRole("dialog", { name: "Report a security problem" })
    ).toBeInTheDocument();
  });
});
