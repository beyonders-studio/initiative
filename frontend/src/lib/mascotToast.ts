import { type RobotToastOptions, toast as robotToast } from "robot-toast";

import excitedSvg from "@/assets/yonder/excited.svg";
import idleSvg from "@/assets/yonder/idle.svg";
import proudSvg from "@/assets/yonder/proud.svg";
import talkingSvg from "@/assets/yonder/talking.svg";
import thinkingSvg from "@/assets/yonder/thinking.svg";

type MascotToastType = "default" | "success" | "error" | "warning" | "info" | "loading";

type MascotToastPosition =
  | "top-left"
  | "top-center"
  | "top-right"
  | "bottom-left"
  | "bottom-center"
  | "bottom-right";

const VARIANT_BY_TYPE: Record<MascotToastType, string> = {
  default: idleSvg,
  success: proudSvg,
  error: excitedSvg,
  warning: thinkingSvg,
  info: talkingSvg,
  loading: talkingSvg,
};

interface MascotToastOptions {
  /** Dismissal handle; showing another toast under it replaces this one. */
  id?: string;
  /** ms to auto-dismiss; pass `Infinity` to keep open until dismissed. */
  duration?: number;
  /** Secondary line appended below the main message (Sonner parity). */
  description?: string;
  /** Override the auto-selected Yonder variant with any imported SVG URL. */
  robotVariant?: string;
  position?: MascotToastPosition;
  typeSpeed?: number;
  /** Sonner-style action; mapped to a single robot-toast button. */
  action?: { label: string; onClick: (e: MouseEvent) => void };
  /**
   * Fires when the toast closes for any reason (manual dismiss or auto-close).
   * Sonner's separate `onDismiss` / `onAutoClose` are not honored — robot-toast
   * exposes a single close hook with no way to distinguish the two.
   */
  onClose?: () => void;
}

type RobotToastType = "default" | "success" | "error" | "warning" | "info";

const ROBOT_TYPE_BY_TYPE: Record<MascotToastType, RobotToastType> = {
  default: "default",
  success: "success",
  error: "error",
  warning: "warning",
  info: "info",
  loading: "info",
};

/**
 * Auto-dismiss timing.
 *
 * robot-toast only starts its auto-close timer once the typewriter animation
 * finishes, so `autoClose` is the dwell time *after* the message is fully on
 * screen — not the total time it is visible. We budget a total reading time
 * from the content and hand robot-toast whatever is left once typing is done.
 *
 * The budget is a fixed cost for noticing the toast plus a per-character
 * reading allowance (50ms/char, roughly 240 wpm), clamped so short messages
 * still linger long enough to register and long ones don't camp on screen.
 */
const NOTICE_MS = 1_200;
const MS_PER_CHAR = 50;
const MAX_TOTAL_MS = 10_000;
/** Extra budget when the toast carries a button the reader may want to press. */
const ACTION_MS = 2_000;
/** Never leave less than this much time after the message finishes typing. */
const MIN_DWELL_MS = 1_200;
/** Floor on total on-screen time, per type — warnings and errors sit longer. */
const MIN_TOTAL_MS_BY_TYPE: Record<MascotToastType, number> = {
  default: 3_000,
  success: 3_000,
  info: 3_000,
  loading: 3_000,
  warning: 4_500,
  error: 5_000,
};

/** Dwell time (ms) to hand robot-toast for a message it will type at `typeSpeed`. */
const computeAutoClose = (
  message: string,
  type: MascotToastType,
  typeSpeed: number,
  hasAction: boolean
): number => {
  const budget = NOTICE_MS + message.length * MS_PER_CHAR + (hasAction ? ACTION_MS : 0);
  const total = Math.min(Math.max(budget, MIN_TOTAL_MS_BY_TYPE[type]), MAX_TOTAL_MS);
  const typingMs = message.length * typeSpeed;
  return Math.max(total - typingMs, MIN_DWELL_MS);
};

const buildInput = (
  message: string,
  type: MascotToastType,
  opts?: MascotToastOptions
): RobotToastOptions => {
  const text = opts?.description ? `${message}\n${opts.description}` : message;
  const typeSpeed = opts?.typeSpeed ?? 20;
  const input: RobotToastOptions = {
    message: text,
    type: ROBOT_TYPE_BY_TYPE[type],
    robotVariant: opts?.robotVariant ?? VARIANT_BY_TYPE[type],
    position: opts?.position ?? "bottom-center",
    typeSpeed,
  };
  if (opts?.duration !== undefined) {
    input.autoClose = Number.isFinite(opts.duration) ? opts.duration : false;
  } else {
    input.autoClose = computeAutoClose(text, type, typeSpeed, Boolean(opts?.action));
  }
  if (opts?.action) {
    input.buttons = [{ label: opts.action.label, onClick: opts.action.onClick }];
  }
  return input;
};

