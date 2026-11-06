import { Check, ExternalLink, Minus, Star } from "lucide-react";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import {
  type CounterSettingsOutput,
  MetadataType,
  type PropertyOption,
  type PropertySummary,
} from "@/api/generated/initiativeAPI.schemas";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { formatDate, formatDateTime } from "@/lib/formatDate";
import { numberFormat } from "@/lib/intl";
import { getAvatarSrc, getInitialsForUser, getUserDisplayName } from "@/lib/userDisplay";
import { cn } from "@/lib/utils";

import {
  counterCount,
  counterSettings,
  type FieldDisplay,
  isEmptyPropertyValue,
  numericValue,
  scaleValue,
} from "./propertyHelpers";
import { iconForPropertyType } from "./propertyTypeIcons";

type CellVariant = "cell" | "chip";

export interface PropertyValueCellProps {
  summary: PropertySummary | undefined;
  variant?: CellVariant;
  className?: string;
  /** Set when the cell renders inside a wrapping link (card-as-anchor): a URL
   * value opens via a programmatic handler instead of nesting an `<a>` in an
   * `<a>`, and stops the click from also triggering the outer link. */
  nested?: boolean;
  /** How a scale or a counter is drawn, as the layout showing it says; a
   *  number without. */
  display?: FieldDisplay | null;
  /** On one line, its chips past the end cut off: a card whose height is
   *  reserved without measuring it. */
  oneLine?: boolean;
}

const formatNumber = (raw: unknown, options?: Intl.NumberFormatOptions): string => {
  const value = numericValue(raw);
  return value === null ? "" : numberFormat(undefined, options).format(value);
};

/** How many of five stars a scale of 0–100 fills: one for each fifth begun. */
const scaleStars = (value: number): number => Math.min(5, Math.max(0, Math.ceil(value / 20)));

/** A scale of 0–100 as a number ("80%"), five stars or a bar. */
export const ScaleValue = ({ value, display }: { value: number; display: FieldDisplay }) => {
  const { i18n } = useTranslation();
  const percent = numberFormat(i18n.language, { style: "percent" }).format(value / 100);
  if (display === "stars") {
    const filled = scaleStars(value);
    return (
      <span role="img" aria-label={percent} title={percent} className="inline-flex items-center">
        {[1, 2, 3, 4, 5].map((star) => (
          <Star
            key={star}
            aria-hidden
            className={cn(
              "h-3.5 w-3.5",
              star <= filled ? "fill-current text-warning" : "text-muted-foreground/40"
            )}
          />
        ))}
      </span>
    );
  }
  if (display === "bar") {
    return (
      <span
        role="img"
        aria-label={percent}
        title={percent}
        className="inline-block h-1.5 w-16 overflow-hidden rounded-full bg-muted-foreground/20"
      >
        <span className="block h-full rounded-full bg-primary" style={{ width: `${value}%` }} />
      </span>
    );
  }
  return <span className="tabular-nums">{percent}</span>;
};

/** The most steps a counter's clock is drawn with, one segment each; a
 *  counter with more fills its clock as a dial. */
const MAX_CLOCK_SEGMENTS = 60;

/** A slice of a 16-unit clock face, from one fraction of a turn to another. */
const wedge = (from: number, to: number): string => {
  const point = (turn: number) =>
    `${8 + 7 * Math.sin(2 * Math.PI * turn)} ${8 - 7 * Math.cos(2 * Math.PI * turn)}`;
  return `M8 8 L${point(from)} A7 7 0 ${to - from > 0.5 ? 1 : 0} 1 ${point(to)} Z`;
};

/** A counter's count as a number, then for a bar or a clock its place
 *  between its bounds. A counter without both bounds is drawn as a number. */
