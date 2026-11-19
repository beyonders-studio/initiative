/**
 * Where a plug-in's initiative surfaces appear.
 *
 * A plug-in appears in the initiatives it is placed in and no others. This is
 * where the seat places it — placement rather than permission, so it reads the
 * same for everyone afterwards, including the admin who set it. "Every current
 * initiative" places it in each initiative that exists now; one created later
 * is placed here like any other.
 *
 * Who uses it in an initiative is that initiative's roles' answer, so each
 * initiative it is placed in links to its Roles page.
 *
 * Absent for a plug-in with no initiative surface to place: there would be nothing
 * for the choice to move.
 */

import { Link } from "@tanstack/react-router";
import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import type { CommunityPluginDetail } from "@/api/generated/initiativeAPI.schemas";
import { useUpdateCommunityPlugin } from "@/hooks/useCommunityPlugins";
import { useCommunityInitiatives } from "@/hooks/useInitiatives";
import { useCommunityPath } from "@/lib/communityUrl";
import { declaredPages, hasInitiativeSurfaces } from "@/lib/pluginSurfaces";
import { initiativeRoute } from "@/lib/tools";
import { Button } from "@/ui/button";
import { Checkbox } from "@/ui/checkbox";
import { Label } from "@/ui/label";
import { SkeletonLines, SkeletonRegion } from "@/ui/page-skeletons";
import { RadioGroup, RadioGroupItem } from "@/ui/radio-group";

export interface PluginPlacementPanelProps {
  plugin: CommunityPluginDetail;
}

