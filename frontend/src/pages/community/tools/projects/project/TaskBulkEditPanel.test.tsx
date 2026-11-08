import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { buildTask } from "@/__tests__/factories";
import { renderWithProviders } from "@/__tests__/helpers/render";

import { TaskBulkEditPanel } from "./TaskBulkEditPanel";

const handlers = {
  onEdit: vi.fn(),
  onEditTags: vi.fn(),
  onArchive: vi.fn(),
  onDelete: vi.fn(),
};

describe("TaskBulkEditPanel", () => {
  it("renders Export Selected ahead of the edit actions when a selector is given", () => {
    renderWithProviders(
      <TaskBulkEditPanel
        selectedTasks={[buildTask(), buildTask()]}
        exportParams={{
          conditions: [{ field: "id", op: "in_", value: [1, 2] }],
        }}
        {...handlers}
      />
    );
    const buttons = screen.getAllByRole("button");
    expect(buttons[0]).toHaveAccessibleName("Export Selected");
  });

  it("omits the export action without a selector", () => {
    renderWithProviders(<TaskBulkEditPanel selectedTasks={[buildTask()]} {...handlers} />);
    expect(screen.queryByRole("button", { name: /export/i })).not.toBeInTheDocument();
  });
});
