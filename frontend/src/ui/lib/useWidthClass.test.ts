import { readFileSync } from "node:fs";
import path from "node:path";

import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { atLeast, useRegionWidthClass, useWidthClass, WIDTH_CLASSES } from "./useWidthClass";

const stylesheet = readFileSync(path.join(import.meta.dirname, "../styles.css"), "utf8");

const breakpoints = Object.fromEntries(
  [...stylesheet.matchAll(/--breakpoint-([a-z]+):\s*([^;]+);/g)].map(([, name, value]) => [
    name,
    value,
  ])
);

describe("widths", () => {
  it("declares a breakpoint for every class above base, and a canvas variant at the same width", () => {
    expect(Object.keys(breakpoints)).toEqual(WIDTH_CLASSES.slice(1));
    const canvas = Object.fromEntries(
      [
        ...stylesheet.matchAll(
          /@custom-variant canvas-([a-z]+)\s*\{\s*(?:\/\*[^*]*\*\/\s*)?@container \(width >= ([^)]+)\)/g
        ),
      ].map(([, name, value]) => [name, value])
    );
    expect(canvas).toEqual(breakpoints);
  });

  it("reads the screen's class from the breakpoints styles.css declares", () => {
    const from = (name: string) => `(width >= ${breakpoints[name]})`;
    const asked: string[] = [];
    vi.mocked(window.matchMedia).mockImplementation((query: string) => {
      asked.push(query);
      return {
        matches: query === from("sm") || query === from("md"),
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
      } as unknown as MediaQueryList;
    });

    const { result } = renderHook(() => useWidthClass());

    expect(result.current).toBe("md");
    expect(asked).toContain(from("xl"));
  });

  it("follows a region's width once it mounts, and lets go of one it no longer measures", () => {
    const observers: { callback: ResizeObserverCallback; observed: Element[] }[] = [];
    vi.stubGlobal(
      "ResizeObserver",
      class {
        observed: Element[] = [];
        constructor(public callback: ResizeObserverCallback) {
          observers.push(this);
        }
        observe(element: Element) {
          this.observed.push(element);
        }
        disconnect() {
          this.observed = [];
        }
      }
    );
    const resize = (width: number) =>
      act(() => {
        const observer = observers.at(-1);
        observer?.callback(
          [{ contentRect: { width } } as ResizeObserverEntry],
          observer as unknown as ResizeObserver
        );
      });
    const first = document.createElement("div");
    const second = document.createElement("div");

    const { result, rerender } = renderHook(({ region }) => useRegionWidthClass(region), {
      initialProps: { region: null as HTMLElement | null },
    });
    expect(result.current).toBe("base");

    rerender({ region: first });
    resize(900);
    expect(result.current).toBe("md");
    resize(500);
    expect(result.current).toBe("base");

    rerender({ region: second });
    expect(observers[0]?.observed).toEqual([]);
    resize(1300);
    expect(result.current).toBe("lg");
  });

  it("orders the classes narrowest first", () => {
    expect(atLeast("lg", "md")).toBe(true);
    expect(atLeast("sm", "md")).toBe(false);
  });
});
