// Single source of truth for the "task completion feedback" preferences on
// the frontend (visual + audio + haptic). Mirror of the allowed visual values
// in backend/app/api/v1/endpoints/users.py.

import { Capacitor } from "@capacitor/core";

import popSoundUrl from "@/assets/pop.wav";

export const TASK_COMPLETION_VISUAL_FEEDBACK_VALUES = [
  "none",
  "confetti",
  "heart",
  "d20",
  "gold_coin",
  "random",
] as const;

export type TaskCompletionVisualFeedback = (typeof TASK_COMPLETION_VISUAL_FEEDBACK_VALUES)[number];

// Pool the `random` option draws from. Excludes `none` (defeats the point)
// and `random` itself (would loop).
export const RANDOMIZABLE_EFFECTS = ["confetti", "heart", "d20", "gold_coin"] as const;

export type ResolvedEffect = (typeof RANDOMIZABLE_EFFECTS)[number];

const VALID_VALUES = new Set<string>(TASK_COMPLETION_VISUAL_FEEDBACK_VALUES);

export const parseTaskCompletionVisualFeedback = (
  raw: string | null | undefined
): TaskCompletionVisualFeedback => {
  if (raw && VALID_VALUES.has(raw)) {
    return raw as TaskCompletionVisualFeedback;
  }
  return "none";
};

// Map a stored preference to the actual effect that should fire right now.
// `none` → null (caller should skip), `random` → uniformly random element of
// the pool, anything else → echo input.
export const resolveEffect = (value: TaskCompletionVisualFeedback): ResolvedEffect | null => {
  if (value === "none") return null;
  if (value === "random") {
    const idx = Math.floor(Math.random() * RANDOMIZABLE_EFFECTS.length);
    return RANDOMIZABLE_EFFECTS[idx];
  }
  return value;
};

// Custom event channel — matches the AUTH_UNAUTHORIZED_EVENT pattern in
// src/api/client.ts. Carries the resolved effect (already random-resolved)
// in `event.detail.effect`.
export const TASK_COMPLETION_EVENT = "initiative:task-completion-feedback";

export interface TaskCompletionEventDetail {
  effect: ResolvedEffect;
}

export const dispatchTaskCompletionVisualFeedback = (value: TaskCompletionVisualFeedback): void => {
  if (typeof window === "undefined") return;
  const effect = resolveEffect(value);
  if (!effect) return;
  window.dispatchEvent(
    new CustomEvent<TaskCompletionEventDetail>(TASK_COMPLETION_EVENT, {
      detail: { effect },
    })
  );
};

// ── Audio ──────────────────────────────────────────────────────────────────

// Lazily-constructed Audio element so back-to-back fires don't churn DOM
// elements. `currentTime = 0` rewinds for re-play.
let popAudio: HTMLAudioElement | null = null;

export const playTaskCompletionSound = (): void => {
  if (typeof window === "undefined") return;
  if (!popAudio) {
    popAudio = new Audio(popSoundUrl);
    popAudio.volume = 0.8;
  }
  popAudio.currentTime = 0;
  void popAudio.play().catch(() => {
    // Autoplay policies can reject programmatic play in rare contexts and
    // some devices simply have no audio output. The pop is a nice-to-have;
    // silent failure is the right behavior.
  });
};

// ── Haptic ─────────────────────────────────────────────────────────────────

/**
 * Two-pulse "buzz buzz" haptic. On Capacitor (iOS + Android) we go through
 * the Haptics plugin so iOS WKWebView (which doesn't expose
 * `navigator.vibrate`) still works. On web we fall back to the Vibration
 * API, which works on Android Chrome and silently no-ops on iOS Safari.
 */
export const triggerTaskCompletionHaptic = (): void => {
  if (Capacitor.isNativePlatform()) {
    // Dynamic import keeps the plugin's web stub out of the synchronous
    // bundle — only loaded when actually needed on a native build.
    void import("@capacitor/haptics").then(({ Haptics, ImpactStyle }) => {
      void Haptics.impact({ style: ImpactStyle.Light });
      window.setTimeout(() => {
        void Haptics.impact({ style: ImpactStyle.Light });
      }, 100);
    });
    return;
  }
  if (typeof navigator !== "undefined" && typeof navigator.vibrate === "function") {
    navigator.vibrate([40, 60, 40]);
  }
};

// ── Unified dispatcher ─────────────────────────────────────────────────────

interface UserPrefsLike {
  task_completion_visual_feedback?: string | null;
  task_completion_audio_feedback?: boolean | null;
  task_completion_haptic_feedback?: boolean | null;
}

/**
 * Fan out to all three feedback modalities respecting the user's prefs.
 *
 * - Visual is the loud one — only fires when `opts.isAssigned`. Confetti /
 *   d20 popping for every closeout you do as a PM would feel like spam.
 * - Audio + haptic are subtle — fire for any completion the caller decided
 *   to celebrate (caller is responsible for the transition + initiator
 *   gating; this helper just dispatches).
 *
 * Both audio/haptic prefs check `!== false` so a missing/null field defaults
 * to enabled (matching the backend's `server_default="true"`).
 */
export const fireTaskCompletionFeedback = (
  prefs: UserPrefsLike,
  opts: { isAssigned: boolean }
): void => {
  if (opts.isAssigned) {
    const visual = parseTaskCompletionVisualFeedback(prefs.task_completion_visual_feedback);
    if (visual !== "none") dispatchTaskCompletionVisualFeedback(visual);
  }
  if (prefs.task_completion_audio_feedback !== false) playTaskCompletionSound();
  if (prefs.task_completion_haptic_feedback !== false) triggerTaskCompletionHaptic();
};

// Last user-pointer position (viewport pixels). Updated by the global listener
// installed inside <TaskCompletionEffectHost />. Falls back to viewport center
// when no pointer interaction has happened yet (e.g. status changed via a
// keyboard shortcut on first load).
let lastPointerX: number | null = null;
let lastPointerY: number | null = null;

export const recordPointer = (x: number, y: number): void => {
  lastPointerX = x;
  lastPointerY = y;
};

export const getLastPointer = (): { x: number; y: number } => {
  if (typeof window === "undefined") {
    return { x: 0, y: 0 };
  }
  if (lastPointerX === null || lastPointerY === null) {
    return { x: window.innerWidth / 2, y: window.innerHeight / 2 };
  }
  return { x: lastPointerX, y: lastPointerY };
};
