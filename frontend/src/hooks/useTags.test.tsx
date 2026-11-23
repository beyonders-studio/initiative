import { QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { createTestQueryClient } from "@/__tests__/helpers/render";

const mocks = vi.hoisted(() => ({ error: vi.fn(), success: vi.fn() }));

vi.mock("@/lib/mascotToast", () => ({
  toast: { error: mocks.error, success: mocks.success },
}));
vi.mock("@/hooks/useActiveCommunityId", () => ({ useActiveCommunityId: () => 1 }));
vi.mock("@/api/generated/tags/tags", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  deleteTag: () => Promise.reject(new Error("refused")),
}));

import { useDeleteTag } from "./useTags";

const wrapper = ({ children }: { children: ReactNode }) => (
  <QueryClientProvider client={createTestQueryClient()}>{children}</QueryClientProvider>
);

describe("useDeleteTag", () => {
  beforeEach(() => vi.clearAllMocks());

  it("says so when a delete fails", async () => {
    const { result } = renderHook(() => useDeleteTag(), { wrapper });

    result.current.mutate(5);

    await waitFor(() => expect(mocks.error).toHaveBeenCalledTimes(1));
  });

  it("leaves a silent caller to report the failure once, itself", async () => {
    const { result } = renderHook(() => useDeleteTag({ silent: true }), { wrapper });

    await expect(result.current.mutateAsync(5)).rejects.toThrow("refused");

    expect(mocks.error).not.toHaveBeenCalled();
  });
});
