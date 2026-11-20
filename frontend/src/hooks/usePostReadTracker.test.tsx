/**
 * Turning "this was on screen" into "this has been read".
 *
 * Two rules carry the feature. A notice that merely went past during a fast
 * scroll was not read, so a card has to stay on screen for a beat before it
 * counts. And *mark unread* has to stick: the card is still on screen when you
 * click it, so without suppression the observer would undo the click a second
 * later and the button would look broken.
 */
import { act, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PostReadTrackerProvider, usePostReadTracker } from "@/hooks/usePostReadTracker";

const mutate = vi.fn();
vi.mock("@/hooks/usePosts", () => ({
  useMarkPostsRead: () => ({ mutate }),
}));

function Harness({ onReady }: { onReady: (api: ReturnType<typeof usePostReadTracker>) => void }) {
  const api = usePostReadTracker();
  onReady(api);
  return null;
}

const mount = () => {
  let api!: ReturnType<typeof usePostReadTracker>;
  render(
    <PostReadTrackerProvider>
      <Harness
        onReady={(value) => {
          api = value;
        }}
      />
    </PostReadTrackerProvider>
  );
  return api;
};

describe("the post read tracker", () => {
  beforeEach(() => {
    mutate.mockClear();
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("holds the batch while more arrive, then sends each reported id once", () => {
    const api = mount();

    act(() => {
      api.report(1);
      vi.advanceTimersByTime(1_000);
      api.report(2);
      api.report(1);
      vi.advanceTimersByTime(1_000);
    });
    // The second report pushed the flush out; nothing has gone yet.
    expect(mutate).not.toHaveBeenCalled();

    act(() => {
      vi.runAllTimers();
    });
    expect(mutate).toHaveBeenCalledTimes(1);
    expect(mutate.mock.calls[0][0]).toEqual({ post_ids: [1, 2] });
  });

  it("never reads a notice somebody just marked unread, queued or not", () => {
    const api = mount();

    act(() => {
      api.report(9);
      api.suppress(9);
      api.suppress(7);
      api.report(7);
      api.report(8);
      vi.runAllTimers();
    });

    expect(mutate).toHaveBeenCalledTimes(1);
    expect(mutate.mock.calls[0][0]).toEqual({ post_ids: [8] });
  });
});
