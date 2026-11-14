import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/__tests__/helpers/render";
import type { FiledTicketDetailRead } from "@/api/generated/initiativeAPI.schemas";

type TimeOut = {
  contact_email: string | null;
  reason: string | null;
  since: null;
  can_appeal?: boolean;
  appeal_task_id?: number | null;
};

const timeOut = vi.hoisted(() => ({
  value: { contact_email: null, reason: null, since: null } as TimeOut,
}));
const appeal = vi.hoisted(() => ({ ticket: undefined as FiledTicketDetailRead | undefined }));
const fileMutate = vi.fn();

vi.mock("@/api/generated/users/users", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/generated/users/users")>()),
  readMyTimeOut: () => Promise.resolve(timeOut.value),
}));

vi.mock("@/hooks/useTickets", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/hooks/useTickets")>()),
  useFileTicket: () => ({ mutate: fileMutate, isPending: false }),
  useFiledTicket: () => ({ data: appeal.ticket }),
  useReplyToTicket: () => ({ mutate: vi.fn(), isPending: false }),
}));

import { AccountTimeOut } from "./AccountTimeOut";

const now = new Date().toISOString();
const appealTicket = (state: FiledTicketDetailRead["state"]): FiledTicketDetailRead => ({
  task_id: 12,
  stream: "moderation",
  topic: "appeal",
  subject: null,
  state,
  opened_at: now,
  updated_at: now,
  conversation: "open",
  can_reply: state !== "closed",
  evidence: { max_files: 0, max_bytes: 0, types: [] },
  messages: [
    { id: 1, mine: true, content: "It was my sister.", created_at: now },
    { id: 2, mine: false, content: "We are looking into it.", created_at: now },
  ],
});

describe("AccountTimeOut", () => {
  beforeEach(() => {
    timeOut.value = { contact_email: null, reason: null, since: null };
    appeal.ticket = undefined;
    fileMutate.mockClear();
  });

  it("gives the reason and names who to contact", async () => {
    timeOut.value = { contact_email: "trust@example.com", reason: "Spam", since: null };
    renderWithProviders(<AccountTimeOut />);

    expect(screen.getByText("Your account is suspended")).toBeInTheDocument();
    expect(await screen.findByText("Reason given: Spam")).toBeInTheDocument();
    expect(screen.getByText("Contact trust@example.com about it.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sign out" })).toBeInTheDocument();
  });

  it("says to contact whoever runs the server when nobody is named", async () => {
    renderWithProviders(<AccountTimeOut />);

    expect(
      await screen.findByText("Contact whoever runs this server about it.")
    ).toBeInTheDocument();
    expect(screen.queryByText(/Reason given/)).not.toBeInTheDocument();
  });

  it("appeals where appeals are taken here", async () => {
    timeOut.value = {
      contact_email: "trust@example.com",
      reason: null,
      since: null,
      can_appeal: true,
      appeal_task_id: null,
    };
    renderWithProviders(<AccountTimeOut />);
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Appeal" }));
    expect(screen.queryByText(/Contact trust@example.com/)).not.toBeInTheDocument();
    await user.type(screen.getByLabelText("Why should it be lifted?"), " It was my sister. ");
    await user.click(screen.getByRole("button", { name: "Send appeal" }));

    expect(fileMutate).toHaveBeenCalledWith({
      ticket: { stream: "moderation", type: "appeal", body: "It was my sister." },
      files: [],
    });
  });

  it("follows an open appeal in place of appealing again", async () => {
    timeOut.value = {
      contact_email: null,
      reason: null,
      since: null,
      can_appeal: true,
      appeal_task_id: 12,
    };
    appeal.ticket = appealTicket("in_progress");
    renderWithProviders(<AccountTimeOut />);

    expect(await screen.findByText("Your appeal")).toBeInTheDocument();
    expect(screen.getByText("We are looking into it.")).toBeInTheDocument();
    expect(screen.getByLabelText("Your reply")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Appeal/ })).not.toBeInTheDocument();
  });

  it("appeals again once the last appeal is closed", async () => {
    timeOut.value = {
      contact_email: null,
      reason: null,
      since: null,
      can_appeal: true,
      appeal_task_id: 12,
    };
    appeal.ticket = appealTicket("closed");
    renderWithProviders(<AccountTimeOut />);

    expect(await screen.findByRole("button", { name: "Appeal again" })).toBeInTheDocument();
  });
});