export const CounterValue = ({
  count,
  settings,
  display,
}: {
  count: number;
  settings: CounterSettingsOutput | null;
  display: FieldDisplay;
}) => {
  const { min, max, step } = counterSettings(settings);
  const number = <span className="tabular-nums">{formatNumber(count)}</span>;
  const drawn = display === "bar" || display === "clock";
  if (!drawn || min === null || max === null || max <= min) return number;
  const filled = Math.min(1, Math.max(0, (count - min) / (max - min)));
  const label = `${formatNumber(count)} / ${formatNumber(max)}`;
  const segments = Math.round((max - min) / step);
  return (
    <span className="inline-flex items-center gap-1.5">
      {number}
      {display === "clock" ? (
        <svg role="img" aria-label={label} viewBox="0 0 16 16" className="h-4 w-4 shrink-0">
          <title>{label}</title>
          <circle cx="8" cy="8" r="7" className="fill-muted-foreground/20" />
          {segments >= 2 && segments <= MAX_CLOCK_SEGMENTS ? (
            Array.from({ length: segments }, (_, index) => (
              <path
                // biome-ignore lint/suspicious/noArrayIndexKey: a clock's segments are its places
                key={index}
                d={wedge(index / segments, (index + 1) / segments)}
                className={cn(
                  "stroke-background",
                  index < Math.round(filled * segments) ? "fill-primary" : "fill-transparent"
                )}
                strokeWidth={0.75}
              />
            ))
          ) : filled >= 1 ? (
            <circle cx="8" cy="8" r="7" className="fill-primary" />
          ) : filled > 0 ? (
            <path d={wedge(0, filled)} className="fill-primary" />
          ) : null}
        </svg>
      ) : (
        <span
          role="img"
          aria-label={label}
          title={label}
          className="inline-block h-1.5 w-16 overflow-hidden rounded-full bg-muted-foreground/20"
        >
          <span
            className="block h-full rounded-full bg-primary"
            style={{ width: `${filled * 100}%` }}
          />
        </span>
      )}
    </span>
  );
};

const coerceOptionMap = (options: PropertyOption[] | null | undefined) => {
  const map = new Map<string, PropertyOption>();
  for (const option of options ?? []) {
    map.set(option.value, option);
  }
  return map;
};

interface SelectChipProps {
  option: PropertyOption | undefined;
  slug: string;
  unknownLabel: string;
  dense?: boolean;
}

const SelectChip = ({ option, slug, unknownLabel, dense }: SelectChipProps) => {
  const label = option?.label ?? unknownLabel;
  const color = option?.color ?? null;
  return (
    <span
      className={cn(
        "inline-flex max-w-full items-center gap-1.5 truncate",
        dense ? "text-xs" : "text-sm",
        !option && "italic"
      )}
      title={option ? option.label : slug}
    >
      {color ? (
        <span
          className="inline-block h-2 w-2 shrink-0 rounded-full"
          style={{ backgroundColor: color }}
        />
      ) : null}
      <span className="truncate">{label}</span>
    </span>
  );
};

export interface UserValue {
  id: number;
  username?: string | null;
  discriminator?: number | null;
  display_name?: string | null;
  avatar_url?: string | null;
}

export const extractUser = (raw: unknown): UserValue | null => {
  if (raw && typeof raw === "object" && "id" in raw) {
    const id = (raw as { id: unknown }).id;
    if (typeof id === "number" && Number.isFinite(id)) {
      return raw as UserValue;
    }
  }
  if (typeof raw === "number" && Number.isFinite(raw)) {
    return { id: raw };
  }
  return null;
};

/**
 * Render a single PropertySummary value in either a `cell` (table) or
 * `chip` (card) layout. Empty values render an em-dash in `cell` mode and
 * return `null` in `chip` mode so cards aren't littered with unset rows.
 */
