/**
 * Adding an option answers with the option the server kept, under the label
 * that was asked for — or refuses when it did not keep one.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook } from "@testing-library/react";
import { HttpResponse } from "msw";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { buildPropertyDefinition } from "@/__tests__/factories";
import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { useAppendPropertyOption } from "@/hooks/useProperties";

vi.mock("@/hooks/useActiveCommunityId", () => ({ useActiveCommunityId: () => 1 }));

const wrapper = ({ children }: { children: ReactNode }) => (
  <QueryClientProvider client={new QueryClient()}>{children}</QueryClientProvider>
);

describe("useAppendPropertyOption", () => {
  const todo = { value: "todo", label: "To do", color: null };
  const definition = buildPropertyDefinition({ id: 7, type: "select", options: [todo] });

  /** Answers with `options` held, and keeps what each write sent. */
  const answering = (options: { value: string; label: string; color: null }[]) => {
    const sent: unknown[] = [];
    server.use(
      communityHttp.patch("/property-definitions/:id", async ({ request }) => {
        sent.push(await request.json());
        return HttpResponse.json({
          definition: { ...definition, options },
          orphaned_value_count: 0,
        });
      })
    );
    return sent;
  };

  it("answers with the option the server kept", async () => {
    const done = { value: "done", label: "Done", color: null };
    const sent = answering([todo, done]);
    const { result } = renderHook(() => useAppendPropertyOption(), { wrapper });

    const added = await result.current({ id: 7, options: [todo] }, "Done");

    expect(added).toMatchObject({ value: "done", label: "Done" });
    // The options held, and the new one under a slug of its label.
    expect(sent).toEqual([{ options: [todo, done] }]);
  });

  it("refuses when the value was already taken by another label", async () => {
    answering([
      { value: "todo", label: "To do", color: null },
      { value: "done", label: "done!", color: null },
    ]);
    const { result } = renderHook(() => useAppendPropertyOption(), { wrapper });

    await expect(result.current({ id: 7, options: [todo] }, "Done")).rejects.toThrow();
  });
});
