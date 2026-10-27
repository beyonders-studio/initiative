import { Check, ExternalLink, Minus, Star } from "lucide-react";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import {
  type PropertyOption,
  type PropertySummary,
  PropertyType,
} from "@/api/generated/initiativeAPI.schemas";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { formatDate, formatDateTime } from "@/lib/formatDate";
import { numberFormat } from "@/lib/intl";
import { getAvatarSrc, getInitialsForUser, getUserDisplayName } from "@/lib/userDisplay";
import { cn } from "@/lib/utils";

import { isEmptyPropertyValue, numericValue, type RatingDisplay } from "./propertyHelpers";
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
  /** How a rating is drawn, as the list showing it says; a number without. */
  display?: RatingDisplay | null;
}

const formatNumber = (raw: unknown, options?: Intl.NumberFormatOptions): string => {
  const value = numericValue(raw);
  return value === null ? "" : numberFormat(undefined, options).format(value);
};

/** How many of five stars a rating of 1–100 fills: one for each fifth begun. */
const ratingStars = (rating: number): number => Math.min(5, Math.max(0, Math.ceil(rating / 20)));

/** A rating of 1–100 as a list draws it. */
const Rating = ({ value, display }: { value: number; display: RatingDisplay }) => {
  const { t } = useTranslation("properties");
  const label = t("cell.rating", { value: formatNumber(value) });
  if (display === "stars") {
    const filled = ratingStars(value);
    return (
      <span role="img" aria-label={label} title={label} className="inline-flex items-center">
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
        aria-label={label}
        title={label}
        className="inline-block h-1.5 w-16 overflow-hidden rounded-full bg-muted-foreground/20"
      >
        <span
          className="block h-full rounded-full bg-primary"
          style={{ width: `${Math.min(100, Math.max(0, value))}%` }}
        />
      </span>
    );
  }
  return <span className="tabular-nums">{formatNumber(value)}</span>;
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
}: PropertyValueCellProps) => {
  const { t } = useTranslation("properties");
  const options = useMemo(() => coerceOptionMap(summary?.options), [summary?.options]);

  if (!summary || isEmptyPropertyValue(summary.value)) {
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
    case PropertyType.text: {
      body = <span className="truncate">{String(value ?? "")}</span>;
      break;
    }
    case PropertyType.url: {
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
    case PropertyType.number: {
      body = <span className="tabular-nums">{formatNumber(value)}</span>;
      break;
    }
    case PropertyType.currency: {
      body = (
        <span className="tabular-nums">
          {summary.currency
            ? formatNumber(value, { style: "currency", currency: summary.currency })
            : formatNumber(value)}
        </span>
      );
      break;
    }
    case PropertyType.rating: {
      const rating = numericValue(value);
      body = rating === null ? null : <Rating value={rating} display={display ?? "number"} />;
      break;
    }
    case PropertyType.checkbox: {
      body =
        value === true ? (
          <Check className="h-4 w-4" aria-hidden />
        ) : (
          <Minus className="h-4 w-4 text-muted-foreground" aria-hidden />
        );
      break;
    }
    case PropertyType.date: {
      body = <span>{formatDate(value)}</span>;
      break;
    }
    case PropertyType.datetime: {
      body = <span>{formatDateTime(value)}</span>;
      break;
    }
    case PropertyType.select: {
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
    case PropertyType.multi_select: {
      const slugs = Array.isArray(value)
        ? (value as unknown[]).filter((v): v is string => typeof v === "string")
        : [];
      body = (
        <span className="flex max-w-full flex-wrap items-center gap-1">
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
    case PropertyType.user_reference: {
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
