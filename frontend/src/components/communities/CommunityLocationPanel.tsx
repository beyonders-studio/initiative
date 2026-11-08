/**
 * Where the community is — optional, and as broad or as exact as its admin
 * likes: a country alone, a city, or a street address, typed into one field,
 * and a name of their own for the place on top. A place picked from the
 * suggestions pins it, which is what lets the directory put the community near
 * the people browsing for one.
 */

import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import { updateCommunity } from "@/api/generated/communities/communities";
import type { CommunityRead } from "@/api/generated/initiativeAPI.schemas";
import { PlacePicker } from "@/components/communities/PlacePicker";
import { SettingsSection } from "@/components/settings/SettingsSection";
import { useCommunities } from "@/hooks/useCommunities";
import type { CommunityLocation } from "@/lib/communityLocation";
import { type Place, placeFrom } from "@/lib/directoryNear";
import { getErrorMessage } from "@/lib/errorMessage";
import { toast } from "@/lib/mascotToast";
import { Button } from "@/ui/button";
import { Field } from "@/ui/field";
import { Input } from "@/ui/input";

/** The server's limit on the community's own name for the place. */
const LABEL_MAX = 60;

/** The location the fields hold; none without a place, whatever its name. */
export const locationOf = (place: Place, label: string): CommunityLocation | null =>
  place.text.trim()
    ? {
        text: place.text.trim(),
        label: label.trim() || null,
        country: place.country || null,
        latitude: place.latitude,
        longitude: place.longitude,
      }
    : null;

export const CommunityLocationPanel = () => {
  const { activeCommunity, refreshCommunities, updateCommunityInState } = useCommunities();
  const { t } = useTranslation(["communities", "common"]);
  const [draft, setDraft] = useState<Place>(() => placeFrom(activeCommunity?.location));
  const [label, setLabel] = useState(() => activeCommunity?.location?.label ?? "");
  const [saving, setSaving] = useState(false);

  const stored = activeCommunity?.location;
  // Compared by value: the community list is refetched on focus, and a fresh copy
  // of the same location must not throw away what is being typed.
  const storedKey = JSON.stringify(stored ?? null);
  const [prevStoredKey, setPrevStoredKey] = useState(storedKey);
  if (prevStoredKey !== storedKey) {
    setPrevStoredKey(storedKey);
    setDraft(placeFrom(stored));
    setLabel(stored?.label ?? "");
  }

  if (!activeCommunity) return null;

  const save = async (location: CommunityLocation | null, done: string) => {
    setSaving(true);
    try {
      const result = (await updateCommunity(activeCommunity.id, {
        location,
      } as Parameters<typeof updateCommunity>[1])) as unknown as CommunityRead;
      updateCommunityInState(result);
      await refreshCommunities();
      toast.success(done);
    } catch (err) {
      toast.error(getErrorMessage(err, "communities:settings.unableToUpdate"));
    } finally {
      setSaving(false);
    }
  };

  const location = locationOf(draft, label);

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    void save(location, t("location.saved"));
  };

  return (
    <SettingsSection title={t("location.title")} description={t("location.description")}>
      <form className="space-y-4" onSubmit={handleSubmit}>
        <Field label={t("location.fieldLabel")}>
          <PlacePicker value={draft} onChange={setDraft} disabled={saving} />
        </Field>

        <Field label={t("location.labelLabel")} hint={t("location.labelHint")}>
          <Input
            value={label}
            onChange={(event) => setLabel(event.target.value)}
            maxLength={LABEL_MAX}
            placeholder={t("location.labelPlaceholder")}
            disabled={saving}
          />
        </Field>

        {activeCommunity.is_community && location ? (
          <p className="text-muted-foreground text-xs">{t("location.listedNote")}</p>
        ) : null}

        <div className="flex flex-wrap gap-2">
          <Button type="submit" disabled={saving || !location}>
            {saving ? t("settings.saving") : t("location.save")}
          </Button>
          {stored ? (
            <Button
              type="button"
              variant="outline"
              disabled={saving}
              onClick={() => void save(null, t("location.removed"))}
            >
              {t("location.remove")}
            </Button>
          ) : null}
        </div>
      </form>
    </SettingsSection>
  );
};
