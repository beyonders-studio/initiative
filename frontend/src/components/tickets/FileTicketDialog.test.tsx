/**
 * The sheet reports and security problems are filed through.
 *
 * What it must not do is as important as what it does: a report never says
 * where it went, and tells the reporter nothing about what happens next.
 */
import { act, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AxiosError, type AxiosResponse } from "axios";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildUser } from "@/__tests__/factories";
import { renderWithProviders } from "@/__tests__/helpers/render";

const fileMutate = vi.fn();
const fileOptions = vi.hoisted(() => ({
  current: undefined as
    | { onSuccess?: (accepted: unknown) => void; onError?: (e: unknown) => void }
    | undefined,
}));
const contacts = vi.hoisted(() => ({ moderation: null as string | null }));
const POLICY = vi.hoisted(() => ({
  max_files: 2,
  max_bytes: 1024,
  types: ["image/png", "application/pdf", "text/plain"],
}));

vi.mock("@/hooks/useTickets", async () => {
  const actual = await vi.importActual<typeof import("@/hooks/useTickets")>("@/hooks/useTickets");
  return {
    ...actual,
    useTicketAvailability: () => ({
      data: {
        moderation: { mode: "form", contact: contacts.moderation, evidence: POLICY },
        security: { mode: "form", contact: null, evidence: POLICY },
      },
    }),
    useFileTicket: (options: (typeof fileOptions)["current"]) => {
      fileOptions.current = options;
      return { mutate: fileMutate, isPending: false };
    },
  };
});

import { FileTicketDialog, type FileTicketDialogProps } from "./FileTicketDialog";

const report = (props: Partial<FileTicketDialogProps> = {}) =>
  renderWithProviders(
    <FileTicketDialog
      open
      onOpenChange={() => {}}
      ticket={{ stream: "moderation", targetType: "comment", targetId: 42 }}
      communityId={3}
      {...props}
    />,
    { auth: { user: buildUser() } }
  );

/** Picks `name` from the dropdown labelled `field`. */
const choose = async (user: ReturnType<typeof userEvent.setup>, field: string, name: string) => {
  await user.click(screen.getByLabelText(field));
  await user.click(await screen.findByRole("option", { name }));
};
const chooseReason = (user: ReturnType<typeof userEvent.setup>, name: string) =>
  choose(user, "What is wrong?", name);

