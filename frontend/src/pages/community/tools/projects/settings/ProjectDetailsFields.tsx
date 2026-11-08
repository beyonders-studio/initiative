import { useTranslation } from "react-i18next";

import type { ProjectRead } from "@/api/generated/initiativeAPI.schemas";
import { ProjectDateFields } from "@/components/tools/projects/ProjectDateFields";
import { useUpdateProject } from "@/hooks/useProjects";
import { useServerForm } from "@/hooks/useServerForm";
import { dateRangeBounds } from "@/lib/dateRange";
import { EmojiField } from "@/ui/emoji-picker";
import { Field } from "@/ui/field";

interface ProjectDates {
  startDate: string;
  endDate: string;
}

/**
 * A project's icon and dates, inside the shared Details card. Each saves on
 * its own: the icon when it is picked, the dates whenever they make a range.
 */
export const ProjectDetailsFields = ({ project }: { project: ProjectRead }) => {
  const { t } = useTranslation("projects");
  // One queue for the project's writes: a later date change waits for the
  // earlier one, so the last change made is the last one saved.
  const update = useUpdateProject(project.id, { scope: { id: `project-${project.id}` } });
  const canEdit = project.can.edit;

  // An inverted pair stays here unsaved until the other date puts it right.
  const dates = useServerForm(
    project,
    (loaded): ProjectDates => ({
      startDate: loaded?.start_date ?? "",
      endDate: loaded?.end_date ?? "",
    }),
    project.id
  );

  const changeDates = (patch: Partial<ProjectDates>) => {
    const next = { ...dates.values, ...patch };
    dates.set(patch);
    if (dateRangeBounds(next.startDate, next.endDate).isInverted) return;
    update.mutate(
      // "" means "no date" in the picker; the API clears on null.
      { start_date: next.startDate || null, end_date: next.endDate || null },
      { onSuccess: () => dates.settle(next) }
    );
  };

  return (
    <div className="space-y-4">
      <Field label={t("createDialog.iconLabel")}>
        <EmojiField
          value={project.icon ?? undefined}
          onChange={(emoji) => update.mutate({ icon: emoji ?? null })}
          disabled={!canEdit}
        />
      </Field>
      <ProjectDateFields
        idPrefix="project-settings"
        startDate={dates.values.startDate}
        endDate={dates.values.endDate}
        onStartDateChange={(startDate) => changeDates({ startDate })}
        onEndDateChange={(endDate) => changeDates({ endDate })}
        disabled={!canEdit}
      />
    </div>
  );
};
