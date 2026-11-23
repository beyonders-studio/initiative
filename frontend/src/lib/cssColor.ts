/**
 * A CSS custom property as a colour a WebGL renderer can be handed.
 *
 * The theme states its colours in `oklch()`, which is the right thing for CSS
 * and no use at all to sigma: it reads `#rgb`, `rgb()` and `rgba()`, and
 * anything else comes out black rather than as an error.
 *
 * Converting is not a matter of asking the canvas to restate it — a browser
 * that understands `oklch()` hands `fillStyle` straight back, still in
 * `oklch()`, because it keeps the colour space rather than flattening it. So the
 * colour is actually *painted* and the pixel read back, which is the one way to
 * get sRGB out of a browser whatever went in.
 *
 * Doing it at all means a themed picture follows the theme — including an accent
 * somebody set for their own community — instead of a second set of colours
 * hard-coded beside the first and drifting from it.
 */

let probe: CanvasRenderingContext2D | null | undefined;

const canvas = () => {
  if (probe === undefined) {
    const element = document.createElement("canvas");
    element.width = 1;
    element.height = 1;
    probe = element.getContext("2d", { willReadFrequently: true });
  }
  return probe;
};

/** The forms sigma reads as they stand. */
const DIRECT = /^(#[0-9a-f]{3,8}|rgba?\([^)]*\))$/i;

/** Paint one pixel of a colour and say what came out, or null. */
const paint = (colour: string): [number, number, number, number] | null => {
  const context = canvas();
  if (!context) return null;
  // Cleared, and the fill set to transparent, so a colour the browser rejects
  // (which leaves `fillStyle` as it was) paints nothing rather than black.
  context.clearRect(0, 0, 1, 1);
  context.fillStyle = "rgba(0, 0, 0, 0)";
  context.fillStyle = colour;
  context.fillRect(0, 0, 1, 1);
  try {
    const [r, g, b, a] = context.getImageData(0, 0, 1, 1).data;
    return [r, g, b, a];
  } catch {
    // A canvas that will not be read from — jsdom's stub, a tainted one.
    return null;
  }
};

/**
 * Any CSS colour as `#rrggbb` / `rgba(…)`, or null if the browser cannot read
 * it. Null rather than a guess: a wrong colour is harder to spot than none.
 */
export const normalizeColor = (value: string): string | null => {
  const wanted = value.trim();
  if (!wanted) return null;
  // Already something a renderer takes. Worth checking first: it is most of
  // what is passed, it saves painting anything, and it means this still works
  // somewhere without a canvas at all.
  if (DIRECT.test(wanted)) return wanted;

  const painted = paint(wanted);
  if (!painted) return null;
  const [r, g, b, a] = painted;
  // Nothing was drawn, so the browser did not understand the colour. A real
  // fully transparent colour is not something worth drawing either.
  if (a === 0) return null;
  return a === 255
    ? `#${[r, g, b].map((channel) => channel.toString(16).padStart(2, "0")).join("")}`
    : `rgba(${r}, ${g}, ${b}, ${(a / 255).toFixed(3)})`;
};

/**
 * The colour a CSS custom property currently resolves to, on the document root.
 *
 * Read at the moment it is asked for rather than cached: the value changes when
 * the theme does, and a picture drawn in last theme's colours is worse than one
 * that costs a few reads.
 */
export const themeColor = (variable: string, fallback: string): string => {
  if (typeof document === "undefined") return fallback;
  const raw = getComputedStyle(document.documentElement).getPropertyValue(variable);
  return normalizeColor(raw) ?? normalizeColor(fallback) ?? fallback;
};

/** The same colour, said more quietly. */
export const withAlpha = (colour: string, alpha: number): string => {
  const normalized = normalizeColor(colour);
  if (!normalized) return colour;
  if (normalized.startsWith("rgba")) {
    return normalized.replace(/[\d.]+\)$/, `${alpha})`);
  }
  if (normalized.startsWith("rgb")) {
    return normalized.replace("rgb(", "rgba(").replace(")", `, ${alpha})`);
  }
  const hex = normalized.replace(/^#([0-9a-f])([0-9a-f])([0-9a-f])$/i, "#$1$1$2$2$3$3");
  if (/^#[0-9a-f]{6}$/i.test(hex)) {
    const byte = Math.round(Math.max(0, Math.min(1, alpha)) * 255)
      .toString(16)
      .padStart(2, "0");
    return `${hex}${byte}`;
  }
  return normalized;
};
