import { screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { buildProject, resetFactories } from "@/__tests__/factories";
import { renderPage } from "@/__tests__/helpers/render";
import { ProjectHeader } from "@/pages/community/tools/projects/project/ProjectHeader";

const renderHeader = (overrides: Parameters<typeof buildProject>[0]) =>
  renderPage(() => <ProjectHeader project={buildProject(overrides)} projectIsArchived={false} />);

describe("ProjectHeader", () => {
  beforeEach(() => {
    resetFactories();
  });

  it("shows both dates when the project has a start and an end", async () => {
    renderHeader({ start_date: "2026-03-02", end_date: "2026-09-30" });

    expect(await screen.findByText("Mar 2, 2026 – Sep 30, 2026")).toBeInTheDocument();
  });

  it("renders a date-only value as that calendar day, not the day before", async () => {
    // A bare YYYY-MM-DD parsed as UTC would render Mar 1 west of Greenwich.
    renderHeader({ start_date: "2026-03-02" });

    expect(await screen.findByText("Starts Mar 2, 2026")).toBeInTheDocument();
  });

  it("shows only the end when that is all the project has", async () => {
    renderHeader({ end_date: "2026-09-30" });

    expect(await screen.findByText("Ends Sep 30, 2026")).toBeInTheDocument();
  });

  it("says None when neither date is set", async () => {
    renderHeader({});

    expect(await screen.findByText("None")).toBeInTheDocument();
  });

  it("reads a template's status as Template, among the choices an editor has", async () => {
    renderHeader({ is_template: true });

    expect(await screen.findByRole("combobox", { name: "Status" })).toHaveTextContent("Template");
  });
});
