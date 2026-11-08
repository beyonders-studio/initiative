/**
 * The gate between a private community and a listed one.
 *
 * Listing publishes a community to everyone signed in, so it is a decision made
 * once, deliberately, with both of its conditions in front of you: at least one
 * category, and a certification about what the community contains. Neither is a
 * default anyone can click past — Confirm stays disabled until both are met,
 * and the server refuses the same two conditions independently.
 *
 * The certification is what answers the community's 18+ question. Ticking it here
 * is the only path from unanswered to "no", which is why the statement sits
 * with the checkbox rather than in a policy page nobody opens.
 */

import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { CommunityCategory } from "@/api/generated/initiativeAPI.schemas";
import { COMMUNITY_CATEGORIES, communityCategoryLabel } from "@/lib/communityCategories";
import { Button } from "@/ui/button";
import { Checkbox } from "@/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/ui/dialog";
import { Label } from "@/ui/label";
import { cn } from "@/ui/lib/utils";

/** One key per line of the certification, so a translator sees each claim on
 *  its own rather than one paragraph to keep in sync. */
const CERTIFY_KEYS = [
  "certifyPorn",
  "certifyMinors",
  "certifyIllegal",
  "certifyViolence",
  "certifyHate",
] as const;

export const PublishCommunityDialog = ({
  open,
  saving,
  initialCategories,
  onCancel,
  onConfirm,
}: {
  open: boolean;
  saving: boolean;
  initialCategories: CommunityCategory[];
  onCancel: () => void;
  onConfirm: (categories: CommunityCategory[]) => void | Promise<void>;
}) => {
  const { t } = useTranslation(["communities", "common"]);
  const [categories, setCategories] = useState<CommunityCategory[]>(initialCategories);
  const [certified, setCertified] = useState(false);

  // Every opening starts from the community's current shelves and an un-ticked
  // certification: it is an assertion made now, not one a previous visit made.
  const [prev, setPrev] = useState({ open, initialCategories });
  if (prev.open !== open || prev.initialCategories !== initialCategories) {
    setPrev({ open, initialCategories });
    if (open) {
      setCategories(initialCategories);
      setCertified(false);
    }
  }

  const toggleCategory = (category: CommunityCategory) => {
    setCategories((current) =>
      current.includes(category)
        ? current.filter((value) => value !== category)
        : [...current, category]
    );
  };

  const ready = categories.length > 0 && certified;

  return (
    <Dialog open={open} onOpenChange={(next) => !next && !saving && onCancel()}>
      <DialogContent className="bg-card sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{t("communities:community.publish.title")}</DialogTitle>
          <DialogDescription>{t("communities:community.publish.description")}</DialogDescription>
        </DialogHeader>

        <fieldset className="space-y-2">
          <legend className="font-medium text-sm">
            {t("communities:community.publish.categoriesLabel")}
          </legend>
          <p className="text-muted-foreground text-sm">
            {t("communities:community.publish.categoriesHint")}
          </p>
          <div className="flex flex-wrap gap-2 pt-1">
            {COMMUNITY_CATEGORIES.map((category) => {
              const selected = categories.includes(category);
              return (
                <button
                  key={category}
                  type="button"
                  onClick={() => toggleCategory(category)}
                  aria-pressed={selected}
                  className={cn(
                    "rounded-full border px-3 py-1 text-sm transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                    selected
                      ? "border-primary bg-primary/10 text-primary"
                      : "border-input text-muted-foreground hover:bg-muted hover:text-foreground"
                  )}
                >
                  {communityCategoryLabel(category, t)}
                </button>
              );
            })}
          </div>
        </fieldset>

        <div className="space-y-3 rounded-lg border bg-muted/40 p-3">
          <div className="flex items-start gap-3">
            <Checkbox
              id="community-certify-no-adult-content"
              checked={certified}
              onCheckedChange={(next) => setCertified(next === true)}
              className="mt-0.5"
            />
            <Label
              htmlFor="community-certify-no-adult-content"
              className="font-medium text-sm leading-snug"
            >
              {t("communities:community.publish.certifyLabel")}
            </Label>
          </div>
          <p className="text-muted-foreground text-sm">
            {t("communities:community.publish.certifyIntro")}
          </p>
          <ul className="list-disc space-y-1 pl-5 text-sm">
            {CERTIFY_KEYS.map((key) => (
              <li key={key}>{t(`communities:community.publish.${key}`)}</li>
            ))}
          </ul>
          <p className="font-medium text-sm">{t("communities:community.publish.certifyDuty")}</p>
        </div>

        <DialogFooter>
          <Button type="button" variant="outline" onClick={onCancel} disabled={saving}>
            {t("common:cancel")}
          </Button>
          <Button
            type="button"
            onClick={() => void onConfirm(categories)}
            disabled={!ready || saving}
          >
            {saving ? t("communities:settings.saving") : t("communities:community.publish.confirm")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};
