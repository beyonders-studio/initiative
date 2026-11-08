import { screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { buildProject, resetFactories } from "@/__tests__/factories";
import { renderWithProviders } from "@/__tests__/helpers/render";
import { ProjectDetailsFields } from "@/pages/community/tools/projects/settings/ProjectDetailsFields";

const INVERTED = "The end date can't be before the start date.";

describe("ProjectDetailsFields", () => {
  beforeEach(() => {
    resetFactories();
  });

  it("calls out an inverted range", () => {
    renderWithProviders(
      <ProjectDetailsFields
        project={buildProject({ start_date: "2026-09-30", end_date: "2026-03-02" })}
      />
    );

    expect(screen.getByText(INVERTED)).toBeInTheDocument();
  });

  it("says nothing for an ordered range", () => {
    renderWithProviders(
      <ProjectDetailsFields
        project={buildProject({ start_date: "2026-03-02", end_date: "2026-09-30" })}
      />
    );

    expect(screen.queryByText(INVERTED)).not.toBeInTheDocument();
  });
});
