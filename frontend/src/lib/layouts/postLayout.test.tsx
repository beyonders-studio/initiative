import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it } from "vitest";

import { buildPost } from "@/__tests__/factories";
import { renderPage } from "@/__tests__/helpers/render";
import type { PostRead } from "@/api/generated/initiativeAPI.schemas";
import { DetailLayoutView } from "@/ui/layouts/DetailLayoutView";

import { POST_DETAIL } from "./postLayout";

/** A notice whose layout a manager moves the poll in, while it is open. */
const Moved = ({ post }: { post: PostRead }) => {
  const [moved, setMoved] = useState(false);
  return (
    <>
      <button type="button" onClick={() => setMoved(true)}>
        Move the poll
      </button>
      <DetailLayoutView
        detail={POST_DETAIL}
        item={post}
        layout={moved ? { main: [{ type: "poll" }], side: [] } : null}
        context={{ canEdit: true, canPin: false }}
      />
    </>
  );
};

describe("a notice's detail", () => {
  it("keeps a poll being written when the layout moves it", async () => {
    renderPage(() => <Moved post={buildPost({ poll: null })} />);
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Add a poll" }));
    await user.type(screen.getByPlaceholderText("What are you asking?"), "Lunch?");
    await user.click(screen.getByRole("button", { name: "Move the poll" }));

    expect(screen.getByPlaceholderText("What are you asking?")).toHaveValue("Lunch?");
  });
});