export const PropertyValueCell = ({
  summary,
  variant = "cell",
  className,
  nested = false,
  display,
  oneLine = false,
}: PropertyValueCellProps) => {
  const { t } = useTranslation("properties");
  const options = useMemo(() => coerceOptionMap(summary?.options), [summary?.options]);

  // A counter with no value holds its initial value.
  if (!summary || (isEmptyPropertyValue(summary.value) && summary.type !== MetadataType.counter)) {
    if (variant === "chip") return null;
    return (
      <span
        role="img"
        aria-label={t("cell.none")}
        className={cn("text-muted-foreground", className)}
      >
        {t("cell.emptyValue")}
      </span>
    );
  }

  const { type, value } = summary;

  let body: React.ReactNode = null;

  switch (type) {
    case MetadataType.text: {
      body = <span className="truncate">{String(value ?? "")}</span>;
      break;
    }
    case MetadataType.url: {
      const href = typeof value === "string" ? value : "";
      const urlClassName =
        "inline-flex max-w-full items-center gap-1 truncate text-primary hover:underline";
      const urlContent = (
        <>
          <span className="truncate">{href}</span>
          <ExternalLink className="h-3 w-3 shrink-0" aria-hidden />
        </>
      );
      body = nested ? (
        // biome-ignore lint/a11y/useSemanticElements: a <button> is also invalid interactive content nested inside the wrapping card <a>; a role=button span avoids the nested-anchor while staying keyboard-accessible.
        <span
          role="button"
          tabIndex={0}
          className={cn(urlClassName, "cursor-pointer")}
          onClick={(e) => {
            e.preventDefault();
            e.stopPropagation();
            if (href) window.open(href, "_blank", "noopener,noreferrer");
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") {
              e.preventDefault();
              e.stopPropagation();
              if (href) window.open(href, "_blank", "noopener,noreferrer");
            }
          }}
        >
          {urlContent}
        </span>
      ) : (
        <a
          href={href}
          target="_blank"
          rel="noopener noreferrer"
          className={urlClassName}
          onClick={(e) => e.stopPropagation()}
        >
          {urlContent}
        </a>
      );
      break;
    }
    case MetadataType.number: {
      body = <span className="tabular-nums">{formatNumber(value)}</span>;
      break;
    }
    case MetadataType.currency: {
      body = (
        <span className="tabular-nums">
          {summary.currency
            ? formatNumber(value, { style: "currency", currency: summary.currency })
            : formatNumber(value)}
        </span>
      );
      break;
    }
    case MetadataType.scale: {
      const figure = scaleValue(value);
      body = figure === null ? null : <ScaleValue value={figure} display={display ?? "number"} />;
      break;
    }
    case MetadataType.counter: {
      body = (
        <CounterValue
          count={counterCount(summary.counter, value)}
          settings={summary.counter}
          display={display ?? "number"}
        />
      );
      break;
    }
    case MetadataType.checkbox: {
      body =
        value === true ? (
          <Check className="h-4 w-4" aria-hidden />
        ) : (
          <Minus className="h-4 w-4 text-muted-foreground" aria-hidden />
        );
      break;
    }
    case MetadataType.date: {
      body = <span>{formatDate(value)}</span>;
      break;
    }
    case MetadataType.datetime: {
      body = <span>{formatDateTime(value)}</span>;
      break;
    }
    case MetadataType.select: {
      const slug = String(value ?? "");
      const option = options.get(slug);
      body = (
        <SelectChip
          option={option}
          slug={slug}
          unknownLabel={t("input.unknownOption", { value: slug })}
          dense={variant === "chip"}
        />
      );
      break;
    }
    case MetadataType.multi_select: {
      const slugs = Array.isArray(value)
        ? (value as unknown[]).filter((v): v is string => typeof v === "string")
        : [];
      body = (
        <span
          className={cn(
            "flex max-w-full items-center gap-1",
            oneLine ? "overflow-hidden *:shrink-0" : "flex-wrap"
          )}
        >
          {slugs.map((slug) => (
            <SelectChip
              key={slug}
              option={options.get(slug)}
              slug={slug}
              unknownLabel={t("input.unknownOption", { value: slug })}
              dense
            />
          ))}
        </span>
      );
      break;
    }
    case MetadataType.user_reference: {
      const user = extractUser(value);
      if (!user) {
        body = <span className="text-muted-foreground italic">{t("cell.emptyValue")}</span>;
      } else {
        const name = getUserDisplayName(user, `#${user.id}`);
        const userAvatarSrc = getAvatarSrc(user);
        body = (
          <span className="inline-flex max-w-full items-center gap-2 truncate">
            <Avatar className="h-5 w-5 text-3xs">
              {userAvatarSrc ? <AvatarImage src={userAvatarSrc} alt={name} /> : null}
              <AvatarFallback userId={user.id}>{getInitialsForUser(user)}</AvatarFallback>
            </Avatar>
            <span className="truncate">{name}</span>
          </span>
        );
      }
      break;
    }
    default:
      body = null;
  }

  if (variant === "chip") {
    const Icon = iconForPropertyType(type);
    return (
      <span
        className={cn(
          "inline-flex max-w-full items-center gap-1 rounded-md bg-muted px-1.5 py-0.5 text-muted-foreground text-xs",
          className
        )}
      >
        <Icon className="h-3 w-3 shrink-0" aria-hidden />
        <span className="truncate font-medium">{summary.name}:</span>
        <span className="max-w-[14rem] truncate text-foreground">{body}</span>
      </span>
    );
  }

  return (
    <div className={cn("flex min-w-0 max-w-full items-center gap-1 truncate", className)}>
      {body}
    </div>
  );
};
