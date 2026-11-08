/**
 * Adding a plug-in to the community, with the seat's consent.
 *
 * A plug-in belongs to the community, so there is no initiative to choose for it the
 * way there is for a dashboard. What the seat does choose is on this one
 * screen, and is confirmed once:
 *
 * 1. **What it can reach.** Each scope the plug-in asks for, as a plain sentence.
 *    Everything this server allows starts ticked, except a standing (acting as
 *    a moderator or an admin), which the seat ticks itself; a scope it does
 *    not allow is shown disabled, with the reason.
 * 2. **Where it appears.** Only for a plug-in with a page inside initiatives, or
 *    fields, sections or actions on items: every current initiative, or the
 *    ones picked here.
 * 3. **Who can open it there.** Built-in roles, moderators by default, applied
 *    to every initiative it is placed in.
 * 4. **Which plug-ins can use it.** The ones already here that ask to, all
 *    ticked to start. A plug-in is never asked about using one the community
 *    does not have, so this is where that question comes up.
 *
 * The server installs, grants and places in one transaction, under the same
 * checks the plug-in's settings apply afterwards.
 *
 * Community admins only. The server enforces that; this hides the action rather
 * than offering one that would be refused.
 */

import { useNavigate } from "@tanstack/react-router";
import { Download } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { MarketplaceListingDetail } from "@/api/generated/initiativeAPI.schemas";
import { ListingProvenance } from "@/components/marketplace/ListingProvenance";
import { useInstallCommunityPlugin } from "@/hooks/useCommunityPlugins";
import { useCommunityInitiatives } from "@/hooks/useInitiatives";
import { useCommunityPath } from "@/lib/communityUrl";
import { getErrorMessage } from "@/lib/errorMessage";
import { listingShownHere } from "@/lib/marketplaceCuration";
import { toast } from "@/lib/mascotToast";
import { STANDING_SCOPES, scopeSentence, toggleScope } from "@/lib/pluginScopes";
import { communityPluginPath, declaredPages } from "@/lib/pluginSurfaces";
import type { DialogProps } from "@/types/dialog";
import { Checkbox } from "@/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/ui/dialog";
import { Field } from "@/ui/field";
import { Input } from "@/ui/input";
import { Label } from "@/ui/label";
import { SkeletonLines, SkeletonRegion } from "@/ui/page-skeletons";
import { RadioGroup, RadioGroupItem } from "@/ui/radio-group";

export interface InstallPluginDialogProps extends DialogProps {
  listing: MarketplaceListingDetail;
}

/** The built-in initiative roles the seat may let open the plug-in. */
export const ROLE_KINDS = ["moderator", "project_manager", "member"] as const;
type RoleKind = (typeof ROLE_KINDS)[number];

