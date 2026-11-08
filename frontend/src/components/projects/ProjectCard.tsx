import { Link } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";

import { type ProjectRead, Tool } from "@/api/generated/initiativeAPI.schemas";
import { BookmarkButton } from "@/components/BookmarkButton";
import { PinProjectButton } from "@/components/projects/PinProjectButton";
import { TagBadgeList } from "@/components/tags/TagBadge";
import { ToolIndexDragHandle } from "@/components/tools/ToolIndexSortable";
import { useCommunityPath } from "@/lib/communityUrl";
import { formatDate } from "@/lib/formatDate";
import { toolDetailRoute } from "@/lib/tools";
import { Badge } from "@/ui/badge";
import { Card, CardFooter, CardHeader, CardTitle } from "@/ui/card";
import { Progress } from "@/ui/progress";

/** A project on its initiative's list. The unread mark is the list's to draw,
 *  in the card's top corner, so the controls stop short of it. */
export const ProjectCard = ({ project }: { project: ProjectRead }) => {
  const { t } = useTranslation("projects");
  const gp = useCommunityPath();

  return (
    <div className="relative">
      {/* Outside the link, so each stays its own button inside a card that is
          an anchor. */}
      <div className="absolute top-3 right-7 z-10 flex items-center gap-1">
        <PinProjectButton
          projectId={project.id}
          isPinned={Boolean(project.pinned_at)}
          canPin={project.can.configure}
          suppressNavigation
        />
        <BookmarkButton
          tool={Tool.project}
          entityId={project.id}
          name={project.name}
          initiativeId={project.initiative_id}
          suppressNavigation
        />
        <ToolIndexDragHandle label={t("preview.reorder")} />
      </div>
      <Link
        to={gp(toolDetailRoute(Tool.project, project.initiative_id, project.id))}
        className="block"
      >
        <Card variant="tile">
          <CardHeader className="pr-34">
            <CardTitle className="flex flex-wrap items-center gap-2 text-xl">
              {project.icon ? <span className="text-2xl leading-none">{project.icon}</span> : null}
              <span>{project.name}</span>
              <ProjectStateBadge project={project} />
            </CardTitle>
          </CardHeader>
          <CardFooter className="flex flex-col gap-3 text-muted-foreground text-sm">
            <div className="flex w-full justify-between gap-6">
              <div>
                <p>
                  {t("preview.updated", {
                    date: formatDate(project.updated_at),
                  })}
                </p>
                {project.archived_at ? (
                  <p>
                    {t("preview.archivedOn", {
                      date: formatDate(project.archived_at),
                    })}
                  </p>
                ) : null}
              </div>
              <div className="flex-1">
                <ProjectProgress summary={project.task_summary} />
              </div>
            </div>
            <TagBadgeList
              tags={project.tags}
              limit={4}
              tagHref={(tag) => gp(`/tags/${tag.id}`)}
              nested
              className="w-full"
            />
          </CardFooter>
        </Card>
      </Link>
    </div>
  );
};

/** Marks a card that is not an ordinary active project, so template and
 *  archived projects stay recognizable wherever they are listed. */
const ProjectStateBadge = ({ project }: { project: ProjectRead }) => {
  const { t } = useTranslation(["projects", "common"]);
  if (project.is_template) {
    return <Badge variant="outline">{t("common:toolChest.template")}</Badge>;
  }
  if (project.archived_at !== null) {
    return <Badge variant="outline">{t("common:toolChest.archived")}</Badge>;
  }
  return null;
};

const ProjectProgress = ({ summary }: { summary?: ProjectRead["task_summary"] }) => {
  const { t } = useTranslation("projects");
  const total = summary?.total ?? 0;
  const completed = summary?.completed ?? 0;
  const percent = total > 0 ? Math.round((completed / total) * 100) : 0;

  return (
    <div className="flex w-full flex-col gap-2">
      <span className="flex justify-end text-muted-foreground text-xs">
        {t("preview.tasksDone", { completed, total })}
      </span>
      <Progress value={percent} className="h-2" aria-label={t("progressLabel")} />
    </div>
  );
};
