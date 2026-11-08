/**
 * The pictures a community is known by: its icon, and its banner.
 *
 * Both are uploaded rather than typed, and both are resized here before they
 * are sent — an admin picks one file per picture and the browser produces the
 * renditions the server stores (see ``lib/imageRenditions``). Nobody is asked to
 * prepare a thumbnail, and nobody has to know what 4:1 means to get it right.
 *
 * Every community has a banner: the artwork it uploaded, or the colour it wears
 * instead. So there are two colours here, not one — the fill, and what the
 * community's name and description are written in. The text colour is a setting
 * rather than something derived, because artwork is not one colour and what
 * reads over a picture is not ours to guess; picking a fill moves it to the
 * best contrast against that fill, which is the answer whenever there is no
 * artwork. It is a choice between two colours rather than a picker: black or
 * white is what keeps the words readable on a fill nobody here chose.
 *
 * Beside the two colours are the two layout choices: where the copy sits
 * across the banner, and whether the banner ends at an edge or is extended
 * past it and dissolved into the page under the page's own content. Both are
 * closed sets rather than sliders, and both save the moment they are picked —
 * there is nothing to confirm about a look the preview above is already
 * showing.
 *
 * Where an operator has not given a community banner artwork, this offers the
 * colour and no upload: an upload control that only ever answers "no" is worse
 * than none. The server refuses it regardless — this is what the settings page
 * shows, not what enforces it — and a banner the community already has keeps being
 * shown and can still be removed.
 */

import { useState } from "react";
import { useTranslation } from "react-i18next";

import {
  clearCommunityBanner,
  clearCommunityIcon,
  setCommunityBanner,
  setCommunityIcon,
  updateCommunity,
  useReadCommunityEntitlements,
} from "@/api/generated/communities/communities";
import {
  BannerFade,
  BannerTextAlign,
  type CommunityBannerRead,
  type CommunityBannerWrite,
  type CommunityRead,
} from "@/api/generated/initiativeAPI.schemas";
import { useApiMutation } from "@/hooks/useApiMutation";
import { useCommunities } from "@/hooks/useCommunities";
import { renderableBanner } from "@/lib/banner";
import { DARK_TEXT, LIGHT_TEXT, readableTextColor, readableTextShadow } from "@/lib/contrastColor";
import { getErrorMessage } from "@/lib/errorMessage";
import {
  ImageRenditionError,
  renderCommunityBanner,
  renderCommunityIcon,
} from "@/lib/imageRenditions";
import { toast } from "@/lib/mascotToast";
import { resolveHeaderlessApiUrl } from "@/lib/uploadUrl";
import { Button } from "@/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/ui/card";
import { ColorPickerPopover } from "@/ui/color-picker-popover";
import { Field } from "@/ui/field";
import { ImagePicker } from "@/ui/image-picker";
import { Label } from "@/ui/label";

/**
 * How much of the preview each fade eats, as a share of its height.
 *
 * The real banner fades over a fixed distance measured up from its bottom
 * edge, which is what keeps a short colour band and a tall photograph both
 * looking right. A 4:1 preview is neither of those heights, so this shows the
 * *impression* of each setting rather than its exact geometry — enough to
 * choose between them, which is what a preview is for.
 */
const PREVIEW_FADE: Record<CommunityBannerRead["fade"], string | undefined> = {
  none: undefined,
  weak: "linear-gradient(to bottom, #000 65%, transparent 100%)",
  strong: "linear-gradient(to bottom, #000 15%, transparent 100%)",
};

