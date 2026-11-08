/**
 * Answering the age question changes what the rest of the page may show.
 *
 * The answer is a gate: before it, this account can reach nobody and nobody
 * can reach it; after it, it has a messaging policy, a roster and requests.
 * Anything still holding the old answer would leave the surface that asked
 * looking exactly as it did before it was answered.
 */

import { renderHook, waitFor } from "@testing-library/react";
import { AxiosError, type AxiosResponse } from "axios";
import { beforeEach, describe, expect, it, vi } from "vitest";

const confirmMyAge = vi.fn();
const refreshUser = vi.fn();
const invalidations = vi.hoisted(() => vi.fn());

vi.mock("@/api/generated/users/users", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/generated/users/users")>()),
  confirmMyAge: (...args: unknown[]) => confirmMyAge(...args),
}));

vi.mock("@/hooks/useAuth", () => ({
  useAuth: () => ({ refreshUser }),
}));

// One entry point now, so the assertion is on WHAT was named rather than on
// which of three helpers ran. `q` stays real: the specs are the comparison.
vi.mock("@/api/query-keys", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/query-keys")>()),
  invalidate: (...specs: unknown[]) => invalidations(...specs),
}));

import { q } from "@/api/query-keys";

import { useAgeConfirmation } from "./useAgeConfirmation";

beforeEach(() => {
  vi.clearAllMocks();
  confirmMyAge.mockResolvedValue(undefined);
  refreshUser.mockResolvedValue(undefined);
});

describe("confirming an age", () => {
  it("drops everything that was answered under the old one", async () => {
    const { result } = renderHook(() => useAgeConfirmation());

    result.current.setBirthdate("1990-01-01");
    await waitFor(() => expect(result.current.birthdate).toBe("1990-01-01"));
    await result.current.confirm();

    expect(confirmMyAge).toHaveBeenCalledWith({
      birthdate: "1990-01-01",
    });
    expect(refreshUser).toHaveBeenCalled();
    expect(invalidations).toHaveBeenCalledWith(q.dmSettings(), q.people(), q.contactGrants());
  });

  it("keeps what is on screen when the answer was refused", async () => {
    // A refusal changes nothing, and re-reading everything would only make the
    // page flicker on its way back to what it already said.
    confirmMyAge.mockRejectedValue(new Error("too young"));
    const { result } = renderHook(() => useAgeConfirmation());

    result.current.setBirthdate("2020-01-01");
    await waitFor(() => expect(result.current.birthdate).toBe("2020-01-01"));
    await result.current.confirm();

    expect(invalidations).not.toHaveBeenCalled();
    expect(refreshUser).not.toHaveBeenCalled();
  });

  it("re-reads the account when the answer was under age, which it records", async () => {
    confirmMyAge.mockRejectedValue(
      new AxiosError("refused", "ERR_BAD_REQUEST", undefined, undefined, {
        status: 422,
        data: { detail: "USER_AGE_BELOW_MINIMUM" },
      } as AxiosResponse)
    );
    const { result } = renderHook(() => useAgeConfirmation());

    result.current.setBirthdate("2020-01-01");
    await waitFor(() => expect(result.current.birthdate).toBe("2020-01-01"));
    await result.current.confirm();

    expect(refreshUser).toHaveBeenCalled();
    expect(invalidations).not.toHaveBeenCalled();
  });
});