describe("FileTicketDialog", () => {
  beforeEach(() => {
    fileMutate.mockClear();
    contacts.moderation = null;
  });

  describe("reporting something", () => {
    it("will not send without a reason", () => {
      report();
      expect(screen.getByRole("button", { name: "Send report" })).toBeDisabled();
    });

    it("sends the target, the reason and the community it was reported from", async () => {
      report();
      const user = userEvent.setup();

      await chooseReason(user, "Harassment");
      await user.click(screen.getByRole("button", { name: "Send report" }));

      expect(fileMutate).toHaveBeenCalledWith({
        ticket: {
          stream: "moderation",
          target_type: "comment",
          target_id: 42,
          reason: "harassment",
          detail: null,
          legal_basis: null,
          community_id: 3,
        },
        files: [],
      });
    });

    it("asks which law something illegal breaks, and what is wrong with it", async () => {
      report();
      const user = userEvent.setup();
      const send = screen.getByRole("button", { name: "Send report" });

      await chooseReason(user, "Illegal");
      expect(send).toBeDisabled();
      await choose(user, "Which law?", "Privacy");
      // A law named, and still nothing said about it.
      expect(send).toBeDisabled();
      await user.type(screen.getByLabelText("Tell them what you saw"), "My home address.");
      await user.click(send);

      expect(fileMutate).toHaveBeenCalledWith(
        expect.objectContaining({
          ticket: expect.objectContaining({
            reason: "illegal",
            legal_basis: "privacy",
            detail: "My home address.",
          }),
        })
      );
    });

    it("takes no files with a child-safety report", async () => {
      report();
      const user = userEvent.setup();

      await chooseReason(user, "Illegal");
      await choose(user, "Which law?", "Child safety");

      expect(screen.getByText(/Don't attach anything/)).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Attach files" })).not.toBeInTheDocument();
    });

    it("needs words for a report of something else", async () => {
      report();
      const user = userEvent.setup();

      await chooseReason(user, "Other");
      expect(screen.getByRole("button", { name: "Send report" })).toBeDisabled();
      await user.type(screen.getByLabelText("Tell them what you saw"), "It's a scam.");
      expect(screen.getByRole("button", { name: "Send report" })).toBeEnabled();
    });

    it("carries the reporter's own words", async () => {
      report();
      const user = userEvent.setup();

      await user.type(screen.getByLabelText("Anything else?"), "  This is abusive.  ");
      await chooseReason(user, "Hate");
      await user.click(screen.getByRole("button", { name: "Send report" }));

      expect(fileMutate).toHaveBeenCalledWith(
        expect.objectContaining({
          ticket: expect.objectContaining({ detail: "This is abusive.", reason: "hate" }),
        })
      );
    });

    it("sends no community when the reporter is not in one", async () => {
      report({
        ticket: { stream: "moderation", targetType: "user_profile", targetId: 7 },
        communityId: null,
      });
      const user = userEvent.setup();

      await chooseReason(user, "Spam");
      await user.click(screen.getByRole("button", { name: "Send report" }));

      expect(fileMutate).toHaveBeenCalledWith(
        expect.objectContaining({
          ticket: expect.objectContaining({ target_type: "user_profile", community_id: null }),
        })
      );
    });

    it("thanks the reporter once it is sent, with the server's address where it gave one", async () => {
      report();
      act(() => {
        fileOptions.current?.onSuccess?.({ platform_contact: "abuse@example.org" });
      });

      expect(await screen.findByText("Thanks — somebody will look at this.")).toHaveFocus();
      expect(screen.getByText(/abuse@example\.org/)).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Send report" })).toBeNull();
    });

    it("never says where the report will go", () => {
      report();
      // Nothing in the sheet names a venue, a project or a moderator: where
      // it goes is decided server-side and is not the reporter's business.
      for (const leak of [/moderator/i, /platform/i, /operations/i, /initiative/i]) {
        expect(screen.queryByText(leak)).not.toBeInTheDocument();
      }
    });

    const nothingReceivedIt = () =>
      act(() => {
        fileOptions.current?.onError?.(
          new AxiosError("unavailable", "ERR_BAD_RESPONSE", undefined, undefined, {
            status: 503,
          } as AxiosResponse)
        );
      });

    it("offers the deployment's address, with what was written, when nothing could receive the report", async () => {
      contacts.moderation = "trust@example.org";
      report();
      const user = userEvent.setup();
      await user.type(screen.getByLabelText("Anything else?"), "It names my street.");
      await chooseReason(user, "Harassment");

      nothingReceivedIt();

      expect(await screen.findByText("trust@example.org")).toBeInTheDocument();
      const write = screen.getByRole("link", { name: "Write an email" });
      const href = write.getAttribute("href") ?? "";
      expect(href.startsWith("mailto:trust@example.org?")).toBe(true);
      const sent = new URLSearchParams(href.split("?")[1]);
      expect(sent.get("subject")).toBe("Report this: Harassment");
      expect(sent.get("body")).toContain("It names my street.");
      expect(sent.get("body")).toContain("comment 42");
      expect(screen.getByRole("button", { name: "Copy what you wrote" })).toBeInTheDocument();
    });

    it("turns into the address when it arrives after the refusal", async () => {
      const view = report();

      nothingReceivedIt();
      expect(await screen.findByRole("alert")).toBeInTheDocument();

      contacts.moderation = "trust@example.org";
      view.rerender(
        <FileTicketDialog
          open
          onOpenChange={() => {}}
          ticket={{ stream: "moderation", targetType: "comment", targetId: 42 }}
          communityId={3}
        />
      );

      expect(await screen.findByText("trust@example.org")).toBeInTheDocument();
    });
  });

  describe("reporting a security problem", () => {
    it("sends what it is about, a line and the words, from nowhere in particular", async () => {
      renderWithProviders(
        <FileTicketDialog
          open
          onOpenChange={() => {}}
          ticket={{ stream: "security" }}
          communityId={null}
        />,
        { auth: { user: buildUser() } }
      );
      const user = userEvent.setup();

      const send = screen.getByRole("button", { name: "Send report" });
      await user.type(screen.getByLabelText("Title"), "Cookie without Secure");
      await user.type(screen.getByLabelText("What did you find?"), "On the sign-in reply.");
      // Not until it says what kind of problem it is.
      expect(send).toBeDisabled();
      await choose(user, "What is it about?", "A weakness in this server");
      await user.click(send);

      expect(fileMutate).toHaveBeenCalledWith({
        ticket: {
          stream: "security",
          type: "vulnerability",
          subject: "Cookie without Secure",
          body: "On the sign-in reply.",
        },
        files: [],
      });
    });
  });

  describe("attaching files", () => {
    it("sends what was chosen with the report", async () => {
      report();
      const user = userEvent.setup();
      const shot = new File(["png"], "shot.png", { type: "image/png" });
      await user.upload(screen.getByTestId("evidence-input"), shot);
      await chooseReason(user, "Harassment");
      await user.click(screen.getByRole("button", { name: "Send report" }));
      expect(fileMutate).toHaveBeenCalledWith(expect.objectContaining({ files: [shot] }));
    });

    it("says what it will not take, before anything is sent", async () => {
      report();
      const user = userEvent.setup({ applyAccept: false });
      const big = new File(["x".repeat(2048)], "big.png", { type: "image/png" });
      const odd = new File(["zip"], "a.zip", { type: "application/zip" });
      await user.upload(screen.getByTestId("evidence-input"), big);
      expect(screen.getByRole("alert")).toHaveTextContent("big.png is larger than 1 KB.");
      await user.upload(screen.getByTestId("evidence-input"), odd);
      expect(screen.getByRole("alert")).toHaveTextContent("a.zip isn't a kind of file this takes.");
    });

    it("leaves a file the browser cannot name, and any text, to the server", async () => {
      report();
      const user = userEvent.setup({ applyAccept: false });
      const notes = new File(["# notes"], "notes.md", { type: "text/markdown" });
      const unnamed = new File(["?"], "scan", { type: "" });
      await user.upload(screen.getByTestId("evidence-input"), [notes, unnamed]);
      expect(screen.queryByRole("alert")).toBeNull();
      expect(screen.getByText("notes.md")).toBeInTheDocument();
      expect(screen.getByText("scan")).toBeInTheDocument();
    });

    it("stops at as many files as the stream takes", async () => {
      report();
      const user = userEvent.setup();
      const files = ["a", "b", "c"].map(
        (name) => new File([name], `${name}.png`, { type: "image/png" })
      );
      await user.upload(screen.getByTestId("evidence-input"), files);
      expect(screen.getByRole("alert")).toHaveTextContent("You can attach up to 2 files.");
      expect(screen.getByRole("button", { name: "Remove a.png" })).toBeInTheDocument();
      expect(screen.queryByRole("img", { name: "c.png" })).toBeNull();
      expect(screen.getByRole("button", { name: "Attach files" })).toBeDisabled();
    });
  });
});
