/** Text that stays legible on a coloured background. */

/**
 * Return a foreground text color (near-black or white) that has good contrast
 * against the given background. Uses YIQ luminance — fast, no library, gives
 * the same answer humans pick for most palette colors.
 *
 * Accepts hex strings: ``#RGB``, ``#RRGGBB``, ``#RRGGBBAA`` (alpha ignored).
 * Returns ``undefined`` for unparseable input so the caller can fall back.
 */
export const getContrastingTextColor = (
  background: string | null | undefined
): "#0F172A" | "#FFFFFF" | undefined => {
  if (!background) return undefined;
  let hex = background.startsWith("#") ? background.slice(1) : background;
  if (hex.length === 3) {
    hex = hex
      .split("")
      .map((c) => c + c)
      .join("");
  }
  if (hex.length !== 6 && hex.length !== 8) return undefined;

  const r = Number.parseInt(hex.slice(0, 2), 16);
  const g = Number.parseInt(hex.slice(2, 4), 16);
  const b = Number.parseInt(hex.slice(4, 6), 16);
  if ([r, g, b].some((n) => Number.isNaN(n))) return undefined;

  // YIQ luminance — values >= ~128 are "light".
  const yiq = (r * 299 + g * 587 + b * 114) / 1000;
  return yiq >= 140 ? "#0F172A" : "#FFFFFF";
};
