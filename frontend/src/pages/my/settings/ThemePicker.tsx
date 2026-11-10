import { useId, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  getThemeList,
  resolveThemeChoice,
  type ThemeColors,
  type ThemeDefinition,
  type ThemeVariant,
  themeChoiceId,
  variantPalettes,
} from "@/lib/themes";
import { cn } from "@/ui/lib/utils";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/ui/tooltip";

const c = (value: string): string => `oklch(${value})`;

/**
 * A border in polished metal, as the metallic finish draws one (styles.css):
 * the fill on the padding box over a sheen on the border box, which shows only
 * through the transparent border.
 */
const sheenBorder = (colors: ThemeColors, fill: string) => ({
  borderColor: "transparent",
  background: `linear-gradient(${c(fill)}, ${c(fill)}) padding-box, linear-gradient(135deg, ${c(
    colors.ring
  )} 0%, ${c(colors.border)} 35%, color-mix(in oklch, ${c(colors.ring)} 50%, white) 50%, ${c(
    colors.border
  )} 65%, ${c(colors.ring)} 100%) border-box`,
});

/** A theme's palette in miniature: a sidebar, a card and the chart colors. */
function MiniMockup({ colors, metallic }: { colors: ThemeColors; metallic?: boolean }) {
  return (
    <div
      className="flex overflow-hidden rounded-lg border"
      style={{
        height: 88,
        ...(metallic
          ? sheenBorder(colors, colors.background)
          : { borderColor: c(colors.border), backgroundColor: c(colors.background) }),
      }}
    >
      {/* Sidebar strip */}
      <div
        className="flex flex-col gap-1.5 p-1.5"
        style={{
          width: 28,
          backgroundColor: c(colors.sidebar),
          // The sheen the finish lays across the sidebar (styles.css).
          backgroundImage: metallic
            ? `linear-gradient(135deg, oklch(1 0 0 / 22%) 0%, transparent 30%, ${c(
                `${colors.ring} / 18%`
              )} 55%, oklch(1 0 0 / 10%) 68%, transparent 85%)`
            : undefined,
        }}
      >
        <div
          className="rounded"
          style={{ height: 6, width: "100%", backgroundColor: c(colors.sidebarPrimary) }}
        />
        <div
          className="rounded"
          style={{ height: 6, width: "100%", backgroundColor: c(colors.muted) }}
        />
        <div
          className="rounded"
          style={{ height: 6, width: "100%", backgroundColor: c(colors.muted) }}
        />
      </div>

      {/* Main area */}
      <div className="flex flex-1 flex-col gap-2 p-2">
        {/* Mini card */}
        <div
          className={cn("flex flex-col gap-1.5 rounded p-2", metallic && "border")}
          style={metallic ? sheenBorder(colors, colors.card) : { backgroundColor: c(colors.card) }}
        >
          <div
            className="rounded"
            style={{
              height: 6,
              width: "80%",
              backgroundColor: c(colors.foreground),
              opacity: 0.8,
            }}
          />
          <div
            className="rounded"
            style={{
              height: 4,
              width: "50%",
              backgroundColor: c(colors.mutedForeground),
              opacity: 0.6,
            }}
          />
          <div className="mt-1 flex gap-1">
            <div
              className="rounded"
              style={{ height: 8, width: 24, backgroundColor: c(colors.ring) }}
            />
            <div
              className="rounded"
              style={{ height: 8, width: 24, backgroundColor: c(colors.border) }}
            />
          </div>
        </div>

        {/* Chart color swatches */}
        <div className="flex gap-0.5">
          {[colors.chart1, colors.chart2, colors.chart3, colors.chart4, colors.chart5].map(
            (color) => (
              <div
                key={color}
                className="flex-1 rounded-sm"
                style={{ height: 6, backgroundColor: c(color) }}
              />
            )
          )}
        </div>
      </div>
    </div>
  );
}

/** A variant as an orb: its accent catching the light over its page color. */
const orb = (colors: ThemeColors, swatch?: string) =>
  swatch
    ? // A swatch of its own is a deep color: lit at the top, falling to near black.
      `radial-gradient(circle at 32% 28%, oklch(1 0 0 / 55%) 0%, ${c(swatch)} 38% 70%, oklch(0.12 0 0) 100%)`
    : `radial-gradient(circle at 32% 28%, oklch(1 0 0 / 85%) 0%, ${c(colors.ring)} 38%, ${c(
        colors.background
      )} 100%)`;

/** A variant's name: a proper name as written, otherwise from the locale. */
function useVariantName() {
  const { t } = useTranslation("settings");
  return (theme: ThemeDefinition, variant: ThemeVariant | undefined) =>
    variant
      ? (variant.name ?? t(`interface.themeVariants.${theme.id}.${variant.id}` as never))
      : undefined;
}

interface ThemeTileProps {
  theme: ThemeDefinition;
  /** The stored choice, which may be another theme's. */
  value: string;
  onChange: (choiceId: string) => void;
  disabled?: boolean;
}

/**
 * One theme as a tile: its light and dark palettes side by side, and for a
 * theme with variants a row of orbs to choose one. Pointing at an orb shows its
 * palette in the tile before it is chosen.
 */
