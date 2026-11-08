import { cn } from "../ui/lib/utils";

export const INITIATIVE_COLOR_FALLBACK = "#94a3b8";
const HEX_COLOR_REGEX = /^#(?:[0-9a-fA-F]{3}){1,2}$/i;

export const resolveInitiativeColor = (color?: string | null): string => {
  if (color && HEX_COLOR_REGEX.test(color)) {
    return color;
  }
  return INITIATIVE_COLOR_FALLBACK;
};

export const hexToRgba = (hex: string, alpha: number): string => {
  const sanitized = hex.replace("#", "");
  const expanded =
    sanitized.length === 3
      ? sanitized
          .split("")
          .map((char) => char + char)
          .join("")
      : sanitized.padEnd(6, "0");
  const r = parseInt(expanded.slice(0, 2), 16);
  const g = parseInt(expanded.slice(2, 4), 16);
  const b = parseInt(expanded.slice(4, 6), 16);

  if ([r, g, b].some((value) => Number.isNaN(value))) {
    return hexToRgba(INITIATIVE_COLOR_FALLBACK, alpha);
  }

  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
};

export const InitiativeColorDot = ({
  color,
  className,
}: {
  color?: string | null;
  className?: string;
}) => (
  <span
    className={cn("inline-block h-2.5 w-2.5 rounded-full", className)}
    style={{ backgroundColor: resolveInitiativeColor(color) }}
    aria-hidden="true"
  />
);
