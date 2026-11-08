import { Check } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { OwnedDecoration } from "@/api/generated/initiativeAPI.schemas";
import { DecorationSwatch } from "@/components/user/DecorationSwatch";
import { currentYear, MIN_GRAD_YEAR, maxGradYear } from "@/lib/gradArtwork";
import {
  DEFAULT_TINTS,
  type Decoration,
  type DecorationKind,
  resolveDecoration,
} from "@/lib/profileDecorations";
import { Button } from "@/ui/button";
import { cn } from "@/ui/lib/utils";

/**
 * The decorations of one slot that this reader owns *and* this build can draw.
 *
 * Two filters, and the second one matters: a library is the server's answer and
 * may name a decoration from a pack whose artwork this build has never seen.
 * Offering a tile that renders as nothing would be worse than leaving it out.
 */
const wearable = (owned: OwnedDecoration[] | undefined, kind: DecorationKind): Decoration[] =>
  (owned ?? [])
    .filter((item) => item.kind === kind)
    .map((item) => resolveDecoration(item.id, kind))
    .filter((decoration): decoration is Decoration => Boolean(decoration));

interface TileProps {
  label: string;
  selected: boolean;
  onToggle: () => void;
  children: React.ReactNode;
  /** `radio` for a slot that holds one thing, `checkbox` for the trophy row. */
  control: "radio" | "checkbox";
  /** Groups the radios of one slot, so the browser treats them as alternatives. */
  name?: string;
  /** A tile past the cap, which stays visible and stops responding. */
  disabled?: boolean;
}

/** A checked input needs a change handler; this one is driven by its click. */
const NO_CHANGE = () => {};

/**
 * One decoration, as something to turn on.
 *
 * A real input rather than a button wearing a role: it arrives with the state,
 * the keyboard and the grouping already correct, and the artwork is the label.
 * The input is hidden from sight, not from the page.
 */
const Tile = ({ label, selected, onToggle, children, control, name, disabled }: TileProps) => (
  <label
    title={label}
    className={cn(
      "relative block rounded-md border-2 p-1.5 transition-colors",
      disabled ? "cursor-not-allowed opacity-50" : "cursor-pointer",
      selected
        ? "border-primary bg-primary/5"
        : "border-transparent hover:border-muted-foreground/30",
      "focus-within:ring-2 focus-within:ring-ring"
    )}
  >
    <input
      type={control}
      name={name}
      checked={selected}
      disabled={disabled}
      // The click, not the change: picking the one already on takes it off, and
      // a radio reports no change when it is clicked while checked.
      onClick={onToggle}
      onChange={NO_CHANGE}
      aria-label={label}
      className="sr-only"
    />
    {children}
    {selected ? (
      <Check className="absolute top-0.5 right-0.5 size-3.5 text-primary" aria-hidden="true" />
    ) : null}
  </label>
);

/**
 * The year on a decoration that carries one.
 *
 * A plain number field: the year is four digits and every platform already
 * knows how to type four digits. It arrives filled in with this one, because
 * that is the year almost everybody setting it means.
 */
const YearPicker = ({
  value,
  onChange,
}: {
  value: number | null;
  onChange: (year: number) => void;
}) => {
  const { t } = useTranslation("profiles");
  return (
    <label className="flex items-center gap-2 text-muted-foreground text-xs">
      {t("decorationPicker.year")}
      <input
        type="number"
        inputMode="numeric"
        min={MIN_GRAD_YEAR}
        max={maxGradYear()}
        value={value ?? currentYear()}
        onChange={(event) => onChange(Number(event.target.value))}
        className="w-24 rounded-md border border-input bg-transparent px-2 py-1 text-foreground text-sm"
      />
    </label>
  );
};

interface SlotPickerProps {
  kind: Extract<DecorationKind, "banner" | "frame">;
  value: string | null;
  onChange: (id: string | null) => void;
  owned: OwnedDecoration[] | undefined;
  /** The colours picked for a tintable frame, and how to change them. */
  tint?: string[];
  onTint?: (colours: string[]) => void;
  /** The year picked for a decoration that carries one, and how to change it. */
  year?: number | null;
  onYear?: (year: number) => void;
}

/**
 * The colour wells for a frame whose colours are the wearer's.
 *
 * A native colour input, because every platform already has a colour picker
 * its own users know, and none of them is worth rebuilding.
 */
