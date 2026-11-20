/**
 * Asking someone their age, and what the surface promises about the answer.
 *
 * The date goes to the server to be compared and is not kept, so the dialog
 * must not hold on to it either.
 *
 * This is the only place the question is put. Nothing here blocks the app: the
 * dialog sits in front of one button, and closing it leaves the account with
 * everything it already had.
 */
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildUser } from "@/__tests__/factories";
import { renderWithProviders } from "@/__tests__/helpers/render";

const confirmMyAge = vi.fn();

vi.mock("@/api/generated/users/users", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/generated/users/users")>()),
  confirmMyAge: (...args: unknown[]) => confirmMyAge(...args),
}));

import { AgeConfirmationDialog } from "@/components/communities/AgeConfirmationDialog";

describe("AgeConfirmationDialog", () => {
  beforeEach(() => {
    confirmMyAge.mockReset().mockResolvedValue(undefined);
  });

  const renderDialog = (user?: ReturnType<typeof buildUser>) =>
    renderWithProviders(
      <AgeConfirmationDialog open onOpenChange={() => {}} onConfirmed={() => {}} />,
      user ? { auth: { user } } : undefined
    );

  /** Reach the date through the app's picker: open it, type the date, commit. */
  const enterBirthdate = async (date: string) => {
    await userEvent.click(await screen.findByLabelText("Date of birth"));
    const entry = await screen.findByLabelText("Type or pick a date");
    await userEvent.type(entry, `${date}{Enter}`);
    await userEvent.keyboard("{Escape}");
  };

  it("asks for a date of birth rather than offering a box to tick, and needs one", async () => {
    renderDialog();
    expect(await screen.findByRole("button", { name: "Confirm and join" })).toBeDisabled();

    await userEvent.click(await screen.findByLabelText("Date of birth"));

    // The app's own picker, not the browser's: a birthday is decades back, and
    // the year dropdown is how you get there.
    expect(await screen.findByLabelText("Type or pick a date")).toBeInTheDocument();
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
  });

  it("offers a lifetime of years to reach, and none the server would refuse", async () => {
    // Everything the calendar offers has to be a date the server accepts: born
    // by today, and no longer ago than the oldest person alive.
    renderDialog();

    await userEvent.click(await screen.findByLabelText("Date of birth"));
    const years = await screen.findByRole("combobox", { name: /year/i });
    const offered = within(years)
      .getAllByRole("option")
      .map((option) => option.textContent);

    // The server compares against the UTC date, so the window is that one.
    const thisYear = new Date().getUTCFullYear();
    expect(offered.at(-1)).toBe(String(thisYear));
    expect(offered[0]).toBe(String(thisYear - 120));
  });

  it("says what is done with the date beside the field, why it is asked, and that it is asked once", async () => {
    renderDialog();

    expect(await screen.findByText(/We don't sell your data\./)).toBeInTheDocument();
    expect(screen.getByText(/so we ask once/i)).toBeInTheDocument();
  });

  it("sends the date and nothing else", async () => {
    renderDialog();

    await enterBirthdate("1990-05-04");
    await userEvent.click(screen.getByRole("button", { name: "Confirm and join" }));

    await waitFor(() => expect(confirmMyAge).toHaveBeenCalledTimes(1));
    expect(confirmMyAge).toHaveBeenCalledWith({
      birthdate: "1990-05-04",
    });
  });

  it("offers no second attempt to an account whose answer stands", async () => {
    // Re-asking would let the answer be tried until it came out right, which
    // is the thing recording it exists to stop.
    renderDialog(
      buildUser({ age_confirmed_at: null, age_below_minimum_at: "2026-01-01T00:00:00Z" })
    );

    expect(await screen.findByText(/told us you're not old enough yet/i)).toBeInTheDocument();
    expect(screen.queryByLabelText("Date of birth")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Confirm and join" })).not.toBeInTheDocument();
    // Who can reset the question, and — so it does not read as an account shut
    // out of the app — that the communities it was invited to are unaffected.
    expect(
      screen.getByText(/ask whoever runs this server to reset the question/i)
    ).toBeInTheDocument();
    expect(screen.getByText(/communities you were invited to is unaffected/i)).toBeInTheDocument();
  });

  it("surfaces the server's answer when somebody is too young", async () => {
    confirmMyAge.mockRejectedValue({
      isAxiosError: true,
      response: { status: 422, data: { detail: "USER_AGE_BELOW_MINIMUM" } },
    });
    renderDialog();

    await enterBirthdate("2020-01-01");
    await userEvent.click(screen.getByRole("button", { name: "Confirm and join" }));

    expect(
      await screen.findByText(/16 or older to join a community anyone can find/i)
    ).toBeInTheDocument();
  });
});
