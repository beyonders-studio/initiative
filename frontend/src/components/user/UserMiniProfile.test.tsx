import { screen } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";

import { buildUserSummary } from "@/__tests__/factories";
import { server } from "@/__tests__/helpers/msw-server";
import { renderWithProviders } from "@/__tests__/helpers/render";
import type { UserProfile } from "@/api/generated/initiativeAPI.schemas";

import { UserMiniProfile } from "./UserMiniProfile";

const profile = (overrides: Partial<UserProfile> = {}): UserProfile => ({
  id: 12,
  username: "ada",
  discriminator: 7,
  avatar_url: null,
  status: "active",
  custom_status: { emoji: "📐", text: "Writing the note", clear_at: null },
  profile_decorations: {
    banner: "core.aurora",
    frame: null,
    frame_tint: [],
    trophies: ["plants.morel"],
    grad_year: null,
  },
  presence: "online",
  joined_at: "2026-01-12T00:00:00Z",
  ...overrides,
});

const answerWithProfile = (body: UserProfile | null, status = 200) =>
  server.use(
    http.get("*/api/v1/users/:handle/profile", () =>
      status === 200 ? HttpResponse.json(body) : new HttpResponse(null, { status })
    )
  );

describe("the card a mention opens", () => {
  it("says what they are up to, what they are wearing, and when they joined", async () => {
    answerWithProfile(profile());

    renderWithProviders(<UserMiniProfile handle="ada0007" />);

    expect(await screen.findByText("Writing the note")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Morel" })).toBeInTheDocument();
    expect(screen.getByText("Joined")).toBeInTheDocument();
  });

  it("names them before the profile arrives, from what the page already knew", () => {
    answerWithProfile(profile());

    renderWithProviders(
      <UserMiniProfile
        handle="ada0007"
        summary={buildUserSummary({
          id: 12,
          username: "ada",
          discriminator: 7,
          display_name: "Ada King",
        })}
      />
    );

    // No `find`: the card is filled from the summary on its first render, so
    // hovering never shows an empty box.
    expect(screen.getByText("Ada King")).toBeInTheDocument();
    expect(screen.getByTitle("ada#0007")).toBeInTheDocument();
  });

  it("says nothing is there when the account cannot be read", async () => {
    // Deleted, or never this reader's to see. The server does not distinguish
    // them, so neither does the card.
    answerWithProfile(null, 404);

    renderWithProviders(<UserMiniProfile handle="ghost0001" />);

    expect(await screen.findByText("No profile here")).toBeInTheDocument();
  });

  it("leaves out a status nobody set", async () => {
    answerWithProfile(profile({ custom_status: { emoji: null, text: null, clear_at: null } }));

    renderWithProviders(<UserMiniProfile handle="ada0007" />);

    expect(await screen.findByText("Joined")).toBeInTheDocument();
    expect(screen.queryByText("Say what you're up to")).not.toBeInTheDocument();
  });
});
