import { ListTodo, Loader2, Search } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import type { ProjectRead } from "@/api/generated/initiativeAPI.schemas";
import { useGlobalProjects } from "@/hooks/useProjects";
import { Input } from "@/ui/input";
import { LoadMore } from "@/ui/load-more";

interface ProjectPickerStepProps {
  communityId: number;
  initiativeId: number;
  onPick: (project: ProjectRead) => void;
}

/**
 * The wizards' project step: the projects of one initiative that a task can be
 * added to, searchable and paged. Each walk into the step mounts it afresh, so
 * it starts from an empty search.
 */
export function ProjectPickerStep({ communityId, initiativeId, onPick }: ProjectPickerStepProps) {
  const { t } = useTranslation("tasks");
  const [projectSearch, setProjectSearch] = useState("");
  const [projectPage, setProjectPage] = useState(1);

  // Track a "generation" that increments when filters change, so we can
  // distinguish stale accumulated data from the current filter set.
  const [projectGen, setProjectGen] = useState(0);
  const prevFilterKey = useRef("");
  const filterKey = `${communityId}-${initiativeId}-${projectSearch}`;
  if (filterKey !== prevFilterKey.current) {
    prevFilterKey.current = filterKey;
    setProjectGen((g) => g + 1);
    setProjectPage(1);
  }

  const projectsQuery = useGlobalProjects({
    community_ids: [communityId],
    search: projectSearch || undefined,
    page_size: 25,
    page: projectPage,
  });

  // Accumulate pages, keyed by generation to avoid mixing results across filters
  const [accumulatedProjects, setAccumulatedProjects] = useState<{
    gen: number;
    items: ProjectRead[];
  }>({ gen: 0, items: [] });

  useEffect(() => {
    if (!projectsQuery.data) return;
    const items = projectsQuery.data.items;
    setAccumulatedProjects((prev) =>
      prev.gen !== projectGen
        ? { gen: projectGen, items }
        : { gen: projectGen, items: projectPage === 1 ? items : [...prev.items, ...items] }
    );
  }, [projectsQuery.data, projectPage, projectGen]);

  const filteredProjects = useMemo(
    () =>
      accumulatedProjects.items.filter(
        (p) => p.initiative_id === initiativeId && p.archived_at === null && p.can.edit
      ),
    [accumulatedProjects, initiativeId]
  );
  const hasMoreProjects = projectsQuery.data?.has_next ?? false;

  return (
    <div className="space-y-2">
      <div className="relative">
        <Search className="absolute top-1/2 left-3 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          value={projectSearch}
          onChange={(e) => setProjectSearch(e.target.value)}
          placeholder={t("createWizard.searchProjects")}
          className="pl-9"
          autoFocus
        />
      </div>
      {projectsQuery.isLoading ? (
        <div className="flex items-center justify-center py-8">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </div>
      ) : filteredProjects.length === 0 && !hasMoreProjects ? (
        <p className="py-4 text-center text-muted-foreground text-sm">
          {t("createWizard.noProjects")}
        </p>
      ) : (
        <>
          {filteredProjects.map((project) => (
            <button
              key={project.id}
              type="button"
              className="flex w-full items-center gap-3 rounded-lg border p-3 text-left transition-colors hover:bg-accent"
              onClick={() => onPick(project)}
            >
              <ListTodo className="h-4 w-4 shrink-0 text-muted-foreground" />
              <span className="font-medium text-sm">{project.name}</span>
            </button>
          ))}
          <LoadMore
            hasMore={hasMoreProjects}
            loading={projectsQuery.isFetching}
            onLoadMore={() => setProjectPage((p) => p + 1)}
          />
        </>
      )}
    </div>
  );
}
