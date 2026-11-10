/**
 * OKLch, the space the color themes are written in, to and from sRGB.
 *
 * A theme token is a bare triplet, "lightness chroma hue", with an optional
 * "/ alpha" (`0.224 0.036 277`, `1 0 0 / 10%`), which the stylesheet wraps in
 * `oklch()`. These helpers write one from a hex value, so a published palette
 * can be copied in as it is published, and read one back to measure its
 * contrast.
 */

export interface Oklch {
  l: number;
  c: number;
  h: number;
}

const clampUnit = (value: number) => Math.max(0, Math.min(1, value));

const srgbToLinear = (channel: number) =>
  channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4;

const linearToSrgb = (channel: number) =>
  channel <= 0.0031308 ? channel * 12.92 : 1.055 * channel ** (1 / 2.4) - 0.055;

/** OKLch from `#rgb` or `#rrggbb`; a neutral grey for nothing. */
export const hexToOklch = (hex: string | undefined | null): Oklch => {
  if (!hex) return { l: 0.5, c: 0, h: 0 };
  let normalized = hex.replace("#", "");
  if (normalized.length === 3) {
    normalized = normalized
      .split("")
      .map((char) => `${char}${char}`)
      .join("");
  }

  const r = srgbToLinear(Number.parseInt(normalized.slice(0, 2), 16) / 255);
  const g = srgbToLinear(Number.parseInt(normalized.slice(2, 4), 16) / 255);
  const b = srgbToLinear(Number.parseInt(normalized.slice(4, 6), 16) / 255);

  const l = Math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b);
  const m = Math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b);
  const s = Math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b);

  const okL = 0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s;
  const okA = 1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s;
  const okB = 0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s;

  let hue = (Math.atan2(okB, okA) * 180) / Math.PI;
  if (hue < 0) hue += 360;
  return { l: clampUnit(okL), c: Math.max(0, Math.sqrt(okA * okA + okB * okB)), h: hue };
};

/** The bare triplet a theme token holds. */
export const oklchToString = ({ l, c, h }: Oklch) =>
  `${l.toFixed(3)} ${c.toFixed(3)} ${h.toFixed(2)}`;

/** A theme token from a hex value: `hex("#24273a")` → `"0.272 0.035 279.86"`. */
export const hex = (value: string) => oklchToString(hexToOklch(value));

/** A theme token's color and alpha; alpha is 1 when the token names none. */
export const parseOklch = (token: string): Oklch & { alpha: number } => {
  const [color, alphaPart] = token.split("/").map((part) => part.trim());
  const [l, c, h] = color.split(/\s+/).map(Number);
  let alpha = 1;
  if (alphaPart) {
    alpha = alphaPart.endsWith("%")
      ? Number.parseFloat(alphaPart) / 100
      : Number.parseFloat(alphaPart);
  }
  return { l, c, h: Number.isNaN(h) ? 0 : h, alpha };
};

/** Linear sRGB, each channel clipped to the gamut a screen shows. */
const oklchToLinearSrgb = ({ l, c, h }: Oklch): [number, number, number] => {
  const radians = (h * Math.PI) / 180;
  const a = c * Math.cos(radians);
  const b = c * Math.sin(radians);
  const l_ = (l + 0.3963377774 * a + 0.2158037573 * b) ** 3;
  const m_ = (l - 0.1055613458 * a - 0.0638541728 * b) ** 3;
  const s_ = (l - 0.0894841775 * a - 1.291485548 * b) ** 3;
  return [
    4.0767416621 * l_ - 3.3077115913 * m_ + 0.2309699292 * s_,
    -1.2684380046 * l_ + 2.6097574011 * m_ - 0.3413193965 * s_,
    -0.0041960863 * l_ - 0.7034186147 * m_ + 1.707614701 * s_,
  ].map(clampUnit) as [number, number, number];
};

/** The sRGB a token shows, `[0..1]` per channel, composited over `under` when translucent. */
const shownSrgb = (token: string, under?: string): [number, number, number] => {
  const { alpha, ...color } = parseOklch(token);
  const top = oklchToLinearSrgb(color).map(linearToSrgb) as [number, number, number];
  if (alpha >= 1 || !under) return top;
  const bottom = shownSrgb(under);
  return top.map((channel, i) => channel * alpha + bottom[i] * (1 - alpha)) as [
    number,
    number,
    number,
  ];
};

/** WCAG relative luminance of an sRGB color. */
const luminance = (rgb: [number, number, number]) => {
  const [r, g, b] = rgb.map(srgbToLinear);
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
};

/**
 * The WCAG contrast ratio of a text token on a background token, 1 to 21. A
 * translucent background is laid over `base` (the page) first.
 */
export const contrastRatio = (text: string, background: string, base?: string): number => {
  const behind = shownSrgb(background, base);
  const front = shownSrgb(text);
  const [lighter, darker] = [luminance(front), luminance(behind)].sort((a, b) => b - a);
  return (lighter + 0.05) / (darker + 0.05);
};