function ThemeTile({ theme, value, onChange, disabled }: ThemeTileProps) {
  const { t } = useTranslation("settings");
  const variantName = useVariantName();
  const descriptionId = useId();
  const choice = resolveThemeChoice(value);
  const selected = choice.theme.id === theme.id;
  const chosen = selected ? choice.variant : theme.variants?.[0];
  const [previewId, setPreviewId] = useState<string | null>(null);
  const shown = theme.variants?.find((variant) => variant.id === previewId) ?? chosen;
  const { light, dark } = variantPalettes(theme, shown);
  const metallic = theme.finish === "metallic";
  const scope = theme.variantScope ?? "dark";
  const shownName = variantName(theme, shown);

  const variants = theme.variants && (
    <div
      role="radiogroup"
      aria-label={t("interface.themeVariantGroup", { theme: theme.name })}
      className="relative z-10 flex flex-wrap items-center gap-1"
    >
      {theme.variants.map((variant) => {
        const name = variantName(theme, variant) ?? variant.id;
        const label =
          scope === "dark"
            ? t("interface.useVariantForDark", { variant: name })
            : t("interface.useVariant", { variant: name });
        const checked = selected && chosen?.id === variant.id;
        return (
          <Tooltip key={variant.id}>
            <TooltipTrigger asChild>
              {/* biome-ignore lint/a11y/useSemanticElements: an orb showing the palette, not a bare radio input */}
              <button
                type="button"
                role="radio"
                aria-checked={checked}
                aria-label={label}
                disabled={disabled}
                onClick={() => onChange(themeChoiceId(theme, variant.id))}
                onPointerEnter={() => setPreviewId(variant.id)}
                onPointerLeave={() => setPreviewId(null)}
                onFocus={() => setPreviewId(variant.id)}
                onBlur={() => setPreviewId(null)}
                className="grid size-6 place-items-center rounded-full outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60"
              >
                <span
                  aria-hidden
                  className={cn(
                    "size-5 rounded-full shadow-sm ring-1 ring-black/15 transition-transform",
                    checked && "ring-2 ring-primary ring-offset-1 ring-offset-background",
                    previewId === variant.id && "scale-110"
                  )}
                  style={{
                    backgroundImage: orb(
                      variantPalettes(theme, variant)[scope === "dark" ? "dark" : "light"],
                      variant.swatch
                    ),
                  }}
                />
              </button>
            </TooltipTrigger>
            <TooltipContent>{label}</TooltipContent>
          </Tooltip>
        );
      })}
    </div>
  );

  return (
    <div
      className={cn(
        "relative space-y-2 rounded-lg border p-2 transition-colors hover:bg-accent/50 has-[[data-theme-tile]:focus-visible]:ring-2 has-[[data-theme-tile]:focus-visible]:ring-ring",
        selected && "border-primary ring-2 ring-primary"
      )}
    >
      {/* biome-ignore lint/a11y/useSemanticElements: a tile of previews, not a bare radio input */}
      <button
        type="button"
        role="radio"
        data-theme-tile
        aria-checked={selected}
        aria-label={theme.name}
        aria-describedby={descriptionId}
        disabled={disabled}
        onClick={() => onChange(themeChoiceId(theme, chosen?.id))}
        className="absolute inset-0 rounded-lg outline-none disabled:cursor-not-allowed"
      />
      <div className="pointer-events-none grid grid-cols-2 gap-1.5">
        <MiniMockup colors={light} metallic={metallic} />
        <MiniMockup colors={dark} metallic={metallic} />
      </div>
      {(theme.lightName || theme.variants) && (
        <div className="grid grid-cols-2 items-center gap-1.5 text-muted-foreground text-xs">
          {scope === "both" ? (
            <div className="col-span-2 flex flex-wrap items-center justify-between gap-1">
              {variants}
              <span className="pointer-events-none px-1">{shownName}</span>
            </div>
          ) : (
            <>
              <span className="pointer-events-none self-start px-1">{theme.lightName}</span>
              {/* The name on a line of its own: pointing at an orb renames it,
                  and the orbs must not move under the pointer. */}
              <div className="flex flex-col items-start gap-0.5">
                <span className="pointer-events-none px-1">{shownName}</span>
                {variants}
              </div>
            </>
          )}
        </div>
      )}
      <div className="pointer-events-none px-1 pb-1">
        <p className="font-medium text-sm">{theme.name}</p>
        <p id={descriptionId} className="text-muted-foreground text-xs">
          {t(`interface.themeDescriptions.${theme.id}` as never)}
        </p>
      </div>
    </div>
  );
}

/**
 * Every theme as a tile showing it in light and dark; the chosen one is ringed.
 * `value` is the stored choice, `<theme>` or `<theme>.<variant>`.
 */
export function ThemePicker({
  value,
  onChange,
  disabled,
}: {
  value: string;
  onChange: (choiceId: string) => void;
  disabled?: boolean;
}) {
  const { t } = useTranslation("settings");
  return (
    <TooltipProvider delayDuration={300}>
      <div
        role="radiogroup"
        aria-label={t("interface.colorTheme")}
        className="grid grid-cols-fill-56/3 gap-3"
      >
        {getThemeList().map((theme) => (
          <ThemeTile
            key={theme.id}
            theme={theme}
            value={value}
            onChange={onChange}
            disabled={disabled}
          />
        ))}
      </div>
    </TooltipProvider>
  );
}
