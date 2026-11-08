import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { buildUserSummary } from "@/__tests__/factories";
import { server } from "@/__tests__/helpers/msw-server";
import { renderWithProviders } from "@/__tests__/helpers/render";
import type { MentionChoice } from "@/components/comments/MentionPopover";

import { MentionComposer } from "./MentionComposer";

// The picker's rows come from the roster and the search index; a test only
// needs to choose one, so it offers each kind of choice as a button.
vi.mock("@/components/comments/MentionPopover", () => ({
  MentionPopover: ({ onSelect }: { onSelect: (choice: MentionChoice) => void }) => (
    <div>
      <button
        type="button"
        onClick={() =>
          onSelect({
            user: true,
            id: 4,
            label: "Ada",
            member: buildUserSummary({ id: 4, display_name: "Ada" }),
          })
        }
      >
        pick-person
      </button>
      <button type="button" onClick={() => onSelect({ user: false, create: "Roadmap" })}>
        pick-create
      </button>
    </div>
  ),
}));

vi.mock("@/components/references/CreateReferencedThingDialog", () => ({
  CreateReferencedThingDialog: ({
    name,
    onCreated,
  }: {
    name: string;
    onCreated: (made: { entityType: string; entityId: number; name: string }) => void;
  }) => (
    <button type="button" onClick={() => onCreated({ entityType: "project", entityId: 9, name })}>
      make-it
    </button>
  ),
}));

const Host = ({
  initial = "",
  onKeyDown,
  onChange,
}: {
  initial?: string;
  onKeyDown?: () => void;
  onChange?: (value: string) => void;
}) => {
  const [value, setValue] = useState(initial);
  return (
    <MentionComposer
      value={value}
      onChange={(next) => {
        setValue(next);
        onChange?.(next);
      }}
      initiativeId={1}
      onKeyDown={onKeyDown}
    />
  );
};

const field = () => screen.getByRole("textbox") as HTMLTextAreaElement;

describe("the mention composer", () => {
  it("writes a chosen person in place of what was typed", async () => {
    const user = userEvent.setup();
    renderWithProviders(<Host />);

    await user.type(field(), "ask @ad");
    await user.click(await screen.findByRole("button", { name: "pick-person" }));

    expect(field()).toHaveValue("ask @[Ada](4) ");
  });

  it("shows a saved mention by the name the person goes by, changing nothing until someone types", async () => {
    server.use(
      http.get("*/api/v1/c/:communityId/users/search", () =>
        HttpResponse.json({
          items: [buildUserSummary({ id: 4, display_name: "Ada King" })],
          total: 1,
          page: 1,
          page_size: 100,
        })
      )
    );
    const onChange = vi.fn();
    const user = userEvent.setup();
    renderWithProviders(<Host initial="ask @[](4) and @[](5)" onChange={onChange} />);

    // Somebody the page cannot name is left as it was stored.
    await waitFor(() => expect(field()).toHaveValue("ask @[Ada King](4) and @[](5)"));
    expect(onChange).not.toHaveBeenCalled();

    await user.type(field(), "!");
    expect(onChange).toHaveBeenLastCalledWith("ask @[Ada King](4) and @[](5)!");
  });

  it("puts a thing made from [[ where the [[ was, not at the end", async () => {
    const user = userEvent.setup();
    renderWithProviders(<Host initial=" and more" />);

    // `[` opens a key name in user-event, so each one is typed doubled.
    await user.type(field(), "see [[[[Roadmap", {
      initialSelectionStart: 0,
      initialSelectionEnd: 0,
    });
    await user.click(await screen.findByRole("button", { name: "pick-create" }));
    await user.click(await screen.findByRole("button", { name: "make-it" }));

    expect(field()).toHaveValue("see #project[Roadmap](9)  and more");
  });

  it("keeps the caller's keys away while a mention is being picked", async () => {
    const onKeyDown = vi.fn();
    const user = userEvent.setup();
    renderWithProviders(<Host onKeyDown={onKeyDown} />);

    await user.type(field(), "@a");
    expect(onKeyDown).toHaveBeenCalledTimes(1);

    await user.keyboard("{Control>}{Enter}{/Control}");
    await waitFor(() => expect(onKeyDown).toHaveBeenCalledTimes(1));
  });
});
