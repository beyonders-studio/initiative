/**
 * The list under a half-typed mention is walked with the arrow keys, and the
 * list `[[` offers is no exception.
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { buildInitiative } from "@/__tests__/factories";
import type { SearchSuggestion } from "@/api/generated/initiativeAPI.schemas";
import { type ActiveMention, activeMention } from "@/lib/mentions";
import { linkableToolTypes } from "@/lib/references";

import { MentionPopover } from "./MentionPopover";

const initiative = buildInitiative();
const items: SearchSuggestion[] = ["Roadmap", "Budget"].map((title, index) => ({
  entity_type: linkableToolTypes(initiative)[0],
  entity_id: index + 1,
  title,
}));

vi.mock("@/hooks/useInitiatives", () => ({ useInitiative: () => ({ data: initiative }) }));
vi.mock("@/hooks/useSearch", () => ({
  useCommunityPickerSuggestions: () => ({ items, isLoading: false }),
}));
vi.mock("@/hooks/useUsers", () => ({
  useMemberSearch: () => ({ data: undefined, isLoading: false }),
}));

describe("the mention picker", () => {
  it("moves through what [[ offers with the arrow keys", () => {
    render(
      <MentionPopover
        active={activeMention("see [[") as ActiveMention}
        initiativeId={initiative.id}
        onSelect={vi.fn()}
        onClose={vi.fn()}
      />
    );

    fireEvent.keyDown(document, { key: "ArrowDown" });

    expect(screen.getByRole("button", { name: "Budget" })).toHaveClass("bg-accent");
    expect(screen.getByRole("button", { name: "Roadmap" })).not.toHaveClass("bg-accent");
  });
});
