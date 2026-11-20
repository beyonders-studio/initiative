import type { RobotToastOptions } from "robot-toast";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { MascotToastType } from "./mascotToast";
import { computeAutoClose, toast } from "./mascotToast";

/** robot-toast stand-in: what is open, and each toast's close hook to run later. */
const robot = vi.hoisted(() => ({
  open: new Map<number, RobotToastOptions>(),
  closing: [] as Array<() => void>,
  next: 0,
}));

vi.mock("robot-toast", () => {
  const show = (input: RobotToastOptions) => {
    robot.next += 1;
    robot.open.set(robot.next, input);
    return robot.next;
  };
  // Like robot-toast, the close hook runs after the exit animation, not at once.
  const closeById = (id: number) => {
    const input = robot.open.get(id);
    robot.open.delete(id);
    if (input?.onClose) robot.closing.push(input.onClose);
  };
  const closeAll = () => {
    for (const id of [...robot.open.keys()]) closeById(id);
  };
  return { toast: Object.assign(show, { closeById, closeAll }) };
});

const finishClosing = () => {
  for (const onClose of robot.closing.splice(0)) onClose();
};
const openMessages = () => [...robot.open.values()].map((input) => input.message);

const TYPE_SPEED = 20;

/** What the reader actually experiences: the typing animation plus the dwell after it. */
const totalOnScreen = (message: string, type: MascotToastType, hasAction = false) =>
  message.length * TYPE_SPEED + computeAutoClose(message, type, TYPE_SPEED, hasAction);

describe("computeAutoClose", () => {
  it("holds a short toast for the per-type floor", () => {
    expect(totalOnScreen("Saved", "success")).toBe(3_000);
  });

  it("scales with message length", () => {
    expect(totalOnScreen("Task created".repeat(8), "default")).toBeGreaterThan(
      totalOnScreen("Task created", "default")
    );
  });

  it("gives warnings and errors a longer floor than neutral toasts", () => {
    expect(totalOnScreen("Nope", "warning")).toBeGreaterThan(totalOnScreen("Nope", "info"));
    expect(totalOnScreen("Nope", "error")).toBeGreaterThan(totalOnScreen("Nope", "warning"));
  });

  it("adds time when the toast has an action to click", () => {
    const message = "Project archived. It can be restored from the trash at any time.";
    expect(totalOnScreen(message, "success", true)).toBe(totalOnScreen(message, "success") + 2_000);
  });

  it("caps the reading budget so a long message does not camp on screen", () => {
    // With no typing animation the dwell is the whole budget, which is clamped.
    expect(computeAutoClose("x".repeat(400), "default", 0, false)).toBe(10_000);
  });

  it("always leaves a dwell after typing finishes", () => {
    // Typing alone (600 chars × 20ms) already outruns the budget.
    expect(computeAutoClose("x".repeat(600), "default", TYPE_SPEED, false)).toBe(1_200);
  });

  it("is shorter than the old fixed 5s dwell for a typical toast", () => {
    expect(computeAutoClose("Task created", "success", TYPE_SPEED, false)).toBeLessThan(5_000);
  });
});

describe("toast", () => {
  beforeEach(() => {
    toast.dismiss();
    finishClosing();
  });

  it("replaces the toast showing under the same id", () => {
    toast.warning("Offline", { id: "offline" });
    toast.warning("Offline, still", { id: "offline" });
    expect(openMessages()).toEqual(["Offline, still"]);
  });

  it("still dismisses by id after the replaced toast finishes closing", () => {
    // An effect that shows, is cleaned up, and shows again (StrictMode does this).
    toast.warning("Offline", { id: "offline" });
    toast.dismiss("offline");
    toast.warning("Offline", { id: "offline" });
    finishClosing();
    toast.dismiss("offline");
    expect(openMessages()).toEqual([]);
  });

  it("shows the same text of the same type once", () => {
    toast.error("Could not save");
    toast.error("Could not save");
    expect(openMessages()).toEqual(["Could not save"]);
  });

  it("shows each toast that carries its own button, though the text matches", () => {
    const onClick = () => {};
    toast.success("Moved to Done", { action: { label: "Undo", onClick } });
    toast.success("Moved to Done", { action: { label: "Undo", onClick } });
    expect(openMessages()).toEqual(["Moved to Done", "Moved to Done"]);
  });

  it("drops a waiting toast that is dismissed before its turn", () => {
    toast.info("One", { id: "one" });
    toast.info("Two");
    toast.warning("Three", { id: "three" });
    toast.dismiss("three");
    toast.dismiss("one");
    finishClosing();
    expect(openMessages()).toEqual(["Two"]);
  });
});