export function PluginPlacementPanel({ plugin }: PluginPlacementPanelProps) {
  const { t } = useTranslation(["plugins", "common"]);
  // Every initiative in the community, not the admin's own memberships. Placement
  // is what bounds the plug-in's reach — an automation fires only where its
  // install is placed — so "every current initiative" has to mean every one, and
  // an initiative the admin never joined is still one they place it in.
  const initiatives = useCommunityInitiatives();
  const update = useUpdateCommunityPlugin(plugin.id);
  // What the admin is choosing right now. Seeded from the plug-in and kept locally
  // so ticking several initiatives is one decision, saved per change.
  const [chosen, setChosen] = useState<number[]>(() => plugin.placed_initiative_ids);
  // Whether the admin asked to pick initiatives one by one. Until they do, an
  // plug-in placed in every initiative there is reads as "every current one".
  const [picking, setPicking] = useState(false);
  // The last selection the server took, so a failed save falls back to
  // something true rather than to whatever the cache happens to hold.
  const settled = useRef(chosen);
  // Each save replaces the whole selection, so two in flight could land in
  // either order and leave the older one stored. Chained rather than
  // concurrent: the server sees the ticks in the order they were made.
  const queue = useRef<Promise<unknown>>(Promise.resolve());
  // How many are still to settle. The panel is reconciled when the last one
  // does, rather than by each in turn — a save that failed behind a save that
  // worked would otherwise roll the panel back past a choice the server kept.
  const outstanding = useRef(0);

  const roster = initiatives.data ?? [];
  const hasPage = declaredPages(plugin.definition, "initiative").length > 0;
  // Roles decide who opens the plug-in's page and who is drawn its fields,
  // sections or actions on items, so a plug-in with any of those has them.
  const offersRoles = hasInitiativeSurfaces(plugin.definition);
  const placed = new Set(plugin.placed_initiative_ids);
  const everywhere = roster.length > 0 && roster.every((one) => chosen.includes(one.id));
  const mode = picking || !everywhere ? "some" : "all";

  const save = (next: number[]) => {
    setChosen(next);
    outstanding.current += 1;
    queue.current = queue.current
      .catch(() => undefined)
      .then(async () => {
        // Only initiatives still on the roster are sent. An initiative deleted
        // after it was chosen leaves an id nothing on screen shows, and
        // resubmitting it would fail every later edit for a reason the admin
        // cannot see.
        const live = !initiatives.data
          ? next
          : next.filter((id) => initiatives.data?.some((one) => one.id === id));
        await update.mutateAsync({ placed_initiative_ids: live });
        settled.current = live;
      })
      // The update says when it fails; the queue only has to carry on.
      .catch(() => undefined)
      .finally(() => {
        outstanding.current -= 1;
        // Nothing else is coming, so the panel now shows what the server took:
        // the newest choice when every save landed, and the last one it
        // accepted when any did not. Either way the next edit builds on what
        // is actually stored.
        if (outstanding.current === 0) setChosen(settled.current);
      });
  };

  const toggle = (id: number, on: boolean) => {
    // Ticking the last box keeps the list open rather than folding it into
    // "every current initiative" under the admin's cursor.
    setPicking(true);
    save(on ? [...chosen, id] : chosen.filter((one) => one !== id));
  };

  const choose = (value: string) => {
    if (value === "all") {
      setPicking(false);
      save(roster.map((one) => one.id));
    } else {
      // Nothing moves until a box is ticked: the current placements stay as
      // they are, shown ticked.
      setPicking(true);
    }
  };

  return (
    <section className="space-y-3">
      <div>
        <h3 className="font-medium text-sm">{t("plugins:placement.title")}</h3>
        <p className="text-muted-foreground text-sm">
          {t(hasPage ? "plugins:placement.description" : "plugins:placement.descriptionNoPage")}
        </p>
      </div>

      <RadioGroup value={mode} onValueChange={choose} className="space-y-2">
        <div className="flex items-center gap-2">
          <RadioGroupItem value="all" id={`placement-all-${plugin.id}`} />
          <Label htmlFor={`placement-all-${plugin.id}`} className="font-normal">
            {t("plugins:placement.all")}
          </Label>
        </div>
        <div className="flex items-center gap-2">
          <RadioGroupItem value="some" id={`placement-some-${plugin.id}`} />
          <Label htmlFor={`placement-some-${plugin.id}`} className="font-normal">
            {t("plugins:placement.some")}
          </Label>
        </div>
      </RadioGroup>

      {mode === "all" && offersRoles && placed.size > 0 && (
        <div className="space-y-2 border-l pl-4">
          {roster
            .filter((initiative) => placed.has(initiative.id))
            .map((initiative) => (
              <div key={initiative.id} className="flex items-center justify-between gap-2">
                <span className="text-sm">{initiative.name}</span>
                <RolesLink initiativeId={initiative.id} initiativeName={initiative.name} />
              </div>
            ))}
        </div>
      )}

      {mode === "some" && (
        <div className="space-y-2 border-l pl-4">
          {initiatives.isLoading ? (
            <SkeletonRegion>
              <SkeletonLines lines={3} />
            </SkeletonRegion>
          ) : (
            roster.map((initiative) => (
              <div key={initiative.id} className="flex items-center gap-2">
                <Checkbox
                  id={`placement-${plugin.id}-${initiative.id}`}
                  checked={chosen.includes(initiative.id)}
                  onCheckedChange={(state) => toggle(initiative.id, state === true)}
                />
                <Label
                  htmlFor={`placement-${plugin.id}-${initiative.id}`}
                  className="flex-1 font-normal"
                >
                  {initiative.name}
                </Label>
                {/* Only a placement the server holds has roles to set. */}
                {offersRoles && chosen.includes(initiative.id) && placed.has(initiative.id) && (
                  <RolesLink initiativeId={initiative.id} initiativeName={initiative.name} />
                )}
              </div>
            ))
          )}
          {chosen.length === 0 && (
            <p className="text-muted-foreground text-sm">{t("plugins:placement.none")}</p>
          )}
        </div>
      )}

      {offersRoles && (
        <p className="text-muted-foreground text-xs">{t("plugins:placement.roles.note")}</p>
      )}
    </section>
  );
}

/** The Roles page of one initiative the plug-in is placed in, where its roles
 *  are given the plug-in's permissions. */
function RolesLink({
  initiativeId,
  initiativeName,
}: {
  initiativeId: number;
  initiativeName: string;
}) {
  const { t } = useTranslation("plugins");
  const gp = useCommunityPath();
  return (
    <Button asChild size="sm" variant="ghost" className="h-7 px-2 text-muted-foreground text-xs">
      <Link
        to={gp(`${initiativeRoute(initiativeId)}/settings/roles`)}
        aria-label={t("placement.roles.open", { name: initiativeName })}
      >
        {t("placement.roles.link")}
      </Link>
    </Button>
  );
}
