/**
 * A colour for a new counter, picked from the app's palette: desaturated
 * mid-tones (not the vivid Tailwind-500 set) so a grid full of counters reads
 * as calm rather than neon, and ~30 hues spanning the wheel keep randomly
 * assigned colours visually distinct.
 */

import records from "@/api/generated/tools.json";

export const pickRandomCounterColor = (): string =>
  records.colors[Math.floor(Math.random() * records.colors.length)] ?? records.colors[0]!;
