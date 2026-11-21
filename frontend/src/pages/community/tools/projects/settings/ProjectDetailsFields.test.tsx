import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { buildProject } from "@/__tests__/factories";
import { renderWithProviders } from "@/__tests__/helpers/render";

import { ProjectDetailsFields } from "./ProjectDetailsFields";

const INVERTED = "The end date can't be before the start date.";

describe("ProjectDetailsFields", () => {
  it.each([
    ["2026-09-30", "2026-03-02", true],
    ["2026-03-02", "2026-09-30", false],
  ])("from %s to %s calls out an inverted range: %s", (start_date, end_date, inverted) => {
    renderWithProviders(<ProjectDetailsFields project={buildProject({ start_date, end_date })} />);

    expect(screen.queryByText(INVERTED) !== null).toBe(inverted);
  });
});
