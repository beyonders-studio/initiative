import "@testing-library/jest-dom/vitest";
// jsdom ships neither of these, and a browser on a secure origin has both.
// Code that asks whether it can keep a key store here should get a browser's
// answer rather than a gap in the test environment.
import "fake-indexeddb/auto";

import { webcrypto } from "node:crypto";
import { readFileSync } from "node:fs";
import path from "node:path";

import { cleanup, configure } from "@testing-library/react";
import { afterAll, afterEach, beforeAll, beforeEach, vi } from "vitest";

import { resetStoreSelling } from "@/lib/storeSelling";

import { resetFactories } from "./factories";
import { server } from "./helpers/msw-server";
import "./helpers/i18n-test";

// findBy/waitFor keep their own ceiling, separate from vitest's testTimeout, and
// it defaults to one second. A whole-suite run has every worker transforming the
// app's import graphs at once, so a query that resolves promptly in isolation can
// sit queued past that and fail on the clock rather than the assertion. Kept well
// under testTimeout so a genuinely stuck wait still reports as the wait it was.
configure({ asyncUtilTimeout: 5_000 });

// ---------------------------------------------------------------------------
// Global Capacitor mocks – these modules are imported at the top level by many
// source files. Providing no-op stubs prevents "Cannot find module" errors in
// the jsdom test environment.
// ---------------------------------------------------------------------------

// jsdom's crypto has getRandomValues and no subtle. Node's has both, and it is
// the same Web Crypto API a browser exposes.
if (globalThis.crypto?.subtle === undefined) {
  Object.defineProperty(globalThis, "crypto", { value: webcrypto, configurable: true });
}

vi.mock("@capacitor/core", () => ({
  Capacitor: {
    isNativePlatform: () => false,
    getPlatform: () => "web",
    convertFileSrc: (url: string) => url,
  },
  // Native plugin registration is a no-op on web. Needed by any test that
  // imports a module graph reaching a registerPlugin call — the route tree
  // does, via the authenticated layout.
  registerPlugin: (_name: string, implementations?: { web?: () => unknown }) =>
    implementations?.web?.() ?? {},
  // The native HTTP client, done the way its web implementation does it:
  // through fetch, so msw answers it.
  CapacitorHttp: (() => {
    const request = async (options: {
      url: string;
      method?: string;
      headers?: Record<string, string>;
      data?: unknown;
    }) => {
      const response = await fetch(options.url, {
        method: options.method ?? "GET",
        headers: options.headers,
        body: options.data === undefined ? undefined : JSON.stringify(options.data),
      });
      const json = (response.headers.get("content-type") ?? "").includes("application/json");
      return {
        status: response.status,
        headers: Object.fromEntries(response.headers.entries()),
        data: json ? await response.json() : await response.text(),
        url: response.url,
      };
    };
    return {
      request,
      get: (options: { url: string }) => request({ ...options, method: "GET" }),
      post: (options: { url: string }) => request({ ...options, method: "POST" }),
      delete: (options: { url: string }) => request({ ...options, method: "DELETE" }),
    };
  })(),
}));

vi.mock("@capacitor/device", () => ({
  Device: {
    getInfo: vi.fn().mockResolvedValue({
      model: "test",
      platform: "web",
      operatingSystem: "unknown",
      osVersion: "0",
      manufacturer: "test",
      isVirtual: true,
      name: "Test Device",
    }),
    getId: vi.fn().mockResolvedValue({ identifier: "test-id" }),
  },
}));

vi.mock("@capacitor/browser", () => ({
  Browser: {
    open: vi.fn().mockResolvedValue(undefined),
    close: vi.fn().mockResolvedValue(undefined),
    addListener: vi.fn().mockResolvedValue({ remove: vi.fn() }),
  },
}));

vi.mock("@capacitor/preferences", () => ({
  Preferences: {
    get: vi.fn().mockResolvedValue({ value: null }),
    set: vi.fn().mockResolvedValue(undefined),
    remove: vi.fn().mockResolvedValue(undefined),
    keys: vi.fn().mockResolvedValue({ keys: [] }),
    clear: vi.fn().mockResolvedValue(undefined),
  },
}));

vi.mock("@capacitor-community/safe-area", () => ({
  SafeArea: {
    enable: vi.fn().mockResolvedValue(undefined),
    disable: vi.fn().mockResolvedValue(undefined),
    getStatusBarHeight: vi.fn().mockResolvedValue({ statusBarHeight: 0 }),
    getSafeAreaInsets: vi.fn().mockResolvedValue({
      insets: { top: 0, right: 0, bottom: 0, left: 0 },
    }),
    addListener: vi.fn().mockResolvedValue({ remove: vi.fn() }),
  },
}));

vi.mock("@capacitor/push-notifications", () => ({
  PushNotifications: {
    requestPermissions: vi.fn().mockResolvedValue({ receive: "granted" }),
    register: vi.fn().mockResolvedValue(undefined),
    addListener: vi.fn().mockResolvedValue({ remove: vi.fn() }),
    removeAllListeners: vi.fn().mockResolvedValue(undefined),
    getDeliveredNotifications: vi.fn().mockResolvedValue({ notifications: [] }),
  },
}));

vi.mock("@capacitor/app", () => ({
  App: {
    addListener: vi.fn().mockResolvedValue({ remove: vi.fn() }),
    removeAllListeners: vi.fn().mockResolvedValue(undefined),
    getInfo: vi.fn().mockResolvedValue({ id: "test", name: "test", version: "0.0.0", build: "0" }),
    exitApp: vi.fn(),
  },
}));

