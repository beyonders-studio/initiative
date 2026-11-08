import { useParams } from "@tanstack/react-router";

import { PluginPage } from "./PluginPage";

/** Reads the install id off the route so the page itself takes a plain prop. */
export function PluginRoute() {
  const { pluginId } = useParams({ strict: false }) as { pluginId?: string };
  const parsed = Number(pluginId);
  if (!Number.isFinite(parsed)) return null;
  return <PluginPage pluginId={parsed} />;
}

/**
 * The same install, read inside one initiative.
 *
 * Both ids come off the route. Which surfaces are on offer is the server's
 * answer for this reader in this initiative; the mint re-derives it under the
 * caller's own session.
 */
export function InitiativePluginRoute() {
  const { pluginId, initiativeId } = useParams({ strict: false }) as {
    pluginId?: string;
    initiativeId?: string;
  };
  const parsedPlugin = Number(pluginId);
  const parsedInitiative = Number(initiativeId);
  if (!Number.isFinite(parsedPlugin) || !Number.isFinite(parsedInitiative)) return null;

  return <PluginPage pluginId={parsedPlugin} initiativeId={parsedInitiative} />;
}
