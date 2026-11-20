import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { useWizard } from "./useWizard";

type Step = "one" | "two" | "three";

describe("useWizard", () => {
  it("starts on the initial step, and ignores back on an empty trail", () => {
    const { result } = renderHook(() => useWizard<Step>("one"));
    expect(result.current.step).toBe("one");
    expect(result.current.canGoBack).toBe(false);

    act(() => result.current.back());

    expect(result.current.step).toBe("one");
  });

  it("walks back along the route taken, recording nothing for a walk to the step showing", () => {
    const { result } = renderHook(() => useWizard<Step>("one"));

    act(() => result.current.go("two"));
    act(() => result.current.go("two"));
    act(() => result.current.go("three"));
    expect(result.current.step).toBe("three");

    act(() => result.current.back());
    expect(result.current.step).toBe("two");

    act(() => result.current.back());
    expect(result.current.step).toBe("one");
    expect(result.current.canGoBack).toBe(false);
  });

  it("commit drops the trail, so there is no way back out", () => {
    const { result } = renderHook(() => useWizard<Step>("one"));

    act(() => result.current.go("two"));
    expect(result.current.canGoBack).toBe(true);

    act(() => result.current.commit("three"));
    expect(result.current.canGoBack).toBe(false);

    act(() => result.current.back());
    expect(result.current.step).toBe("three");
  });

  it("reset returns to the initial step and clears the trail", () => {
    const { result } = renderHook(() => useWizard<Step>("one"));

    act(() => result.current.go("two"));
    act(() => result.current.go("three"));
    act(() => result.current.reset());

    expect(result.current.step).toBe("one");
    expect(result.current.canGoBack).toBe(false);
  });
});
