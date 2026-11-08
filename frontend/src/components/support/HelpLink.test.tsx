/**
 * "Ask for help" beside a notice: Help on asking about the notice's topic, Help
 * with the deployment's address, or nothing.
 */
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/__tests__/helpers/render";

type Offer = { mode: "form" | "email" | "none"; contact: string | null };

const offered = vi.hoisted(() => ({ current: undefined as Offer | undefined }));
const openHelp = vi.hoisted(() => vi.fn());

vi.mock("@/components/help/helpStore", () => ({ openHelp }));
vi.mock("@/hooks/useTickets", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/hooks/useTickets")>();
  return {
    ...actual,
    useTicketAvailability: () => ({
      data: offered.current === undefined ? undefined : { support: offered.current },
    }),
  };
});

import { HelpLink } from "./HelpLink";

describe("HelpLink", () => {
  it("is not drawn where there is nobody to ask", () => {
    offered.current = { mode: "none", contact: null };
    renderWithProviders(<HelpLink topic="community" communityId={3} />);
    expect(screen.queryByRole("button", { name: "Ask for help" })).not.toBeInTheDocument();
  });

  it("opens Help, with the address, where help requests are not taken", async () => {
    offered.current = { mode: "email", contact: "help@example.org" };
    renderWithProviders(<HelpLink topic="community" communityId={3} />);
    await userEvent.click(screen.getByRole("button", { name: "Ask for help" }));
    expect(openHelp).toHaveBeenCalledWith();
  });

  it("asks the team about the notice's topic, and lets its dialog go first", async () => {
    offered.current = { mode: "form", contact: null };
    const onAsk = vi.fn();
    renderWithProviders(<HelpLink topic="community" communityId={3} onAsk={onAsk} />);
    await userEvent.click(screen.getByRole("button", { name: "Ask for help" }));
    expect(onAsk).toHaveBeenCalled();
    expect(openHelp).toHaveBeenCalledWith({ topic: "community", communityId: 3 });
  });
});
