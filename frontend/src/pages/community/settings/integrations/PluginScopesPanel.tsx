/**
 * What a plug-in can reach in the community.
 *
 * The plug-in's manifest lists the scopes it asks for, and the seat grants any of
 * them here. A requested scope this server does not allow is shown but cannot
 * be ticked. Changing something implies reading it, so granting a change
 * includes the read, and taking the read away takes the change with it.
 * Using another plug-in, and acting as a moderator or an admin, are each a row of
 * their own, said as a sentence: none of them is reading or changing a kind of
 * thing.
 *
 * Saved as one set: the server replaces the whole grant.
 */

import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { CommunityPluginDetail } from "@/api/generated/initiativeAPI.schemas";
import { useSetPluginScopes } from "@/hooks/useCommunityPlugins";
import { toast } from "@/lib/mascotToast";
import {
  pluginScopeTarget,
  type ScopeAccess,
  STANDING_SCOPES,
  scopeResourceLabel,
  scopeSentence,
  toggleScope,
} from "@/lib/pluginScopes";
import { Button } from "@/ui/button";
import { Checkbox } from "@/ui/checkbox";
import { Label } from "@/ui/label";

export interface PluginScopesPanelProps {
  plugin: CommunityPluginDetail;
}

type Access = ScopeAccess;

/** One resource the plug-in asks for, and which of its accesses. */
interface ResourceRow {
  resource: string;
  accesses: Access[];
}

const scopeOf = (resource: string, access: Access) => `${resource}:${access}`;

/** A scope said as a sentence on a row of its own rather than as an access to
 * a resource: using another plug-in, or acting as a moderator or an admin. */
const isSentenceScope = (scope: string) =>
  pluginScopeTarget(scope) !== null || STANDING_SCOPES.has(scope);

/** The requested scopes grouped by resource, keeping their order. */
const resourceRows = (requested: string[]): ResourceRow[] => {
  const rows: ResourceRow[] = [];
  for (const scope of requested) {
    if (isSentenceScope(scope)) continue;
    const [resource, access] = scope.split(":") as [string, Access];
    const row = rows.find((one) => one.resource === resource);
    if (row) row.accesses.push(access);
    else rows.push({ resource, accesses: [access] });
  }
  return rows;
};

/** The same set, regardless of order. */
const sameSet = (a: string[], b: string[]) =>
  a.length === b.length && a.every((one) => b.includes(one));

export function PluginScopesPanel({ plugin }: PluginScopesPanelProps) {
  const { t } = useTranslation(["plugins", "common", "nav"]);
  const setScopes = useSetPluginScopes(plugin.id);
  const requested = plugin.requested_scopes ?? [];
  const grantable = new Set(plugin.grantable_scopes ?? []);
  const granted = plugin.granted_scopes ?? [];
  // What the seat is choosing. Only grantable scopes are ever in it, so a
  // save is never refused for one the server no longer allows.
  const [chosen, setChosen] = useState<string[]>(() =>
    granted.filter((scope) => grantable.has(scope))
  );

  const resourceLabel = (resource: string): string => scopeResourceLabel(resource, t);

  const toggle = (resource: string, access: Access, on: boolean) =>
    setChosen(toggleScope(chosen, scopeOf(resource, access), on, grantable));

  const save = () =>
    setScopes.mutate(chosen, {
      onSuccess: (read) => {
        setChosen(read.granted_scopes);
        toast.success(t("plugins:scopes.saved"));
      },
    });

  const rows = resourceRows(requested);
  const sentenceScopes = requested.filter(isSentenceScope);

  return (
    <section className="space-y-3">
      <div>
        <h3 className="font-medium text-sm">{t("plugins:scopes.title")}</h3>
        <p className="text-muted-foreground text-sm">{t("plugins:scopes.description")}</p>
      </div>

      <ul className="divide-y rounded-md border">
        {rows.map((row) => (
          <li key={row.resource} className="flex flex-wrap items-center gap-x-4 gap-y-2 p-3">
            <span className="min-w-32 flex-1 font-medium text-sm">
              {resourceLabel(row.resource)}
            </span>
            {row.accesses.map((access) => {
              const scope = scopeOf(row.resource, access);
              const allowed = grantable.has(scope);
              const id = `scope-${plugin.id}-${row.resource}-${access}`;
              return (
                <div key={access} className="flex items-center gap-2">
                  <Checkbox
                    id={id}
                    checked={chosen.includes(scope)}
                    disabled={!allowed || setScopes.isPending}
                    onCheckedChange={(state) => toggle(row.resource, access, state === true)}
                  />
                  <Label htmlFor={id} className="font-normal">
                    {access === "read" ? t("plugins:scopes.read") : t("plugins:scopes.write")}
                  </Label>
                  {!allowed && (
                    <span className="text-muted-foreground text-xs">
                      {t("plugins:scopes.notAllowed")}
                    </span>
                  )}
                </div>
              );
            })}
          </li>
        ))}
        {sentenceScopes.map((scope) => {
          const allowed = grantable.has(scope);
          const id = `scope-${plugin.id}-${scope.replace(":", "-")}`;
          return (
            <li key={scope} className="flex flex-wrap items-center gap-2 p-3">
              <Checkbox
                id={id}
                checked={chosen.includes(scope)}
                disabled={!allowed || setScopes.isPending}
                onCheckedChange={(state) =>
                  setChosen(toggleScope(chosen, scope, state === true, grantable))
                }
              />
              <Label htmlFor={id} className="font-normal">
                {scopeSentence(scope, t, plugin.plugin_names)}
              </Label>
              {!allowed && (
                <span className="text-muted-foreground text-xs">
                  {t("plugins:scopes.notAllowed")}
                </span>
              )}
            </li>
          );
        })}
      </ul>

      <div className="flex justify-end">
        <Button
          size="sm"
          onClick={save}
          disabled={sameSet(chosen, granted)}
          pending={setScopes.isPending}
        >
          {t("common:save")}
        </Button>
      </div>
    </section>
  );
}