export function InstallPluginDialog({ listing, open, onOpenChange }: InstallPluginDialogProps) {
  const { t } = useTranslation(["plugins", "common", "nav"]);
  const navigate = useNavigate();
  const gp = useCommunityPath();

  const requested = listing.requested_scopes ?? [];
  const grantable = new Set(listing.grantable_scopes ?? []);
  // A page inside initiatives, or fields, sections or actions on items: the
  // roles chosen here say who opens the page and who is drawn the rest.
  const placesInInitiatives = listing.has_initiative_surfaces ?? false;
  const hasPage = declaredPages(listing.definition, "initiative").length > 0;
  // A plug-in reaches content only in the initiatives it is placed in, so one
  // that asks for any access is placed too, whether or not it has a page.
  const placeable = placesInInitiatives || requested.length > 0;

  const [name, setName] = useState(listing.name);
  // Every scope the server allows starts ticked, bar a standing; the seat
  // unticks, and ticks a standing itself.
  const [scopes, setScopes] = useState<string[]>(() =>
    requested.filter((scope) => grantable.has(scope) && !STANDING_SCOPES.has(scope))
  );
  const [where, setWhere] = useState<"all" | "some">("all");
  const [picked, setPicked] = useState<number[]>([]);
  const [roles, setRoles] = useState<RoleKind[]>(["moderator"]);
  const callers = listing.callers ?? [];
  const [allowedCallers, setAllowedCallers] = useState<number[]>(() =>
    callers.map((caller) => caller.id)
  );
  const install = useInstallCommunityPlugin();

  const submit = () =>
    install.mutate(
      {
        listing_uid: listing.uid,
        name: name.trim() || listing.name,
        granted_scopes: scopes,
        placements: !placeable ? [] : where === "all" ? "all" : picked,
        role_kinds: placesInInitiatives ? roles : [],
        callers: allowedCallers,
      },
      {
        onSuccess: (plugin) => {
          toast.success(t("plugins:install.done", { name: plugin.name }));
          onOpenChange(false);
          // Straight to what it created, when it created something reachable.
          const path = communityPluginPath(plugin);
          if (path) navigate({ to: gp(path) });
        },
        onError: (error) => {
          toast.error(getErrorMessage(error, "plugins:error"));
        },
      }
    );

  const toggleRole = (role: RoleKind, on: boolean) =>
    setRoles((current) =>
      on ? [...new Set([...current, role])] : current.filter((one) => one !== role)
    );

  // Only the catalogue this app shows can be installed from it.
  if (!listingShownHere(listing)) return null;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("plugins:install.title", { name: listing.name })}</DialogTitle>
          <DialogDescription>{t("plugins:install.description")}</DialogDescription>
        </DialogHeader>

        {/* A plug-in reaches the whole community, so who wrote it is said here too —
            the same sentence the card and the listing page showed. */}
        <ListingProvenance listing={listing} />

        <Field label={t("plugins:install.name")} className="space-y-1.5">
          <Input
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder={listing.name}
          />
        </Field>

        {requested.length > 0 && (
          <section className="space-y-2" aria-labelledby="install-plugin-reach">
            <h3 id="install-plugin-reach" className="font-medium text-sm">
              {t("plugins:install.reachTitle")}
            </h3>
            <ul className="space-y-2">
              {requested.map((scope) => {
                const allowed = grantable.has(scope);
                const id = `install-scope-${scope.replace(":", "-")}`;
                return (
                  <li key={scope} className="flex items-start gap-2">
                    <Checkbox
                      id={id}
                      checked={scopes.includes(scope)}
                      disabled={!allowed || install.isPending}
                      onCheckedChange={(state) =>
                        setScopes((current) =>
                          toggleScope(current, scope, state === true, grantable)
                        )
                      }
                    />
                    <div className="space-y-0.5">
                      <Label htmlFor={id} className="font-normal">
                        {scopeSentence(scope, t, listing.plugin_names)}
                      </Label>
                      {!allowed && (
                        <p className="text-muted-foreground text-xs">
                          {t("plugins:scopes.notAllowed")}
                        </p>
                      )}
                    </div>
                  </li>
                );
              })}
            </ul>
          </section>
        )}

        {placeable && (
          <section className="space-y-2" aria-labelledby="install-plugin-where">
            <div>
              <h3 id="install-plugin-where" className="font-medium text-sm">
                {t("plugins:install.whereTitle")}
              </h3>
              <p className="text-muted-foreground text-xs">
                {t(
                  hasPage
                    ? "plugins:install.whereDescription"
                    : "plugins:install.whereDescriptionNoPage"
                )}
              </p>
            </div>
            <RadioGroup
              value={where}
              onValueChange={(value) => setWhere(value === "some" ? "some" : "all")}
              className="space-y-2"
            >
              <div className="flex items-center gap-2">
                <RadioGroupItem value="all" id="install-plugin-where-all" />
                <Label htmlFor="install-plugin-where-all" className="font-normal">
                  {t("plugins:placement.all")}
                </Label>
              </div>
              <div className="flex items-center gap-2">
                <RadioGroupItem value="some" id="install-plugin-where-some" />
                <Label htmlFor="install-plugin-where-some" className="font-normal">
                  {t("plugins:placement.some")}
                </Label>
              </div>
            </RadioGroup>
            {where === "some" && <InitiativePicker picked={picked} onChange={setPicked} />}
          </section>
        )}

        {placesInInitiatives && (
          <section className="space-y-2" aria-labelledby="install-plugin-who">
            <div>
              <h3 id="install-plugin-who" className="font-medium text-sm">
                {t("plugins:install.whoTitle")}
              </h3>
              <p className="text-muted-foreground text-xs">
                {t("plugins:placement.roles.adminsAlways")}
              </p>
            </div>
            <div className="space-y-2">
              {ROLE_KINDS.map((role) => (
                <div key={role} className="flex items-center gap-2">
                  <Checkbox
                    id={`install-plugin-role-${role}`}
                    checked={roles.includes(role)}
                    disabled={install.isPending}
                    onCheckedChange={(state) => toggleRole(role, state === true)}
                  />
                  <Label htmlFor={`install-plugin-role-${role}`} className="font-normal">
                    {t(`plugins:install.roles.${role}` as never)}
                  </Label>
                </div>
              ))}
            </div>
          </section>
        )}

        {callers.length > 0 && (
          <section className="space-y-2" aria-labelledby="install-plugin-callers">
            <div>
              <h3 id="install-plugin-callers" className="font-medium text-sm">
                {t("plugins:install.callersTitle")}
              </h3>
              <p className="text-muted-foreground text-xs">
                {t("plugins:install.callersDescription", { name: listing.name })}
              </p>
            </div>
            <div className="space-y-2">
              {callers.map((caller) => (
                <div key={caller.id} className="flex items-center gap-2">
                  <Checkbox
                    id={`install-plugin-caller-${caller.id}`}
                    checked={allowedCallers.includes(caller.id)}
                    disabled={install.isPending}
                    onCheckedChange={(state) =>
                      setAllowedCallers((current) =>
                        state === true
                          ? [...new Set([...current, caller.id])]
                          : current.filter((one) => one !== caller.id)
                      )
                    }
                  />
                  <Label htmlFor={`install-plugin-caller-${caller.id}`} className="font-normal">
                    {caller.name}
                  </Label>
                </div>
              ))}
            </div>
          </section>
        )}

        <DialogFooter
          submitLabel={
            <>
              <Download className="h-4 w-4" />
              {t("plugins:install.action")}
            </>
          }
          onSubmit={submit}
          pending={install.isPending}
        />
      </DialogContent>
    </Dialog>
  );
}

