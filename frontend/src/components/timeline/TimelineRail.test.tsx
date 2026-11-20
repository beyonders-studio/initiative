/**
 * The reusable timeline rail.
 *
 * Written against the generic contract rather than any tool's shape, because
 * that is the thing being kept: a rail that only worked for posts would have to
 * be rewritten for the next tool that wants one.
 *
 * What is load-bearing is that it is a *list of buttons* with dragging layered
 * on top, not a drag surface with buttons bolted beside it — that is what makes
 * it reachable by keyboard and readable by a screen reader, and what makes the
 * same control work on a phone.
 */
import fs from "node:fs";
import path from "node:path";

import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { TimelineRail, type TimelineStop } from "./TimelineRail";

const stops = [
  { period: "2026-03", count: 9 },
  { period: "2026-01", count: 1 },
  { period: "2025-12", count: 4 },
];

const label = (stop: TimelineStop) => `Month ${stop.period}`;
const group = (stop: TimelineStop) => stop.period.slice(0, 4);

const renderRail = (props: Partial<Parameters<typeof TimelineRail>[0]> = {}) =>
  render(
    <TimelineRail
      stops={stops}
      onPick={vi.fn()}
      formatLabel={label}
      formatGroup={group}
      {...props}
    />
  );

/** The rail itself — the element that says which state it is in. */
const rail = () => document.querySelector<HTMLElement>("[data-state]") as HTMLElement;

describe("TimelineRail", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  // The rail is a drag surface with real buttons inside it. A tap on a button
  // fires the button's own click AND bubbles through the rail's pointerup, so
  // without a guard one activation runs a consumer's callback twice.
  it("offers every period as its own button, handing back the whole stop once per tap", async () => {
    const onPick = vi.fn();
    renderRail({ onPick });

    for (const stop of stops) {
      expect(screen.getByRole("button", { name: label(stop) })).toBeInTheDocument();
    }
    await userEvent.click(screen.getByRole("button", { name: "Month 2025-12" }));

    expect(onPick).toHaveBeenCalledTimes(1);
    expect(onPick).toHaveBeenCalledWith(stops[2]);
  });

  it("labels a year once, where it changes", () => {
    renderRail();

    // Three stops across two years: 2026 is labelled at the first of its two,
    // not at both, so the rail reads as a run of months under a year.
    expect(screen.getAllByText("2026")).toHaveLength(1);
    expect(screen.getAllByText("2025")).toHaveLength(1);
  });

  it("marks where the feed actually is", () => {
    renderRail({ activePeriod: "2026-01" });

    expect(screen.getByRole("button", { name: "Month 2026-01" })).toHaveAttribute(
      "aria-current",
      "true"
    );
    expect(screen.getByRole("button", { name: "Month 2026-03" })).not.toHaveAttribute(
      "aria-current"
    );
  });

  it("draws nothing at all when there is nowhere to jump", () => {
    const { container } = renderRail({ stops: [] });

    expect(container).toBeEmptyDOMElement();
  });

  // A tick's length is its share of the busiest period. Without it a year of
  // quiet months and one loud one look identical, and the rail stops being a
  // picture of the feed.
  it("draws a busy period longer than a quiet one", () => {
    const { container } = renderRail();
    const widths = [...container.querySelectorAll<HTMLElement>("button > span")].map((tick) =>
      Number.parseInt(tick.style.width, 10)
    );

    expect(widths[0]).toBeGreaterThan(widths[2]);
    expect(widths[2]).toBeGreaterThan(widths[1]);
  });

  it("keeps the quietest period big enough to hit", () => {
    const { container } = renderRail({
      stops: [
        { period: "2026-03", count: 500 },
        { period: "2026-02", count: 1 },
      ],
    });
    const ticks = [...container.querySelectorAll<HTMLElement>("button > span")];

    expect(Number.parseInt(ticks[1].style.width, 10)).toBeGreaterThanOrEqual(30);
  });

  // The rail overlays the feed on a phone, so what it costs when nobody is
  // using it is the whole point: nothing drawn, and nothing to tap by accident
  // over the notice underneath.
  it("stays out of the way until the feed moves", () => {
    vi.useFakeTimers();
    renderRail();

    expect(rail()).toHaveAttribute("data-state", "idle");

    act(() => {
      window.dispatchEvent(new Event("scroll"));
    });
    expect(rail()).toHaveAttribute("data-state", "peek");

    // And it goes away again once the reader settles, rather than sitting over
    // what they stopped to read.
    act(() => {
      vi.advanceTimersByTime(2000);
    });
    expect(rail()).toHaveAttribute("data-state", "idle");
  });

  // Peeking is a thumb saying where you are. The months themselves — ticks,
  // years, the bubble — are what grabbing it is for.
  it("opens the whole rail once it is grabbed", () => {
    renderRail();

    fireEvent.pointerDown(rail(), { clientY: 10 });
    expect(rail()).toHaveAttribute("data-state", "open");

    fireEvent.pointerUp(rail(), { clientY: 10 });
    expect(rail()).toHaveAttribute("data-state", "idle");
  });

  // The thumb is the handle, not a stop: a tap on it opens the rail, and
  // re-anchoring the feed to the month it was already showing would be a jolt
  // in exchange for nothing.
  it("does not jump when the thumb is tapped rather than dragged", () => {
    const onPick = vi.fn();
    const { container } = renderRail({ onPick });
    const thumb = container.querySelector('[data-slot="timeline-thumb"]');

    fireEvent.pointerDown(rail(), { clientY: 10 });
    fireEvent.pointerUp(rail(), { clientY: 10, target: thumb });

    expect(onPick).not.toHaveBeenCalled();
  });

  // The rail lives beside a feed somebody is reading. Anything drawn outside
  // its own width lands on that feed — which is exactly what a year label
  // positioned `right-full` did. The one deliberate exception is the drag
  // bubble, a transient readout that is meant to float clear of the rail.
  it("keeps its labels inside its own width", () => {
    const source = fs
      .readFileSync(path.resolve(__dirname, "./TimelineRail.tsx"), "utf-8")
      // Comments explain the rule; only the classes actually applied count.
      .replace(/\/\*[\s\S]*?\*\//g, "")
      .replace(/\/\/.*$/gm, "");
    const escapes = [...source.matchAll(/(right-full|left-full)/g)];
    const bubble = [...source.matchAll(/role="status"[\s\S]{0,400}?(right-full|left-full)/g)];

    expect(escapes).toHaveLength(bubble.length);
  });
});
