import { Check } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { CommunityCategory } from "@/api/generated/initiativeAPI.schemas";
import { PlacePicker } from "@/components/communities/PlacePicker";
import { ContinueButton, SkipButton } from "@/components/start/stepParts";
import { COMMUNITY_CATEGORIES, communityCategoryLabel } from "@/lib/communityCategories";
import type { Place } from "@/lib/directoryNear";
import { Button } from "@/ui/button";

/** Each shelf's own colour, spread evenly around the wheel. */
const shelfColour = (index: number): string =>
  `oklch(0.7 0.16 ${Math.round((index * 360) / COMMUNITY_CATEGORIES.length)})`;

/**
 * Where they are, if they like, and the directory shelves to open on, as many
 * as they like. The place sorts the directory nearest-first; it hides nothing.
 */
export const InterestStep = ({
  value,
  onChange,
  near,
  onNearChange,
  onContinue,
  onSkip,
  disabled,
}: {
  value: CommunityCategory[];
  onChange: (categories: CommunityCategory[]) => void;
  near: Place;
  onNearChange: (near: Place) => void;
  onContinue: () => void;
  onSkip: () => void;
  disabled?: boolean;
}) => {
  const { t } = useTranslation(["communities", "common"]);
  const { t: tAuth } = useTranslation("auth");
  const toggle = (category: CommunityCategory) =>
    onChange(
      value.includes(category)
        ? value.filter((picked) => picked !== category)
        : // Kept in the directory's own order, whatever order they were tapped in.
          COMMUNITY_CATEGORIES.filter((item) => item === category || value.includes(item))
    );
  return (
    <>
      <fieldset className="space-y-3">
        <legend className="font-medium text-sm">{tAuth("start.interest.whereTitle")}</legend>
        <p className="text-muted-foreground text-xs">{tAuth("start.interest.whereHint")}</p>
        <PlacePicker
          value={near}
          onChange={onNearChange}
          disabled={disabled}
          aria-label={tAuth("start.interest.whereTitle")}
        />
      </fieldset>
      <p className="font-medium text-sm">{tAuth("start.interest.whatTitle")}</p>
      <div className="flex flex-wrap gap-2">
        {COMMUNITY_CATEGORIES.map((category, index) => {
          const picked = value.includes(category);
          return (
            <Button
              key={category}
              type="button"
              size="sm"
              variant="outline"
              aria-pressed={picked}
              onClick={() => toggle(category)}
              className="rounded-full aria-pressed:border-primary aria-pressed:bg-primary/10"
            >
              {picked ? (
                <Check className="h-3.5 w-3.5 text-primary" aria-hidden="true" />
              ) : (
                <span
                  aria-hidden="true"
                  className="size-2.5 rotate-45 rounded-[2px]"
                  style={{ backgroundColor: shelfColour(index) }}
                />
              )}
              {communityCategoryLabel(category, t)}
            </Button>
          );
        })}
      </div>
      <ContinueButton onClick={onContinue} disabled={disabled} />
      <SkipButton onClick={onSkip} disabled={disabled} />
    </>
  );
};