/** How many toasts are on screen at once; the rest wait their turn. */
const VISIBLE_LIMIT = 2;

/**
 * Every toast on screen or waiting, by key: the caller's `id`, or else its
 * type and text. A toast waiting has no `robotId` yet. The queue is kept here
 * rather than in robot-toast, whose queue cannot drop one waiting toast.
 */
const entries = new Map<string, { input: RobotToastOptions; robotId?: number }>();

const showWaiting = () => {
  let shown = [...entries.values()].filter((entry) => entry.robotId !== undefined).length;
  for (const entry of entries.values()) {
    if (shown >= VISIBLE_LIMIT) return;
    if (entry.robotId === undefined) {
      entry.robotId = robotToast(entry.input);
      shown += 1;
    }
  }
};

const close = (key: string) => {
  const entry = entries.get(key);
  if (!entry) return;
  entries.delete(key);
  if (entry.robotId !== undefined) robotToast.closeById(entry.robotId);
  showWaiting();
};

/**
 * Show a toast. A toast with an `id` replaces the one showing under that id
 * (Sonner's behaviour); one without is dropped while the same text of the
 * same type is already showing or waiting.
 */
const fire = (message: string, type: MascotToastType, opts?: MascotToastOptions): string => {
  const input = buildInput(message, type, opts);
  const key = opts?.id ?? `${type}:${input.message}`;
  if (entries.has(key)) {
    if (opts?.id === undefined) return key;
    close(key);
  }
  const entry: { input: RobotToastOptions; robotId?: number } = { input };
  input.onClose = () => {
    // A toast closes after its exit animation, by which time a newer toast
    // may hold its key; only its own entry is forgotten.
    if (entries.get(key) === entry) entries.delete(key);
    opts?.onClose?.();
    showWaiting();
  };
  entries.set(key, entry);
  showWaiting();
  return key;
};

interface PromiseMessages<T> {
  loading: string;
  success: string | ((value: T) => string);
  error: string | ((err: unknown) => string);
}

interface MascotToast {
  (message: string, options?: MascotToastOptions): void;
  success(message: string, options?: MascotToastOptions): void;
  error(message: string, options?: MascotToastOptions): void;
  warning(message: string, options?: MascotToastOptions): void;
  info(message: string, options?: MascotToastOptions): void;
  message(message: string, options?: MascotToastOptions): void;
  loading(message: string, options?: MascotToastOptions): void;
  dismiss(id?: string): void;
  promise<T>(
    promise: Promise<T>,
    msgs: PromiseMessages<T>,
    options?: MascotToastOptions
  ): Promise<T>;
}

const toast = ((message: string, options?: MascotToastOptions) => {
  fire(message, "default", options);
}) as MascotToast;

toast.success = (message, options) => fire(message, "success", options);
toast.error = (message, options) => fire(message, "error", options);
toast.warning = (message, options) => fire(message, "warning", options);
toast.info = (message, options) => fire(message, "info", options);
toast.message = (message, options) => fire(message, "default", options);
toast.loading = (message, options) =>
  fire(message, "loading", { ...options, duration: options?.duration ?? Infinity });

toast.dismiss = (id) => {
  if (id === undefined) {
    entries.clear();
    robotToast.closeAll();
    return;
  }
  close(id);
};

toast.promise = async <T>(
  promise: Promise<T>,
  msgs: PromiseMessages<T>,
  options?: MascotToastOptions
) => {
  const loadingId = fire(msgs.loading, "loading", { ...options, duration: Infinity });
  try {
    const value = await promise;
    close(loadingId);
    fire(
      typeof msgs.success === "function" ? msgs.success(value) : msgs.success,
      "success",
      options
    );
    return value;
  } catch (err) {
    close(loadingId);
    fire(typeof msgs.error === "function" ? msgs.error(err) : msgs.error, "error", options);
    throw err;
  }
};

export type { MascotToastOptions, MascotToastType };
export { computeAutoClose, toast };
