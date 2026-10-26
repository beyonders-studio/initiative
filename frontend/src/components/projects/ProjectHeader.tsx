import { CalendarRange } from "lucide-react";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import { type ProjectRead, Tool } from "@/api/generated/initiativeAPI.schemas";
import { CatchUpButton } from "@/components/activity/CatchUpButton";
import { Markdown } from "@/components/Markdown";
import { ToolChest, ToolChestSegment } from "@/components/tools/ToolChest";
import { ToolPageHeader } from "@/components/tools/ToolPageHeader";
import { Progress } from "@/components/ui/progress";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { useAuth } from "@/hooks/useAuth";
import { useLastVisit } from "@/hooks/useLastVisit";
import { useUpdateProject } from "@/hooks/useProjects";
import { activityLastVisitKey } from "@/lib/activityLastVisit";
import { formatDate } from "@/lib/formatDate";
import { toolSettingsRoute } from "@/lib/tools";

type ProjectHeaderProps = {
  project: ProjectRead;
  projectIsArchived: boolean;
};

export const ProjectHeader = ({ project, projectIsArchived }: ProjectHeaderProps) => {
  const { t } = useTranslation(["projects", "common"]);
  const updateProject = useUpdateProject(project.id);
  const canEdit = project.can.edit;
  const { user } = useAuth();
  const communityId = useActiveCommunityId();
  const lastVisit = useLastVisit(
    user ? activityLastVisitKey(user.id, communityId, `project:${project.id}`) : null
  );

  // Dates are optional and independent. With neither set the header shows
  // nothing at all — an empty schedule is not worth a line of its own.
  const scheduleLabel = useMemo(() => {
    const start = formatDate(project.start_date);
    const end = formatDate(project.end_date);
    if (start && end) {
      return t("overview.scheduleRange", { start, end });
    }
    if (start) {
      return t("overview.scheduleStartOnly", { start });
    }
    if (end) {
      return t("overview.scheduleEndOnly", { end });
    }
    return null;
  }, [project.start_date, project.end_date, t]);

  return (
    <ToolPageHeader
      tool={Tool.project}
      initiativeId={project.initiative_id}
      starId={project.id}
      settingsTo={
        canEdit ? toolSettingsRoute(Tool.project, project.initiative_id, project.id) : undefined
      }
      mark={project.icon ? <span className="text-3xl leading-none">{project.icon}</span> : null}
      title={project.name}
      titleExtras={
        <CatchUpButton
          // Another project's answer is not this one's.
          key={`${project.community_id}:${project.id}`}
          since={lastVisit}
          scope={{ tool: Tool.project, toolId: project.id }}
        />
      }
      onRename={
        canEdit && !projectIsArchived ? (name) => updateProject.mutateAsync({ name }) : undefined
      }
      chest={
        <ToolChest
          tool={Tool.project}
          entity={project}
          template={{
            isTemplate: project.is_template,
            onChange: (isTemplate) => updateProject.mutateAsync({ is_template: isTemplate }),
          }}
        >
          <ToolChestSegment label={t("overview.progressLabel")}>
            <span className="tabular-nums">
              {t("overview.progress", {
                completed: project.task_summary.completed,
                total: project.task_summary.total,
              })}
            </span>
            <Progress
              value={
                project.task_summary.total
                  ? (project.task_summary.completed / project.task_summary.total) * 100
                  : 0
              }
              className="h-1.5 w-12"
              aria-hidden
            />
          </ToolChestSegment>
          <ToolChestSegment label={t("overview.datesLabel")}>
            <span className="inline-flex items-center gap-1.5">
              <CalendarRange className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
              {scheduleLabel ?? t("common:toolChest.none")}
            </span>
          </ToolChestSegment>
        </ToolChest>
      }
    >
      {project.is_template ? (
        <p className="rounded-md border border-muted/70 bg-muted/30 px-4 py-2 text-muted-foreground text-sm">
          {t("overview.templateInfo")}
        </p>
      ) : null}
      {project.description ? <Markdown content={project.description} /> : null}
      {projectIsArchived ? (
        <p className="rounded-md border border-destructive/40 bg-destructive/10 px-4 py-3 text-destructive text-sm">
          {t("overview.archivedInfo")}
        </p>
      ) : null}
    </ToolPageHeader>
  );
};
