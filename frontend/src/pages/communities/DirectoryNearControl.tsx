/**
 * Where the directory is sorted from: "Near Seattle, Washington, United
 * States", or a way to say so.
 *
 * Setting a place puts the communities nearest it first and hides nothing; it
 * goes in the directory's address and is kept on this device for next time.
 * Clearing it drops both.
 */

import { useNavigate } from "@tanstack/react-router";
import { MapPin, X } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { PlacePicker } from "@/components/communities/PlacePicker";
import { useAuth } from "@/hooks/useAuth";
import { countryName } from "@/lib/communityLocation";
import {
  EMPTY_PLACE,
  NO_NEAR_SEARCH,
  nearOfPlace,
  nearSearchOf,
  type Place,
  saveNear,
} from "@/lib/directoryNear";
import { Button } from "@/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/ui/popover";

export const DirectoryNearControl = ({ near }: { near: Place | null }) => {
  const { t, i18n } = useTranslation("communities");
  const locale = i18n.resolvedLanguage ?? i18n.language ?? "en";
  const navigate = useNavigate();
  const { user } = useAuth();
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState<Place>(EMPTY_PLACE);

  const apply = (next: Place | null) => {
    saveNear(next, user?.id ?? null);
    void navigate({
      to: "/communities",
      search: (prev: Record<string, unknown>) => ({
        ...prev,
        ...NO_NEAR_SEARCH,
        ...nearSearchOf(next),
      }),
    });
    setOpen(false);
  };

  // An address that carried no words for its place is named by its country.
  const where = near ? near.text || countryName(near.country, locale) : null;
  const chosen = nearOfPlace(draft);

  return (
    <div className="flex items-center gap-1">
      <Popover
        open={open}
        onOpenChange={(next) => {
          if (next) setDraft(near?.text ? near : EMPTY_PLACE);
          setOpen(next);
        }}
      >
        <PopoverTrigger asChild>
          <Button variant="outline" size="sm" className="max-w-full rounded-full">
            <MapPin className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
            <span className="truncate">
              {where ? t("location.near.label", { place: where }) : t("location.near.add")}
            </span>
          </Button>
        </PopoverTrigger>
        <PopoverContent align="start" className="w-[min(90vw,28rem)] space-y-3">
          <div className="space-y-1">
            <p className="font-medium text-sm">{t("location.near.title")}</p>
            <p className="text-muted-foreground text-xs">{t("location.near.hint")}</p>
          </div>
          <PlacePicker value={draft} onChange={setDraft} aria-label={t("location.near.title")} />
          <div className="flex flex-wrap gap-2">
            <Button size="sm" disabled={!chosen} onClick={() => apply(chosen)}>
              {t("location.near.apply")}
            </Button>
          </div>
        </PopoverContent>
      </Popover>
      {near ? (
        <Button
          variant="ghost"
          size="icon"
          className="h-8 w-8 rounded-full"
          aria-label={t("location.near.clear")}
          onClick={() => apply(null)}
        >
          <X className="h-3.5 w-3.5" aria-hidden="true" />
        </Button>
      ) : null}
    </div>
  );
};