const TintPicker = ({
  decoration,
  value,
  onChange,
}: {
  decoration: Decoration;
  value: string[];
  onChange: (colours: string[]) => void;
}) => {
  const { t } = useTranslation("profiles");
  const defaults = DEFAULT_TINTS[decoration.id] ?? [];
  // A well per colour the frame takes, named by which one it is: on a split
  // frame that is a side, and on a single-colour frame it is just the colour.
  const wells = defaults.map((fallback, index) => ({
    slot: `colour${index + 1}` as const,
    colour: value[index] || fallback,
    label:
      defaults.length > 1
        ? t(index === 0 ? "decorationPicker.colour1" : "decorationPicker.colour2")
        : t("decorationPicker.colour"),
    replace: (next: string) =>
      onChange(defaults.map((f, i) => (i === index ? next : value[i] || f))),
  }));

  return (
    <div className="flex items-center gap-3">
      {wells.map((well) => (
        <label
          key={well.slot}
          className="flex cursor-pointer items-center gap-2 text-muted-foreground text-xs"
        >
          <input
            type="color"
            value={well.colour}
            onChange={(event) => well.replace(event.target.value)}
            aria-label={well.label}
            className="size-7 cursor-pointer rounded-md border border-input bg-transparent p-0.5"
          />
          {well.label}
        </label>
      ))}
      <Button
        type="button"
        variant="ghost"
        size="sm"
        disabled={value.length === 0}
        onClick={() => onChange([])}
      >
        {t("decorationPicker.resetColour")}
      </Button>
    </div>
  );
};

/**
 * The picker for a slot that holds one thing — the banner, the frame.
 *
 * Picking the tile that is already on takes it off, so "none" needs no tile of
 * its own and there is one way to end up bare.
 */
export const SlotPicker = ({
  kind,
  value,
  onChange,
  owned,
  tint,
  onTint,
  year,
  onYear,
}: SlotPickerProps) => {
  const { t } = useTranslation("profiles");
  const choices = wearable(owned, kind);
  const worn = choices.find((decoration) => decoration.id === value);

  if (choices.length === 0) {
    return <p className="text-muted-foreground text-sm">{t("decorationPicker.empty")}</p>;
  }

  return (
    <div className="space-y-3">
      <fieldset className="flex min-w-0 flex-wrap gap-2">
        <legend className="sr-only">{t(`decorationPicker.${kind}`)}</legend>
        {choices.map((decoration) => (
          <Tile
            key={decoration.id}
            control="radio"
            name={`decoration-${kind}`}
            label={t(decoration.labelKey)}
            selected={value === decoration.id}
            onToggle={() => onChange(value === decoration.id ? null : decoration.id)}
          >
            <span className={kind === "banner" ? "block w-32" : "block"}>
              <DecorationSwatch
                decoration={decoration}
                tint={value === decoration.id ? tint : undefined}
                year={year}
              />
            </span>
          </Tile>
        ))}
      </fieldset>
      {/* Only where there is something to choose: the frames that ship with the
          app leave their colours open, and a pack's artwork is the pack's. */}
      {worn?.tint && onTint ? (
        <TintPicker decoration={worn} value={tint ?? []} onChange={onTint} />
      ) : null}
      {worn?.dated && onYear ? <YearPicker value={year ?? null} onChange={onYear} /> : null}
    </div>
  );
};

interface TrophyPickerProps {
  value: string[];
  onChange: (ids: string[]) => void;
  owned: OwnedDecoration[] | undefined;
  /** Mirrors ``MAX_PROFILE_BADGES`` on the server. */
  max: number;
  /** The year picked for a decoration that carries one, and how to change it. */
  year?: number | null;
  onYear?: (year: number) => void;
}

/**
 * The picker for the trophy row, which holds several.
 *
 * Order is the order they were picked, which is the order they are worn. Past
 * the cap the unpicked tiles stop responding rather than silently dropping the
 * oldest — what is worn is the reader's choice, not the picker's.
 */
export const TrophyPicker = ({ value, onChange, owned, max, year, onYear }: TrophyPickerProps) => {
  const { t } = useTranslation("profiles");
  const choices = wearable(owned, "trophy");

  if (choices.length === 0) {
    return <p className="text-muted-foreground text-sm">{t("decorationPicker.empty")}</p>;
  }

  const toggle = (id: string) => {
    if (value.includes(id)) {
      onChange(value.filter((worn) => worn !== id));
    } else if (value.length < max) {
      onChange([...value, id]);
    }
  };

  return (
    <div className="space-y-2">
      <fieldset className="flex min-w-0 flex-wrap gap-2">
        <legend className="sr-only">{t("decorationPicker.trophy")}</legend>
        {choices.map((decoration) => {
          const selected = value.includes(decoration.id);
          return (
            <Tile
              key={decoration.id}
              control="checkbox"
              label={t(decoration.labelKey)}
              selected={selected}
              disabled={!selected && value.length >= max}
              onToggle={() => toggle(decoration.id)}
            >
              <DecorationSwatch decoration={decoration} year={year} />
            </Tile>
          );
        })}
      </fieldset>
      <p className="text-muted-foreground text-xs">
        {t("decorationPicker.trophyCount", { count: value.length, max })}
      </p>
      {choices.some((decoration) => decoration.dated && value.includes(decoration.id)) && onYear ? (
        <YearPicker value={year ?? null} onChange={onYear} />
      ) : null}
    </div>
  );
};
