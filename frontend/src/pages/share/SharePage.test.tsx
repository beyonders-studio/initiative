import { act, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { getPendingShare, receivedShare, setPendingShare } from "@/lib/share/pendingShare";

// Leaving the page unmounts it a moment later, as the router does: the page
// is still mounted while the navigation is under way.
let leave: () => void = () => {};
const navigate = vi.fn(async (_to: unknown) => {
  await new Promise((resolve) => setTimeout(resolve, 0));
  leave();
});
vi.mock("@tanstack/react-router", () => ({
  useRouter: () => ({ navigate }),
}));

let finish: (path?: string) => void = () => {};
vi.mock("@/pages/share/ShareWizard", () => ({
  ShareWizard: ({ onDone }: { onDone: (path?: string) => void }) => {
    finish = onDone;
    return null;
  },
}));

import { SharePage } from "./SharePage";

const renderPage = () => {
  const { unmount } = render(<SharePage />);
  leave = unmount;
};

beforeEach(() => {
  navigate.mockClear();
  setPendingShare(receivedShare({ texts: ["hello"] }));
});

afterEach(() => setPendingShare(null));

describe("SharePage", () => {
  it("goes to what was made, then lets the share go", async () => {
    renderPage();

    act(() => finish("/c/3/i/4/projects/6/tasks/77"));

    await vi.waitFor(() => expect(getPendingShare()).toBeNull());
    expect(navigate.mock.calls).toEqual([[{ to: "/c/3/i/4/projects/6/tasks/77" }]]);
  });

  it("goes home when the share is put down", async () => {
    renderPage();

    act(() => finish());

    await vi.waitFor(() => expect(getPendingShare()).toBeNull());
    expect(navigate.mock.calls).toEqual([[{ to: "/", replace: true }]]);
  });

  it("marks the share shown", () => {
    renderPage();
    expect(getPendingShare()?.opened).toBe(true);
  });

  it("goes home with nothing to share", () => {
    setPendingShare(null);
    renderPage();
    expect(navigate).toHaveBeenCalledWith({ to: "/", replace: true });
  });
});
