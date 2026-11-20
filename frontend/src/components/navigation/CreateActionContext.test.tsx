import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import {
  CreateActionProvider,
  type PrimaryCreateAction,
  usePrimaryCreateAction,
  useRegisterPrimaryCreateAction,
} from "./CreateActionContext";

function Consumer() {
  const { isCreateContext, action } = usePrimaryCreateAction();
  return (
    <>
      <span data-testid="ctx">{String(isCreateContext)}</span>
      <span data-testid="action">{action ? "yes" : "no"}</span>
      <span data-testid="label">{action?.label ?? ""}</span>
      <button type="button" data-testid="run" onClick={() => action?.run()}>
        run
      </button>
    </>
  );
}

function Registrant({ action }: { action: PrimaryCreateAction | null }) {
  useRegisterPrimaryCreateAction(action);
  return null;
}

function Tree({ mounted, action }: { mounted: boolean; action: PrimaryCreateAction | null }) {
  return (
    <CreateActionProvider>
      <Consumer />
      {mounted ? <Registrant action={action} /> : null}
    </CreateActionProvider>
  );
}

describe("CreateActionContext", () => {
  it("exposes a registered action and runs the latest handler (permitted route)", () => {
    const run = vi.fn();
    const { rerender } = render(<Tree mounted={true} action={{ run, label: "Add Task" }} />);

    expect(screen.getByTestId("ctx").textContent).toBe("true");
    expect(screen.getByTestId("action").textContent).toBe("yes");
    expect(screen.getByTestId("label").textContent).toBe("Add Task");

    fireEvent.click(screen.getByTestId("run"));
    expect(run).toHaveBeenCalledTimes(1);

    // A re-render with a fresh handler should run the new one, not the stale one.
    const nextRun = vi.fn();
    rerender(<Tree mounted={true} action={{ run: nextRun, label: "Add File" }} />);
    fireEvent.click(screen.getByTestId("run"));
    expect(nextRun).toHaveBeenCalledTimes(1);
    expect(run).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("label").textContent).toBe("Add File");
  });

  it("marks a create context with no action when unpermitted, and clears it on unmount", () => {
    const { rerender } = render(<Tree mounted={true} action={null} />);
    // isCreateContext is true so the nav knows to hide the add button rather
    // than fall back to the global create menu.
    expect(screen.getByTestId("ctx").textContent).toBe("true");
    expect(screen.getByTestId("action").textContent).toBe("no");

    rerender(<Tree mounted={false} action={null} />);
    expect(screen.getByTestId("ctx").textContent).toBe("false");
    expect(screen.getByTestId("action").textContent).toBe("no");
  });
});