/** The community's initiatives, ticked one by one. Loaded only once asked for. */
function InitiativePicker({
  picked,
  onChange,
}: {
  picked: number[];
  onChange: (next: number[]) => void;
}) {
  const { t } = useTranslation(["plugins", "common"]);
  const initiatives = useCommunityInitiatives();

  if (initiatives.isLoading) {
    return (
      <SkeletonRegion className="border-l pl-4">
        <SkeletonLines lines={3} />
      </SkeletonRegion>
    );
  }

  return (
    <div className="space-y-2 border-l pl-4">
      {(initiatives.data ?? []).map((initiative) => (
        <div key={initiative.id} className="flex items-center gap-2">
          <Checkbox
            id={`install-plugin-initiative-${initiative.id}`}
            checked={picked.includes(initiative.id)}
            onCheckedChange={(state) =>
              onChange(
                state === true
                  ? [...new Set([...picked, initiative.id])]
                  : picked.filter((one) => one !== initiative.id)
              )
            }
          />
          <Label htmlFor={`install-plugin-initiative-${initiative.id}`} className="font-normal">
            {initiative.name}
          </Label>
        </div>
      ))}
      {picked.length === 0 && (
        <p className="text-muted-foreground text-sm">{t("plugins:placement.none")}</p>
      )}
    </div>
  );
}
