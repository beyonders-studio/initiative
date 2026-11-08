/**
 * Writing a poll.
 *
 * `isPollDraftValid` is what decides whether the submit button is offered, and
 * it has to agree with the server: too few choices, too many, or two that say
 * the same thing are all refused there, and a composer that let them through
 * would only earn a rejected save. The empty rows somebody left behind are the
 * case that matters most — they are not choices, so a poll with two filled
 * rows and a blank third is a valid two-choice poll.
 */
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { buildPoll, buildPollOption } from "@/__tests__/factories";
import { renderPage } from "@/__tests__/helpers/render";

import {
  emptyPollDraft,
  isPollDraftValid,
  PollEditor,
  pollDraftFromRead,
  pollDraftToWrite,
} from "./PollEditor";

const draft = (options: string[]) => ({ ...emptyPollDraft(), options });

describe("isPollDraftValid", () => {
  it("refuses a fresh draft, which is two empty rows", () => {
    expect(isPollDraftValid(emptyPollDraft())).toBe(false);
  });

  it("refuses one choice", () => {
    expect(isPollDraftValid(draft(["Tuesday", "  "]))).toBe(false);
  });

  it("refuses two choices that say the same thing", () => {
    expect(isPollDraftValid(draft(["Tuesday", "tuesday"]))).toBe(false);
  });

  it("refuses more choices than a poll may have", () => {
    expect(isPollDraftValid(draft(Array.from({ length: 11 }, (_, i) => `Choice ${i}`)))).toBe(
      false
    );
  });

  it("accepts two filled rows and ignores a blank third", () => {
    expect(isPollDraftValid(draft(["Tuesday", "Thursday", ""]))).toBe(true);
  });
});

describe("pollDraftToWrite", () => {
  it("drops the blank rows and trims the rest", () => {
    expect(pollDraftToWrite(draft([" Tuesday ", "", "Thursday"])).options).toEqual([
      { text: "Tuesday" },
      { text: "Thursday" },
    ]);
  });

  it("sends no question rather than an empty one", () => {
    expect(pollDraftToWrite({ ...draft(["a", "b"]), question: "   " }).question).toBeNull();
  });
});

describe("pollDraftFromRead", () => {
  it("reopens a saved poll with its choices in order", () => {
    const poll = buildPoll({
      options: [buildPollOption("Tuesday"), buildPollOption("Thursday")],
      allows_multiple: true,
    });

    const reopened = pollDraftFromRead(poll);

    expect(reopened.options).toEqual(["Tuesday", "Thursday"]);
    expect(reopened.allowsMultiple).toBe(true);
  });
});

describe("PollEditor", () => {
  it("never lets the choices fall below the floor", async () => {
    renderPage(() => <PollEditor value={emptyPollDraft()} onChange={vi.fn()} />);

    expect(await screen.findByRole("button", { name: /remove choice 1/i })).toBeDisabled();
  });

  it("freezes the choices once somebody has answered", async () => {
    renderPage(() => (
      <PollEditor value={draft(["Tuesday", "Thursday"])} onChange={vi.fn()} choicesLocked />
    ));

    expect(await screen.findByRole("textbox", { name: /choice 1/i })).toBeDisabled();
    expect(screen.getByText(/choices are fixed/i)).toBeInTheDocument();
  });

  it("adds a choice to the end", async () => {
    const onChange = vi.fn();
    renderPage(() => <PollEditor value={draft(["Tuesday", "Thursday"])} onChange={onChange} />);

    await userEvent.click(await screen.findByRole("button", { name: /add a choice/i }));

    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ options: ["Tuesday", "Thursday", ""] })
    );
  });

  it("stops offering more choices at the ceiling", async () => {
    const full = draft(Array.from({ length: 10 }, (_, i) => `Choice ${i}`));
    renderPage(() => <PollEditor value={full} onChange={vi.fn()} />);

    // An exact name, not a pattern: "Choice 1" is a prefix of "Choice 10".
    await screen.findByRole("textbox", { name: "Choice 10" });
    expect(screen.queryByRole("button", { name: /add a choice/i })).not.toBeInTheDocument();
  });
});