export const CommunityArtworkPanel = ({ community }: { community: CommunityRead }) => {
  const { t } = useTranslation(["communities", "common"]);
  const { refreshCommunities, updateCommunityInState } = useCommunities();
  /** Every write here answers with the whole community, so state is replaced, not patched. */
  const save = useApiMutation(
    {
      mutationFn: async (write: () => Promise<CommunityRead>) => {
        updateCommunityInState(await write());
        await refreshCommunities();
      },
    },
    {
      onSuccess: () => toast.success(t("communities:settings.artwork.saved")),
      // A picture the browser could not make sense of never reached the
      // server, so it has its own message rather than an API code.
      onError: (error) =>
        toast.error(
          error instanceof ImageRenditionError
            ? t(`communities:settings.artwork.${error.code}`)
            : getErrorMessage(error, "communities:settings.artwork.failed")
        ),
    }
  );
  // The banner as this panel is showing it, which is what the pickers below
  // draft against and what a save sends — the whole of it, since the endpoint
  // replaces the banner rather than merging into it.
  const [draft, setDraft] = useState(community.banner);
  // Only an admin reaches this panel, which is who may read this. Until the
  // answer lands, assume artwork is on offer: it is the ordinary case, and the
  // server is what actually decides.
  const entitlements = useReadCommunityEntitlements(community.id);
  const mayUploadBanner = entitlements.data?.banner_image_enabled ?? true;

  const [prevBanner, setPrevBanner] = useState(community.banner);
  if (prevBanner !== community.banner) {
    setPrevBanner(community.banner);
    setDraft(community.banner);
  }

  /** Show a change, without writing it — for a picker still being dragged. */
  const draftLook = (change: Partial<CommunityBannerWrite>) =>
    setDraft((current) => ({ ...current, ...change }));

  /**
   * Show a change and save it. Everything here saves the moment it is picked —
   * there is nothing to confirm about a look the preview above is already
   * showing — and every save sends the whole banner, since that is what it is.
   *
   * `null` is the reset: the server puts the whole default back rather than
   * clearing anything, because a banner is never colourless and never without
   * a layout.
   */
  const commitLook = (change: Partial<CommunityBannerWrite> | null) => {
    const banner = change && { ...draft, ...change };
    if (banner) setDraft(banner);
    save.mutate(() =>
      // The endpoint answers with the whole community; the cast is the generated
      // client's, which types a PATCH body as unknown.
      updateCommunity(community.id, {
        banner,
      } as Parameters<typeof updateCommunity>[1])
    );
  };

  // Picking a fill moves the text with it. Not a lock — the control stays
  // editable, and over artwork the fill is not what the words sit on anyway —
  // but it means the common case is right without anyone thinking about it.
  const withReadableText = (color: string) => ({
    color,
    text_color: readableTextColor(color),
  });

  const pickIcon = (file: File) => {
    save.mutate(async () =>
      setCommunityIcon(community.id, { icon: await renderCommunityIcon(file) })
    );
  };

  const pickBanner = (file: File) => {
    save.mutate(async () => setCommunityBanner(community.id, await renderCommunityBanner(file)));
  };

  const iconUrl = community.icon_url ? resolveHeaderlessApiUrl(community.icon_url) : null;
  const bannerUrl = renderableBanner(community.banner).image_url;

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("communities:settings.artwork.title")}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-6">
        <div className="space-y-2">
          <Label htmlFor="community-icon">{t("communities:settings.iconLabel")}</Label>
          <div className="flex items-center gap-4">
            {iconUrl ? (
              <img
                src={iconUrl}
                alt={t("communities:settings.iconPreviewAlt")}
                className="h-16 w-16 rounded-lg border object-cover"
              />
            ) : (
              <div className="flex h-16 w-16 items-center justify-center rounded-lg border border-dashed text-muted-foreground text-xs">
                {t("communities:settings.artwork.none")}
              </div>
            )}
            {iconUrl ? (
              <Button
                type="button"
                variant="outline"
                disabled={save.isPending}
                onClick={() => save.mutate(() => clearCommunityIcon(community.id))}
              >
                {t("communities:settings.removeIcon")}
              </Button>
            ) : null}
          </div>
          <ImagePicker
            id="community-icon"
            accept="image/*"
            disabled={save.isPending}
            onSelect={pickIcon}
          />
          <p className="text-muted-foreground text-sm">
            {t("communities:settings.artwork.iconHint")}
          </p>
        </div>

        <div className="space-y-2">
          <Label htmlFor="community-banner">{t("communities:settings.artwork.bannerLabel")}</Label>
          {/* The banner as it will be: the artwork over the fill that shows
              without it, with the community's name in the text colour on top. It
              reads from the draft colours below, so the pickers answer here
              rather than somewhere else on the page. */}
          <div
            className={`relative flex aspect-[4/1] w-full items-center overflow-hidden rounded-lg border ${
              draft.text_align === BannerTextAlign.left ? "justify-start" : "justify-center"
            }`}
          >
            {/* The ground and the fade on it, under the name rather than over
                it — the same arrangement the real banner uses, so what the
                fade does to the picture is visible and what it does to the
                words (nothing) is too. */}
            <div
              className="absolute inset-0"
              style={{
                backgroundColor: draft.color,
                maskImage: PREVIEW_FADE[draft.fade],
                WebkitMaskImage: PREVIEW_FADE[draft.fade],
              }}
            >
              {bannerUrl ? (
                <img
                  src={bannerUrl}
                  alt={t("communities:settings.artwork.bannerPreviewAlt")}
                  className="h-full w-full object-cover"
                />
              ) : null}
            </div>
            <span
              className="relative truncate px-4 font-black text-lg sm:text-2xl"
              style={{ color: draft.text_color, textShadow: readableTextShadow(draft.text_color) }}
            >
              {community.name}
            </span>
          </div>
          {mayUploadBanner ? (
            <>
              <ImagePicker
                id="community-banner"
                accept="image/*"
                disabled={save.isPending}
                onSelect={pickBanner}
              />
              <p className="text-muted-foreground text-sm">
                {t("communities:settings.artwork.bannerHint")}
              </p>
            </>
          ) : (
            <p className="text-muted-foreground text-sm">
              {t("communities:settings.artwork.bannerColorOnly")}
            </p>
          )}
          {bannerUrl ? (
            <Button
              type="button"
              variant="outline"
              disabled={save.isPending}
              onClick={() => save.mutate(() => clearCommunityBanner(community.id))}
            >
              {t("communities:settings.artwork.removeBanner")}
            </Button>
          ) : null}
        </div>

        <div className="space-y-2">
          <div className="flex flex-wrap items-end gap-6">
            <Field label={t("communities:settings.artwork.bannerColorLabel")}>
              <ColorPickerPopover
                value={draft.color}
                disabled={save.isPending}
                onChange={(next) => draftLook(withReadableText(next))}
                onChangeComplete={(next) => commitLook(withReadableText(next))}
                triggerLabel={t("communities:settings.artwork.bannerColorLabel")}
              />
            </Field>
            <fieldset className="space-y-2" disabled={save.isPending}>
              <legend className="pb-2 font-medium text-sm">
                {t("communities:settings.artwork.bannerTextColorLabel")}
              </legend>
              <div className="flex gap-2">
                {[
                  { value: LIGHT_TEXT, label: t("communities:settings.artwork.textLight") },
                  { value: DARK_TEXT, label: t("communities:settings.artwork.textDark") },
                ].map((option) => (
                  <Button
                    key={option.value}
                    type="button"
                    size="sm"
                    variant={draft.text_color === option.value ? "default" : "outline"}
                    aria-pressed={draft.text_color === option.value}
                    onClick={() => commitLook({ text_color: option.value })}
                  >
                    {option.label}
                  </Button>
                ))}
              </div>
            </fieldset>
            <fieldset className="space-y-2" disabled={save.isPending}>
              <legend className="pb-2 font-medium text-sm">
                {t("communities:settings.artwork.bannerAlignLabel")}
              </legend>
              <div className="flex gap-2">
                {[
                  {
                    value: BannerTextAlign.center,
                    label: t("communities:settings.artwork.alignCenter"),
                  },
                  {
                    value: BannerTextAlign.left,
                    label: t("communities:settings.artwork.alignLeft"),
                  },
                ].map((option) => (
                  <Button
                    key={option.value}
                    type="button"
                    size="sm"
                    variant={draft.text_align === option.value ? "default" : "outline"}
                    aria-pressed={draft.text_align === option.value}
                    onClick={() => commitLook({ text_align: option.value })}
                  >
                    {option.label}
                  </Button>
                ))}
              </div>
            </fieldset>
            <fieldset className="space-y-2" disabled={save.isPending}>
              <legend className="pb-2 font-medium text-sm">
                {t("communities:settings.artwork.bannerFadeLabel")}
              </legend>
              <div className="flex gap-2">
                {[
                  { value: BannerFade.none, label: t("communities:settings.artwork.fadeNone") },
                  { value: BannerFade.weak, label: t("communities:settings.artwork.fadeWeak") },
                  { value: BannerFade.strong, label: t("communities:settings.artwork.fadeStrong") },
                ].map((option) => (
                  <Button
                    key={option.value}
                    type="button"
                    size="sm"
                    variant={draft.fade === option.value ? "default" : "outline"}
                    aria-pressed={draft.fade === option.value}
                    onClick={() => commitLook({ fade: option.value })}
                  >
                    {option.label}
                  </Button>
                ))}
              </div>
            </fieldset>
          </div>
          <p className="text-muted-foreground text-sm">
            {t("communities:settings.artwork.bannerFadeHint")}
          </p>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            disabled={save.isPending}
            onClick={() => commitLook(null)}
          >
            {t("communities:settings.artwork.resetColor")}
          </Button>
          <p className="text-muted-foreground text-sm">
            {t("communities:settings.artwork.bannerColorHint")}
          </p>
        </div>
      </CardContent>
    </Card>
  );
};
