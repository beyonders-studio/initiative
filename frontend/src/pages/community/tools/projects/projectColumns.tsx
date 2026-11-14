import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import type { ProjectRead } from "@/api/generated/initiativeAPI.schemas";
import type { AppColumnDef } from "@/ui/lib/table";

/** What the projects table shows beside the columns every tool's table has:
 *  how much of each project's work is done. */
export const useProjectColumns = (): AppColumnDef<ProjectRead>[] => {
  const { t } = useTranslation("projects");

  return useMemo<AppColumnDef<ProjectRead>[]>(
    () => [
      {
        id: "progress",
        header: t("overview.progressLabel"),
        cell: ({ row }) => (
          <span className="text-muted-foreground">
            {t("preview.tasksDone", {
              completed: row.original.task_summary?.completed ?? 0,
              total: row.original.task_summary?.total ?? 0,
            })}
          </span>
        ),
        enableSorting: false,
      },
    ],
    [t]
  );
};
