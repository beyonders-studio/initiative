/**
 * A place, typed: a country, a city, a full street address — as short or as
 * long as somebody likes. Places are suggested while they type; picking one
 * pins the field to it (its country, and for a city its point), which is what
 * sorts by distance. Typing on after a pick, a street in front of a city say,
 * keeps the pin. Used wherever somebody names a place: a community saying
 * where it is, and a reader of the directory saying where they are.
 *
 * Suggestions come closest first, measured from the place already pinned, or
 * from where the browser's time zone puts the reader.
 */

import { MapPin } from "lucide-react";
import { type KeyboardEvent, useDeferredValue, useId, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { usePlaceIndex } from "@/hooks/usePlaceIndex";
import { countryName } from "@/lib/communityLocation";
import { EMPTY_PLACE, PLACE_TEXT_MAX, type Place } from "@/lib/directoryNear";
import { browserOrigin, type PlaceSuggestion, suggestPlaces } from "@/lib/placeSearch";
import { Input } from "@/ui/input";
import { cn } from "@/ui/lib/utils";

/** Suggestions listed at once; a few more letters narrow the rest. */
const SUGGESTION_LIMIT = 8;

export const PlacePicker = ({
  value,
  onChange,
  disabled = false,
  id,
  className,
  "aria-label": ariaLabel,
}: {
  value: Place;
  onChange: (place: Place) => void;
  disabled?: boolean;
  /** For a label of the caller's. */
  id?: string;
  className?: string;
  "aria-label"?: string;
}) => {
  const { t, i18n } = useTranslation("communities");
  const locale = i18n.resolvedLanguage ?? i18n.language ?? "en";
  const listId = useId();
  const [wanted, setWanted] = useState(false);
  const [focused, setFocused] = useState(false);
  // Closed by a pick, Escape or leaving the field; typing opens it again.
  const [closed, setClosed] = useState(false);
  const [active, setActive] = useState(0);
  const places = usePlaceIndex(wanted);
  const query = useDeferredValue(value.text);
  const { latitude, longitude } = value;

  // Closest first: to the place already pinned, else to where the browser's
  // time zone says the reader is.
  const reader = useMemo(() => (places.data ? browserOrigin(places.data) : null), [places.data]);
  const suggestions = useMemo(() => {
    if (!places.data || !query.trim()) return [];
    const origin = latitude !== null && longitude !== null ? { latitude, longitude } : reader;
    return suggestPlaces(places.data, query, { locale, origin, limit: SUGGESTION_LIMIT });
  }, [places.data, query, locale, latitude, longitude, reader]);
  const open = focused && !closed && suggestions.length > 0;
  const loading = focused && !closed && places.isFetching && value.text.trim().length > 1;

  const pick = (suggestion: PlaceSuggestion) => {
    onChange({ ...suggestion.place, text: suggestion.place.text.slice(0, PLACE_TEXT_MAX) });
    setClosed(true);
  };

  const type = (text: string) => {
    // Nothing typed is nowhere; anything else keeps whatever was pinned.
    onChange(text.trim() ? { ...value, text } : EMPTY_PLACE);
    setClosed(false);
    setActive(0);
  };

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (!open) return;
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      const step = event.key === "ArrowDown" ? 1 : -1;
      setActive((current) => (current + step + suggestions.length) % suggestions.length);
    } else if (event.key === "Enter") {
      event.preventDefault();
      pick(suggestions[Math.min(active, suggestions.length - 1)]);
    } else if (event.key === "Escape") {
      event.preventDefault();
      setClosed(true);
    }
  };

  const country = value.country ? countryName(value.country, locale) : "";

  return (
    <div className={cn("space-y-1.5", className)}>
      <div className="relative">
        <Input
          id={id}
          value={value.text}
          onChange={(event) => type(event.target.value)}
          onFocus={() => {
            setWanted(true);
            setFocused(true);
          }}
          onBlur={() => {
            setFocused(false);
            setClosed(false);
          }}
          onKeyDown={onKeyDown}
          maxLength={PLACE_TEXT_MAX}
          placeholder={t("location.placeholder")}
          autoComplete="off"
          disabled={disabled}
          role="combobox"
          aria-label={ariaLabel}
          aria-autocomplete="list"
          aria-expanded={open}
          aria-controls={listId}
          aria-activedescendant={open ? `${listId}-${active}` : undefined}
        />
        {open || loading ? (
          <div
            id={listId}
            role="listbox"
            aria-label={ariaLabel}
            className="absolute inset-x-0 top-full z-50 mt-1 max-h-72 overflow-y-auto rounded-md border bg-popover p-1 text-popover-foreground shadow-md"
          >
            {open ? (
              suggestions.map((suggestion, position) => (
                // biome-ignore lint/a11y/useFocusableInteractive lint/a11y/useKeyWithClickEvents: the field keeps the focus and its keys pick (aria-activedescendant)
                <div
                  key={suggestion.label}
                  id={`${listId}-${position}`}
                  role="option"
                  aria-selected={position === active}
                  // Keeps the field focused, so the pick is not lost to a blur.
                  onMouseDown={(event) => event.preventDefault()}
                  onClick={() => pick(suggestion)}
                  onMouseEnter={() => setActive(position)}
                  className={cn(
                    "flex cursor-pointer items-center gap-2 rounded-sm px-2 py-1.5 text-sm",
                    position === active && "bg-accent text-accent-foreground"
                  )}
                >
                  <MapPin className="h-3.5 w-3.5 shrink-0 opacity-60" aria-hidden="true" />
                  <span className="truncate">{suggestion.label}</span>
                </div>
              ))
            ) : (
              <div className="px-2 py-1.5 text-muted-foreground text-sm">
                {t("location.loading")}
              </div>
            )}
          </div>
        ) : null}
      </div>
      {value.text.trim() ? (
        <p className="text-muted-foreground text-xs">
          {!value.country
            ? t("location.unpinned")
            : value.latitude === null
              ? t("location.pinnedCountry", { country })
              : t("location.pinnedPlace", { country })}
        </p>
      ) : null}
    </div>
  );
};
