/**
 * The community-directory opt-in, on the community settings page.
 *
 * Community admins only — the API refuses these fields from anyone else, and the
 * whole settings section is admin-gated — so the panel is simply absent for a
 * member rather than shown disabled. Absent too where the platform owner runs
 * no directory: there would be nothing to list in.
 *
 * Saved on its own rather than folded into the details form above: listing a
 * community publishes it to everyone signed in, which is a different decision from
 * renaming it, and the PATCH treats omitted fields as untouched so the two
 * never overwrite each other.
 *
 * Three conditions gate a listing, and the server enforces all three (two of
 * them as database CHECKs). What the UI adds is that they are asked *before*
 * the request rather than reported after it: the publish dialog collects the
 * categories and the content certification together, and a community whose seat
 * limit leaves no room to join is told so instead of being offered a toggle
 * that can only fail.
 *
 * The 18+ question is asked there and nowhere else. It is a directory question,
 * so a community that keeps to itself never sees it; the certification in the
 * dialog is what answers it, at the moment it starts to matter.
 */

import { useState } from "react";
import { useTranslation } from "react-i18next";

import { updateCommunity } from "@/api/generated/communities/communities";
import {
  type CommunityCategory,
  type CommunityRead,
  SupportTopic,
} from "@/api/generated/initiativeAPI.schemas";
import { HelpLink } from "@/components/support/HelpLink";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { useAppConfig } from "@/hooks/useAppConfig";
import { useCommunities } from "@/hooks/useCommunities";
import { COMMUNITY_CATEGORIES, communityCategoryLabel } from "@/lib/communityCategories";
import { getErrorMessage } from "@/lib/errorMessage";
import { cn } from "@/lib/utils";

import { CommunityAutoJoinPrompt } from "./CommunityAutoJoinPrompt";
import { PublishCommunityDialog } from "./PublishCommunityDialog";

/** A community with one seat can never admit a joiner, so it is never listed.
 *  Mirrors MIN_COMMUNITY_SEATS on the server, which is what enforces it. */
const MIN_COMMUNITY_SEATS = 2;

export const CommunityDiscoveryPanel = () => {
  const { t } = useTranslation(["communities", "common"]);
  const { activeCommunity, refreshCommunities, updateCommunityInState } = useCommunities();
  const { communityDirectoryEnabled } = useAppConfig();
  const [publishing, setPublishing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [prevCommunity, setPrevCommunity] = useState(activeCommunity);
  if (prevCommunity !== activeCommunity) {
    setPrevCommunity(activeCommunity);
    setMessage(null);
    setError(null);
  }

  if (!communityDirectoryEnabled || !activeCommunity?.can.administer) {
    return null;
  }

  const listed = activeCommunity.is_community;
  // null is unlimited. Only an operator sets this, so an admin who hits it is
  // told who to ask rather than offered a control they cannot satisfy.
  const seatLimited =
    activeCommunity.max_users != null && activeCommunity.max_users < MIN_COMMUNITY_SEATS;

  const save = async (updates: Partial<CommunityRead>) => {
    setSaving(true);
    setError(null);
    setMessage(null);
    try {
      const result = (await updateCommunity(
        activeCommunity.id,
        updates as Parameters<typeof updateCommunity>[1]
      )) as unknown as CommunityRead;
      updateCommunityInState(result);
      await refreshCommunities();
      setMessage(t("communities:settings.updatedSuccessfully"));
      return true;
    } catch (err) {
      console.error(err);
      setError(getErrorMessage(err, "communities:settings.unableToUpdate"));
      return false;
    } finally {
      setSaving(false);
    }
  };

  // Listing is a publication, so it goes through the dialog that collects the
  // categories and the certification. Un-listing publishes nothing and asks
  // nothing — it takes effect on the click.
  const handleToggle = (next: boolean) => {
    if (next) {
      setPublishing(true);
      return;
    }
    void save({ is_community: false });
  };

  const toggleCategory = (category: CommunityCategory) => {
    const next = activeCommunity.categories.includes(category)
      ? activeCommunity.categories.filter((value) => value !== category)
      : [...activeCommunity.categories, category];
    void save({ categories: next });
  };

  return (
    <>
      <Card>
        <CardHeader>
          <CardTitle>{t("communities:settings.discoveryTitle")}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-muted-foreground text-sm">
            {t("communities:settings.discoveryDescription")}
          </p>

          <div className="flex items-center gap-3">
            <Switch
              id="community-is-community"
              checked={listed}
              disabled={saving || (!listed && seatLimited)}
              onCheckedChange={handleToggle}
            />
            <Label htmlFor="community-is-community">
              {t("communities:settings.discoveryToggleLabel")}
            </Label>
          </div>

          {/* Why the toggle is unavailable, rather than an inert control. */}
          {!listed && seatLimited ? (
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
              <p className="text-muted-foreground text-sm">
                {t("communities:settings.discoveryCapacityBlocked")}
              </p>
              <HelpLink topic={SupportTopic.community} communityId={activeCommunity.id} />
            </div>
          ) : null}

          {/* A listing is a front door; this is about the room behind it. Shown
              only while the community is listed, and only until it has one. */}
          {listed ? <CommunityAutoJoinPrompt /> : null}

          {/* The shelves only matter once the community is on one. They are editable
              here afterwards; the dialog is only for the first publication. */}
          {listed ? (
            <fieldset className="space-y-2">
              <legend className="font-medium text-sm">
                {t("communities:settings.discoveryCategoriesLabel")}
              </legend>
              <p className="text-muted-foreground text-sm">
                {t("communities:settings.discoveryCategoriesHint")}
              </p>
              <div className="flex flex-wrap gap-2 pt-1">
                {COMMUNITY_CATEGORIES.map((category) => {
                  const selected = activeCommunity.categories.includes(category);
                  return (
                    <button
                      key={category}
                      type="button"
                      onClick={() => toggleCategory(category)}
                      aria-pressed={selected}
                      disabled={saving}
                      className={cn(
                        "rounded-full border px-3 py-1 text-sm transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50",
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
          ) : null}

          {error ? <p className="text-destructive text-sm">{error}</p> : null}
          {message ? <p className="text-primary text-sm">{message}</p> : null}
        </CardContent>
      </Card>

      <PublishCommunityDialog
        open={publishing}
        saving={saving}
        initialCategories={activeCommunity.categories}
        onCancel={() => setPublishing(false)}
        onConfirm={async (categories) => {
          const ok = await save({
            is_community: true,
            categories,
            // Ticking the certification is what answers the 18+ question — the
            // only path to "no", from unanswered or from a previous "yes".
            has_adult_content: false,
          });
          if (ok) setPublishing(false);
        }}
      />
    </>
  );
};
