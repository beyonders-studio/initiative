import { Link } from "@tanstack/react-router";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { UserRead, UserSelfUpdate } from "@/api/generated/initiativeAPI.schemas";
import { SettingsSection } from "@/components/settings/SettingsSection";
import { SlotPicker, TrophyPicker } from "@/components/user/DecorationPicker";
import { MyDecorationPacks } from "@/components/user/MyDecorationPacks";
import { ProfilePreview } from "@/components/user/ProfilePreview";
import { useMyDecorations, useUpdateCurrentUser } from "@/hooks/useUsers";
import { getErrorMessage } from "@/lib/errorMessage";
import { currentYear, DATED_DECORATIONS } from "@/lib/gradArtwork";
import { toast } from "@/lib/mascotToast";
import { Button } from "@/ui/button";
import { Label } from "@/ui/label";

/** Mirrors ``MAX_PROFILE_TROPHIES`` on the server. */
const MAX_TROPHIES = 6;

interface UserSettingsProfilePageProps {
  user: UserRead;
  refreshUser: () => Promise<void>;
}

/**
 * Your profile: the face other people see, and everything that makes it.
 *
 * The card at the top is that face, kept live against the pickers below it —
 * and it is the controls too. Your picture, your status and the dot saying how
 * you appear are all set by clicking them on the card, because that is where
 * you are looking when you decide to change them, and a form further down
 * would be a second place to keep in agreement with the first.
 *
 * Your packs sit under your look rather than over it: what you are wearing is
 * why you came, and what you own is where you go to change it.
 *
 * How you sign in is Settings › Account. Nothing on this page is private.
 */
export const UserSettingsProfilePage = ({ user, refreshUser }: UserSettingsProfilePageProps) => {
  const { t } = useTranslation(["profiles", "common"]);
  const { data: library } = useMyDecorations();

  const [banner, setBanner] = useState(user.profile_decorations.banner ?? null);
  const [frame, setFrame] = useState(user.profile_decorations.frame ?? null);
  const [trophies, setTrophies] = useState<string[]>(user.profile_decorations.trophies ?? []);
  const [frameTint, setFrameTint] = useState<string[]>(user.profile_decorations.frame_tint ?? []);
  const [gradYear, setGradYear] = useState<number | null>(
    user.profile_decorations.grad_year ?? null
  );

  // Removing a pack takes its pieces off server-side, so the pickers follow the
  // saved look when it changes underneath them — but only then. Following the
  // whole account would throw away a pick every time anything else was saved.
  const savedLook = JSON.stringify(user.profile_decorations);
  const [syncedLook, setSyncedLook] = useState(savedLook);
  if (syncedLook !== savedLook) {
    setSyncedLook(savedLook);
    setBanner(user.profile_decorations.banner ?? null);
    setFrame(user.profile_decorations.frame ?? null);
    setTrophies(user.profile_decorations.trophies ?? []);
    setFrameTint(user.profile_decorations.frame_tint ?? []);
    setGradYear(user.profile_decorations.grad_year ?? null);
  }

  const saveLook = useUpdateCurrentUser({
    onSuccess: async () => {
      await refreshUser();
      toast.success(t("profiles:look.saved"));
    },
    onError: (error: unknown) => toast.error(getErrorMessage(error, "profiles:look.failed")),
  });

  // Giving a pack back takes its pieces out of the library, and off the saved
  // look — but a piece picked here and not yet saved is in neither, so nothing
  // above would drop it. The pickers show what the library still answers for,
  // which is also what the write path accepts. Held back until the library has
  // loaded, or a slow read would undress everything on the way past.
  const ownedIds = library ? new Set(library.items.map((item) => item.id)) : null;
  const stillOwned = (id: string | null) => (id && (!ownedIds || ownedIds.has(id)) ? id : null);
  // An emptied slot is the default a bare profile has always had; a trophy just
  // leaves the row.
  const wornBanner = stillOwned(banner);
  const wornFrame = stillOwned(frame);
  const wornTrophies = ownedIds ? trophies.filter((trophy) => ownedIds.has(trophy)) : trophies;
  // A colour belongs to the frame it was picked for, so it goes wherever that
  // frame goes — including away.
  const wornTint = wornFrame ? frameTint : [];
  // Same rule for the year: it belongs to whatever is wearing it, so it goes
  // when nothing is. Unset while something dated is on means this year, which
  // is what the picker is showing.
  const wearingDated =
    DATED_DECORATIONS.has(wornBanner ?? "") ||
    wornTrophies.some((trophy) => DATED_DECORATIONS.has(trophy));
  const wornYear = wearingDated ? (gradYear ?? currentYear()) : null;

  const saved = user.profile_decorations;
  const changed =
    wornBanner !== (saved.banner ?? null) ||
    wornFrame !== (saved.frame ?? null) ||
    wornTrophies.join() !== (saved.trophies ?? []).join() ||
    wornTint.join() !== (saved.frame_tint ?? []).join() ||
    wornYear !== (saved.grad_year ?? null);

  return (
    <div className="space-y-6">
      <ProfilePreview
        user={user}
        decorations={{
          banner: wornBanner,
          frame: wornFrame,
          trophies: wornTrophies,
          frame_tint: wornTint,
          grad_year: wornYear,
        }}
        status={user.custom_status}
        presence={user.presence}
        joinedAt={user.created_at}
        onChanged={refreshUser}
      />

      <SettingsSection
        title={t("profiles:look.title")}
        description={t("profiles:look.description")}
        contentClassName="space-y-6"
        footer={
          <Button
            disabled={!changed || saveLook.isPending}
            onClick={() =>
              saveLook.mutate({
                profile_decorations: {
                  banner: wornBanner,
                  frame: wornFrame,
                  trophies: wornTrophies,
                  frame_tint: wornTint,
                  grad_year: wornYear,
                },
              } as UserSelfUpdate)
            }
          >
            {saveLook.isPending ? t("common:submitting") : t("profiles:look.save")}
          </Button>
        }
      >
        <div className="space-y-2">
          <Label className="text-muted-foreground text-xs">
            {t("profiles:decorationPicker.banner")}
          </Label>
          <SlotPicker
            kind="banner"
            value={wornBanner}
            onChange={setBanner}
            owned={library?.items}
            year={wornYear}
            onYear={setGradYear}
          />
        </div>
        <div className="space-y-2">
          <Label className="text-muted-foreground text-xs">
            {t("profiles:decorationPicker.frame")}
          </Label>
          <SlotPicker
            kind="frame"
            value={wornFrame}
            onChange={(id) => {
              setFrame(id);
              // Colours belong to the frame they were picked for; another frame
              // starts from its own defaults rather than inheriting somebody
              // else's green.
              setFrameTint([]);
            }}
            owned={library?.items}
            tint={frameTint}
            onTint={setFrameTint}
          />
        </div>
        <div className="space-y-2">
          <Label className="text-muted-foreground text-xs">
            {t("profiles:decorationPicker.trophy")}
          </Label>
          <TrophyPicker
            value={wornTrophies}
            onChange={setTrophies}
            owned={library?.items}
            max={MAX_TROPHIES}
            year={wornYear}
            onYear={setGradYear}
          />
        </div>
      </SettingsSection>

      <SettingsSection
        title={t("profiles:myPacks.title")}
        description={t("profiles:myPacks.description")}
        action={
          <Button variant="outline" size="sm" asChild>
            <Link to="/marketplace">{t("profiles:myPacks.browse")}</Link>
          </Button>
        }
      >
        <MyDecorationPacks />
      </SettingsSection>
    </div>
  );
};
