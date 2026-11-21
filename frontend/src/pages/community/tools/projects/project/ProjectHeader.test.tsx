import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { buildProject } from "@/__tests__/factories";
import { renderPage } from "@/__tests__/helpers/render";

import { ProjectHeader } from "./ProjectHeader";

const renderHeader = (overrides: Parameters<typeof buildProject>[0]) =>
  renderPage(() => <ProjectHeader project={buildProject(overrides)} projectIsArchived={false} />);

describe("ProjectHeader", () => {
  it.each([
    [{ start_date: "2026-03-02", end_date: "2026-09-30" }, "Mar 2, 2026 – Sep 30, 2026"],
    // A bare YYYY-MM-DD parsed as UTC would render Mar 1 west of Greenwich.
    [{ start_date: "2026-03-02" }, "Starts Mar 2, 2026"],
    [{ end_date: "2026-09-30" }, "Ends Sep 30, 2026"],
    [{}, "None"],
  ])("shows the dates %o as %s, each a calendar day", async (dates, text) => {
    renderHeader(dates);

    expect(await screen.findByText(text)).toBeInTheDocument();
  });

  it("reads a template's status as Template, among the choices an editor has", async () => {
    renderHeader({ is_template: true });

    expect(await screen.findByRole("combobox", { name: "Status" })).toHaveTextContent("Template");
  });
});
