import { useRouter } from "@tanstack/react-router";
import type { FlatNamespace } from "i18next";
import { useCallback, useEffect, useMemo, useState } from "react";

import type { Tool } from "@/api/generated/initiativeAPI.schemas";
import { type Choice, useCommunityInitiativeSteps } from "@/hooks/useCommunityInitiativeSteps";
import { communityPath } from "@/lib/communityUrl";
import { getItem, setItem } from "@/lib/storage";
import { TOOL_ICONS, toolCamelPlural, toolCreateTarget } from "@/lib/tools";
import { WizardDialog } from "@/ui/wizard-dialog";

// ── Module-level openers, one per mounted tool (same pattern as CreateTaskWizard)

const openers = new Map<Tool, () => void>();

export function getOpenCreateToolWizard(tool: Tool) {
  return openers.get(tool) ?? null;
}

// ── Storage ─────────────────────────────────────────────────────────────────

const storageKey = (tool: Tool) => `initiative-last-${tool}-initiative`;

interface LastUsedInitiative {
  // Stored on the device under these names, so a saved shortcut still reads.
  guildId: number;
  guildName: string;
  initiativeId: number;
  initiativeName: string;
}

function loadLastUsed(tool: Tool): LastUsedInitiative | null {
  try {
    const raw = getItem(storageKey(tool));
    if (!raw) return null;
    const parsed = JSON.parse(raw) as LastUsedInitiative;
    if (parsed.guildId && parsed.initiativeId) return parsed;
    return null;
  } catch {
    return null;
  }
}

// ── Component ───────────────────────────────────────────────────────────────

/**
 * Pick a community and an initiative, then hand over to the tool's own create
 * dialog. The tool's namespace holds the wizard's `createWizard.*` strings.
 */
export const CreateToolWizard = ({ tool }: { tool: Tool }) => {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const lastUsed = useMemo(() => (open ? loadLastUsed(tool) : null), [open, tool]);

  // Register module-level opener
  useEffect(() => {
    openers.set(tool, () => setOpen(true));
    return () => {
      openers.delete(tool);
    };
  }, [tool]);

  const handoff = useCallback(
    (community: Choice, initiative: Choice) => {
      setItem(
        storageKey(tool),
        JSON.stringify({
          guildId: community.id,
          guildName: community.name,
          initiativeId: initiative.id,
          initiativeName: initiative.name,
        } satisfies LastUsedInitiative)
      );
      setOpen(false);
      // The initiative's tool tab reads ?create=true and opens the tool's
      // existing create dialog, so the wizard hands off the rest of the flow
      // without re-mounting the creation UI.
      const target = toolCreateTarget(tool, initiative.id);
      void router.navigate({ to: communityPath(community.id, target.to), search: target.search });
    },
    [router, tool]
  );

  const Icon = TOOL_ICONS[tool];
  const steps = useCommunityInitiativeSteps({
    ns: toolCamelPlural(tool) as FlatNamespace,
    open,
    authors: tool,
    shortcut: lastUsed && {
      title: lastUsed.initiativeName,
      subtitle: lastUsed.guildName,
      onClick: () =>
        handoff(
          { id: lastUsed.guildId, name: lastUsed.guildName },
          { id: lastUsed.initiativeId, name: lastUsed.initiativeName }
        ),
    },
    onInitiative: handoff,
    initiativeIcon: <Icon className="ml-auto h-4 w-4 shrink-0 text-muted-foreground" />,
  });

  return (
    <WizardDialog open={open} onOpenChange={setOpen} className="sm:max-w-md" {...steps.dialog}>
      {steps.body}
    </WizardDialog>
  );
};
