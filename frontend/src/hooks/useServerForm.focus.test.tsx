/**
 * The two halves of this together.
 *
 * The client refetches what has gone stale when a window comes back to the
 * front. That is the point — a tab left in the background has no other way to
 * learn what changed. It is also the moment a form is most likely to be
 * half-written, so the two only make sense as a pair, and nothing else asserts
 * them as one.
 */
import { focusManager, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { queryClient } from "@/lib/queryClient";

import { useServerForm } from "./useServerForm";

interface Entity {
  id: number;
  name: string;
}

const wrapper = ({ children }: { children: ReactNode }) => (
  <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
);

/** Leave the window and come back, which is what the focus manager calls a focus. */
const refocus = () =>
  act(() => {
    focusManager.setFocused(false);
    focusManager.setFocused(true);
  });

/** Backdate the cached answer so the return finds it stale and asks again. */
const age = (key: readonly unknown[]) =>
  queryClient.setQueryData(key, queryClient.getQueryData(key), {
    updatedAt: Date.now() - 10 * 60_000,
  });

/** A form fed by a real query on the app's own client, as a page has it. */
const renderQueriedForm = (queryFn: () => Promise<Entity>) =>
  renderHook(
    () => {
      const query = useQuery<Entity>({ queryKey: ["entity", 7], queryFn });
      return useServerForm(query.data, (e) => ({ name: e?.name ?? "" }), query.data?.id);
    },
    { wrapper }
  );

afterEach(() => {
  focusManager.setFocused(undefined);
  queryClient.clear();
});

describe("coming back to a window mid-edit", () => {
  it("keeps what is being typed, even though the answer changed while away", async () => {
    let name = "Q3 Roadmap";
    const queryFn = vi.fn(async () => ({ id: 7, name }));
    const { result } = renderQueriedForm(queryFn);
    await waitFor(() => expect(result.current.values.name).toBe("Q3 Roadmap"));

    act(() => result.current.set({ name: "Half-written" }));
    name = "Renamed by somebody else";
    age(["entity", 7]);
    refocus();

    await waitFor(() => expect(queryFn).toHaveBeenCalledTimes(2));
    expect(result.current.values.name).toBe("Half-written");
  });

  it("catches the form up when nobody is typing in it", async () => {
    let name = "Q3 Roadmap";
    const queryFn = vi.fn(async () => ({ id: 7, name }));
    const { result } = renderQueriedForm(queryFn);
    await waitFor(() => expect(result.current.values.name).toBe("Q3 Roadmap"));

    name = "Renamed by somebody else";
    age(["entity", 7]);
    refocus();

    await waitFor(() => expect(result.current.values.name).toBe("Renamed by somebody else"));
  });

  it("does not count a save as covering what was typed while it was in flight", async () => {
    // The round trip is the window: press Save, keep typing, and the reply is
    // for the older text. Returning to the tab must not then bring that back.
    let name = "Q3 Roadmap";
    const queryFn = vi.fn(async () => ({ id: 7, name }));
    const { result } = renderQueriedForm(queryFn);
    await waitFor(() => expect(result.current.values.name).toBe("Q3 Roadmap"));

    act(() => result.current.set({ name: "Sent" }));
    const sent = result.current.values;
    act(() => result.current.set({ name: "Sent, and then some" }));
    act(() => result.current.settle(sent));

    name = "Sent";
    age(["entity", 7]);
    refocus();

    await waitFor(() => expect(queryFn).toHaveBeenCalledTimes(2));
    expect(result.current.values.name).toBe("Sent, and then some");
    expect(result.current.edited).toBe(true);
  });

  it("asks for nothing while the answer is still fresh", async () => {
    const queryFn = vi.fn(async () => ({ id: 7, name: "Q3 Roadmap" }));
    const { result } = renderQueriedForm(queryFn);
    await waitFor(() => expect(result.current.values.name).toBe("Q3 Roadmap"));

    refocus();
    await Promise.resolve();

    expect(queryFn).toHaveBeenCalledTimes(1);
  });
});
