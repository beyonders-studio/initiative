import { screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/__tests__/helpers/render";
import { dateTimeFormat } from "@/ui/lib/intl";

const state = vi.hoisted(() => ({
  summaries: [] as unknown[],
  values: {} as Record<string, unknown> | undefined,
  rows: [] as Record<string, unknown>[],
  error: false,
  asked: [] as number[],
}));

vi.mock("@/hooks/useActiveCommunityId", () => ({ useActiveCommunityId: () => 7 }));
vi.mock("@/api/generated/plugins/plugins", () => ({
  useListPluginSummaries: () => ({ data: { items: state.summaries } }),
  useReadPluginSummary: (_communityId: number, pluginId: number) => {
    state.asked.push(pluginId);
    return {
      data: state.values === undefined ? undefined : { values: state.values, rows: state.rows },
      isError: state.error,
    };
  },
}));

import { PluginSummaryCards } from "./PluginSummaryCards";

// A moment, so the calendar day it falls on depends on where the reader is.
const RESETS_ON = "2026-11-15T12:00:00Z";

const summary = (returns: unknown[]) => ({ plugin_id: 3, name: "Meter", returns });

const ALLOWANCE = [
  { key: "used", type: "int", label: { en: "Runs this month" }, of: "allowed" },
  { key: "allowed", type: "int", label: { en: "Monthly allowance" } },
  { key: "left", type: "int", label: { en: "Credits left" } },
  { key: "resets_on", type: "datetime", label: { en: "Resets" } },
];

describe("PluginSummaryCards", () => {
  beforeEach(() => {
    state.summaries = [summary(ALLOWANCE)];
    state.values = { used: 250, allowed: 500, left: 1500, resets_on: RESETS_ON };
    state.rows = [];
    state.error = false;
    state.asked = [];
  });

  it("draws each figure under the plug-in's own label, a pair as one measure", () => {
    renderWithProviders(<PluginSummaryCards />);
    expect(screen.getByText("Meter")).toBeInTheDocument();
    expect(screen.getByText("Runs this month")).toBeInTheDocument();
    expect(screen.getByText("250 of 500")).toBeInTheDocument();
    expect(screen.getByRole("progressbar")).toBeInTheDocument();
    // The ceiling is inside the measure, not a row of its own.
    expect(screen.queryByText("Monthly allowance")).not.toBeInTheDocument();
    expect(screen.getByText("Credits left")).toBeInTheDocument();
    expect(screen.getByText("1,500")).toBeInTheDocument();
    const resets = dateTimeFormat("en", { dateStyle: "long" }).format(new Date(RESETS_ON));
    expect(screen.getByText(resets)).toBeInTheDocument();
  });

  it("draws a figure with no ceiling alone", () => {
    state.values = { used: 250, allowed: null, left: 0 };
    renderWithProviders(<PluginSummaryCards />);
    expect(screen.getByText("250")).toBeInTheDocument();
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
  });

  it("draws a zero ceiling as one, full", () => {
    state.values = { used: 1, allowed: 0, left: 0 };
    renderWithProviders(<PluginSummaryCards />);
    expect(screen.getByText("1 of 0")).toBeInTheDocument();
    expect(screen.getByRole("progressbar")).toBeInTheDocument();
  });

  it("keeps a ceiling that is itself a measure", () => {
    state.summaries = [
      summary([
        { key: "used", type: "int", label: { en: "Used" }, of: "allowed" },
        { key: "allowed", type: "int", label: { en: "Allowed" }, of: "total" },
        { key: "total", type: "int", label: { en: "Total" } },
      ]),
    ];
    state.values = { used: 1, allowed: 4, total: 10 };
    renderWithProviders(<PluginSummaryCards />);
    expect(screen.getByText("1 of 4")).toBeInTheDocument();
    expect(screen.getByText("Allowed")).toBeInTheDocument();
    expect(screen.getByText("4 of 10")).toBeInTheDocument();
    expect(screen.queryByText("Total")).not.toBeInTheDocument();
  });

  it("draws a yes-or-no and a list", () => {
    state.summaries = [
      summary([
        { key: "connected", type: "bool", label: { en: "Connected" } },
        { key: "repos", type: "string", label: { en: "Repositories" }, list: true },
      ]),
    ];
    state.values = { connected: true };
    state.rows = [{ repos: "web" }, { repos: "api" }];
    renderWithProviders(<PluginSummaryCards />);
    expect(screen.getByText("Yes")).toBeInTheDocument();
    expect(screen.getByText("web, api")).toBeInTheDocument();
  });

  it("says a plug-in that does not answer is unavailable", () => {
    state.values = undefined;
    state.error = true;
    renderWithProviders(<PluginSummaryCards />);
    expect(screen.getByText("Meter")).toBeInTheDocument();
    expect(screen.getByText("Unavailable right now")).toBeInTheDocument();
  });

  it("asks nothing when no plug-in says where the community stands", () => {
    state.summaries = [];
    renderWithProviders(<PluginSummaryCards />);
    expect(state.asked).toEqual([]);
  });
});