// ---------------------------------------------------------------------------
// jsdom shims – APIs not implemented in jsdom that components rely on
// ---------------------------------------------------------------------------

// The breakpoints, which useWidthClass reads from :root. jsdom
// loads no stylesheet, so they are set here from the one styles.css declares.
const stylesheet = readFileSync(path.join(import.meta.dirname, "../styles.css"), "utf8");
for (const [, name, value] of stylesheet.matchAll(/--breakpoint-([a-z-]+):\s*([^;]+);/g)) {
  document.documentElement.style.setProperty(`--breakpoint-${name}`, value);
}

const matchesWidth = (query: string): boolean => {
  const width = /^\(width >= ([\d.]+)rem\)$/.exec(query);
  return width ? window.innerWidth >= Number(width[1]) * 16 : false;
};

Object.defineProperty(window, "matchMedia", {
  writable: true,
  value: vi.fn().mockImplementation((query: string) => ({
    // A breakpoint's query is answered against the window, which jsdom makes
    // 1024px wide: md, with the sidebar docked. Anything else is false.
    matches: matchesWidth(query),
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })),
});

// ResizeObserver is used by many UI components (popovers, data tables, etc.)
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
window.ResizeObserver = ResizeObserverStub as unknown as typeof ResizeObserver;

// IntersectionObserver is what a carousel asks for the moment it mounts, and
// what LazyImage asks for before it fetches. jsdom has neither, so a component
// that scrolls or lazy-loads throws instead of rendering.
//
// The stub reports everything it is given as on screen, straight away. There is
// no viewport in jsdom to be outside of, and a test asserting "the card draws
// its picture" is asking what the component renders, not what a scroll position
// would have revealed.
class IntersectionObserverStub {
  readonly root = null;
  readonly rootMargin = "";
  readonly thresholds: ReadonlyArray<number> = [];

  constructor(private readonly callback: IntersectionObserverCallback) {}

  observe(target: Element) {
    this.callback(
      [{ target, isIntersecting: true, intersectionRatio: 1 } as IntersectionObserverEntry],
      this as unknown as IntersectionObserver
    );
  }
  unobserve() {}
  disconnect() {}
  takeRecords(): IntersectionObserverEntry[] {
    return [];
  }
}
window.IntersectionObserver = IntersectionObserverStub as unknown as typeof IntersectionObserver;
globalThis.IntersectionObserver =
  IntersectionObserverStub as unknown as typeof IntersectionObserver;

// Radix UI uses PointerEvent APIs that jsdom doesn't implement. Without these
// shims Select/Popover trigger interactions crash before opening the menu.
if (!("PointerEvent" in window)) {
  // jsdom is missing PointerEvent; fall back to MouseEvent which satisfies
  // Radix's `new PointerEvent(...)` constructor usage in test.
  (window as unknown as { PointerEvent: typeof MouseEvent }).PointerEvent =
    MouseEvent as unknown as typeof MouseEvent;
}
if (!HTMLElement.prototype.hasPointerCapture) {
  HTMLElement.prototype.hasPointerCapture = () => false;
}
if (!HTMLElement.prototype.releasePointerCapture) {
  HTMLElement.prototype.releasePointerCapture = () => {};
}
if (!HTMLElement.prototype.setPointerCapture) {
  HTMLElement.prototype.setPointerCapture = () => {};
}
if (!HTMLElement.prototype.scrollIntoView) {
  HTMLElement.prototype.scrollIntoView = () => {};
}

// jsdom has no layout engine, so a Range cannot measure itself. The document
// editor measures the caret to place its floating toolbars.
if (!Range.prototype.getClientRects) {
  Range.prototype.getClientRects = () =>
    ({ length: 0, item: () => null, [Symbol.iterator]: function* () {} }) as unknown as DOMRectList;
}
if (!Range.prototype.getBoundingClientRect) {
  Range.prototype.getBoundingClientRect = () =>
    ({
      x: 0,
      y: 0,
      top: 0,
      left: 0,
      right: 0,
      bottom: 0,
      width: 0,
      height: 0,
      toJSON: () => ({}),
    }) as DOMRect;
}

// jsdom's Blob implements arrayBuffer() but not stream(). MSW hands mocked
// blob bodies to Node's Response constructor, which calls stream() on them.
if (typeof Blob.prototype.stream !== "function") {
  Blob.prototype.stream = function stream(this: Blob) {
    const blob = this;
    return new ReadableStream<Uint8Array<ArrayBuffer>>({
      async start(controller) {
        controller.enqueue(new Uint8Array(await blob.arrayBuffer()));
        controller.close();
      },
    });
  };
}

// ---------------------------------------------------------------------------
// MSW lifecycle
// ---------------------------------------------------------------------------

beforeAll(() => {
  server.listen({ onUnhandledFrame: "warn" });
});

// Taken before any test fakes the timers, so the tick below always passes.
const realSetTimeout = globalThis.setTimeout;

afterEach(async () => {
  // Unmounting can still send a request (a field saving as it loses focus):
  // one tick lets this test's handlers answer it, not the next test's.
  cleanup();
  await new Promise((resolve) => realSetTimeout(resolve, 0));
  server.resetHandlers();
  localStorage.clear();
});

afterAll(() => {
  server.close();
});

// ---------------------------------------------------------------------------
// Reset factory ID counters between tests
// ---------------------------------------------------------------------------

beforeEach(() => {
  resetFactories();
  // Whether this device may sell is asked once per app run; each test is a run.
  resetStoreSelling();
});
