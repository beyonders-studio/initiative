import { useRouter } from "@tanstack/react-router";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { ProjectPickerStep } from "@/components/tasks/ProjectPickerStep";
import { useCommunityInitiativeSteps } from "@/hooks/useCommunityInitiativeSteps";
import { communityPath } from "@/lib/communityUrl";
import { getItem, removeItem, setItem } from "@/lib/storage";
import { toolDetailRoute } from "@/lib/tools";
import { WizardDialog } from "@/ui/wizard-dialog";

// ── Module-level opener (same pattern as CommandCenter) ─────────────────────

let openCreateTaskWizard: (() => void) | null = null;

export function getOpenCreateTaskWizard() {
  return openCreateTaskWizard;
}

// ── Storage ─────────────────────────────────────────────────────────────────

const STORAGE_KEY = "initiative-last-task-project";

interface LastUsedProject {
  // Stored on the device under these names, so a saved shortcut still reads.
  guildId: number;
  guildName: string;
  initiativeId: number;
  initiativeName: string;
  projectId: number;
  projectName: string;
}

function loadLastUsed(): LastUsedProject | null {
  try {
    const raw = getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as LastUsedProject;
    if (parsed.guildId && parsed.projectId) return parsed;
    return null;
  } catch {
    return null;
  }
}

/**
 * Clear the stored "last used" project if it matches the given projectId.
 * Call this from error pages (404/403) to prevent stale shortcuts.
 */
export function clearLastUsedProject(projectId: number) {
  const stored = loadLastUsed();
  if (stored && stored.projectId === projectId) {
    removeItem(STORAGE_KEY);
  }
}

// ── Component ───────────────────────────────────────────────────────────────

export const CreateTaskWizard = () => {
  const { t } = useTranslation("tasks");
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const lastUsed = useMemo(() => (open ? loadLastUsed() : null), [open]);

  // Register module-level opener
  useEffect(() => {
    openCreateTaskWizard = () => setOpen(true);
    return () => {
      openCreateTaskWizard = null;
    };
  }, []);

  const navigateToProject = useCallback(
    (target: LastUsedProject) => {
      setItem(STORAGE_KEY, JSON.stringify(target));
      setOpen(false);
      void router.navigate({
        to: communityPath(
          target.guildId,
          toolDetailRoute(Tool.project, target.initiativeId, target.projectId)
        ),
        search: { create: "true" },
      });
    },
    [router]
  );

  // A task is child content of a project, so the community and initiative steps
  // offer wherever content can be written; the project step then applies the
  // precise per-project check.
  const steps = useCommunityInitiativeSteps({
    ns: "tasks",
    open,
    authors: null,
    shortcut: lastUsed && {
      title: lastUsed.projectName,
      subtitle: `${lastUsed.guildName} > ${lastUsed.initiativeName}`,
      onClick: () => navigateToProject(lastUsed),
    },
    next: { step: "select-project", description: t("createWizard.selectProject") },
  });
  const { community, initiative } = steps;

  return (
    <WizardDialog open={open} onOpenChange={setOpen} className="sm:max-w-md" {...steps.dialog}>
      {steps.body}

      {steps.step === "select-project" && community && initiative && (
        <ProjectPickerStep
          communityId={community.id}
          initiativeId={initiative.id}
          onPick={(project) =>
            navigateToProject({
              guildId: community.id,
              guildName: community.name,
              initiativeId: initiative.id,
              initiativeName: initiative.name,
              projectId: project.id,
              projectName: project.name,
            })
          }
        />
      )}
    </WizardDialog>
  );
};
