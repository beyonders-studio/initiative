/**
 * The dialog reports, security problems and feedback are filed through.
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
  current: undefined as { onError?: (e: unknown) => void } | undefined,
}));
const contacts = vi.hoisted(() => ({ moderation: null as string | null }));
const offered = vi.hoisted(() => ({
  support: ["account", "community", "billing", "other"] as string[],
  supportMode: "form" as "form" | "email" | "none",
}));
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
        support: {
          mode: offered.supportMode,
          contact: null,
          evidence: POLICY,
          types: offered.support,
        },
        security: { mode: "form", contact: null, evidence: POLICY },
        feedback: {
          mode: "form",
          contact: null,
          evidence: { ...POLICY, types: ["image/png"] },
          types: ["idea", "problem", "praise", "other"],
        },
      },
    }),
    useFileTicket: (options: { onError?: (e: unknown) => void }) => {
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

const chooseReason = async (user: ReturnType<typeof userEvent.setup>, name: string) => {
  await user.click(screen.getByRole("combobox", { name: "What is wrong?" }));
  await user.click(await screen.findByRole("option", { name }));
};

describe("FileTicketDialog", () => {
  beforeEach(() => {
    fileMutate.mockClear();
    contacts.moderation = null;
    offered.support = ["account", "community", "billing", "other"];
    offered.supportMode = "form";
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
      await user.click(screen.getByRole("combobox", { name: "Which law?" }));
      await user.click(await screen.findByRole("option", { name: "Privacy" }));
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
      await user.click(screen.getByRole("combobox", { name: "Which law?" }));
      await user.click(await screen.findByRole("option", { name: "Child safety" }));

      expect(screen.getByText(/Don't attach anything/)).toBeInTheDocument();
      expect(screen.queryByText("Attach files")).not.toBeInTheDocument();
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

    it("never says where the report will go", () => {
      report();
      // Nothing in the dialog names a venue, a project or a moderator: where
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

  describe("sending feedback", () => {
    const CONTEXT = {
      app_version: "0.70.0",
      platform: "web",
      route: "/c/$communityId/i/$initiativeId",
    };

    const feedback = (communityId: number | null = 3) =>
      renderWithProviders(
        <FileTicketDialog
          open
          onOpenChange={() => {}}
          ticket={{ stream: "feedback", context: CONTEXT }}
          communityId={communityId}
        />,
        { auth: { user: buildUser() } }
      );

    const choose = async (user: ReturnType<typeof userEvent.setup>, name: string) => {
      await user.click(screen.getByRole("combobox", { name: "What kind of feedback is it?" }));
      await user.click(await screen.findByRole("option", { name }));
    };

    it("sends the kind, the words and where the app was", async () => {
      feedback();
      const user = userEvent.setup();
      // Shown before it is sent.
      expect(screen.getByText("/c/$communityId/i/$initiativeId")).toBeInTheDocument();

      await choose(user, "An idea");
      await user.type(screen.getByLabelText("What do you want to tell them?"), "Dark print.");
      await user.click(screen.getByRole("button", { name: "Send feedback" }));

      expect(fileMutate).toHaveBeenCalledWith({
        ticket: { stream: "feedback", type: "idea", body: "Dark print.", context: CONTEXT },
        files: [],
      });
    });

    it("sends no context once it is removed", async () => {
      feedback();
      const user = userEvent.setup();
      await user.click(screen.getByRole("button", { name: "Remove" }));
      expect(screen.queryByText("/c/$communityId/i/$initiativeId")).toBeNull();

      await choose(user, "Praise");
      await user.type(screen.getByLabelText("What do you want to tell them?"), "Lovely.");
      await user.click(screen.getByRole("button", { name: "Send feedback" }));

      expect(fileMutate).toHaveBeenCalledWith(
        expect.objectContaining({ ticket: expect.objectContaining({ context: null }) })
      );
    });

    it("sends a problem that needs an answer to support instead", async () => {
      feedback();
      const user = userEvent.setup();
      // Only a problem asks.
      expect(screen.queryByLabelText("I need an answer")).toBeNull();
      await choose(user, "A problem");
      await user.type(
        screen.getByLabelText("What do you want to tell them?"),
        "Export drops a row.\nEvery time."
      );
      await user.click(screen.getByLabelText("I need an answer"));
      await user.click(screen.getByRole("button", { name: "Send" }));

      expect(fileMutate).toHaveBeenCalledWith({
        ticket: {
          stream: "support",
          type: "community",
          community_id: 3,
          subject: "Export drops a row.",
          body: "Export drops a row.\nEvery time.",
        },
        files: [],
      });
    });

    it("asks about the account where the community takes no help requests", async () => {
      offered.support = ["account", "billing", "other"];
      feedback();
      const user = userEvent.setup();
      await choose(user, "A problem");
      await user.type(screen.getByLabelText("What do you want to tell them?"), "Broken.");
      await user.click(screen.getByLabelText("I need an answer"));
      await user.click(screen.getByRole("button", { name: "Send" }));

      expect(fileMutate).toHaveBeenCalledWith(
        expect.objectContaining({
          ticket: expect.objectContaining({
            stream: "support",
            type: "account",
            community_id: null,
          }),
        })
      );
    });

    it("takes off what feedback does not take when no answer is wanted after all", async () => {
      feedback();
      const user = userEvent.setup();
      await choose(user, "A problem");
      await user.click(screen.getByLabelText("I need an answer"));
      const notes = new File(["notes"], "notes.pdf", { type: "application/pdf" });
      const shot = new File(["png"], "shot.png", { type: "image/png" });
      await user.upload(screen.getByTestId("evidence-input"), [notes, shot]);
      expect(screen.getByText("notes.pdf")).toBeInTheDocument();

      await user.click(screen.getByLabelText("I need an answer"));

      expect(screen.queryByText("notes.pdf")).toBeNull();
      expect(screen.getByText("shot.png")).toBeInTheDocument();
      expect(screen.getByRole("status")).toHaveTextContent("Took off notes.pdf");
    });

    it("does not offer an answer where support takes nothing", async () => {
      offered.supportMode = "email";
      feedback();
      const user = userEvent.setup();
      await choose(user, "A problem");
      expect(screen.queryByLabelText("I need an answer")).toBeNull();
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
      await user.click(screen.getByRole("combobox", { name: "What is it about?" }));
      await user.click(await screen.findByRole("option", { name: "A weakness in this server" }));
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
      expect(screen.queryByText("c.png")).toBeNull();
      expect(screen.getByRole("button", { name: "Attach files" })).toBeDisabled();
    });
  });
});
