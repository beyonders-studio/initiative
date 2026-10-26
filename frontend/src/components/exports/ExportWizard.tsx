import { AlertTriangle, CheckCircle2, ChevronDown, Filter, Loader2, XCircle } from "lucide-react";
import { type ReactNode, useEffect, useId, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { useEstimateAggregateExport } from "@/api/generated/exports/exports";
import { type SortField, type TaskStatusRead, Tool } from "@/api/generated/initiativeAPI.schemas";
import type { ExportExtraAction, ExportFormatOption } from "@/components/exports/ExportButton";
import {
  AGGREGATE_EXPORT_TOOLS,
  REPORT_FILE_FORMATS,
  REPORT_TOOL_FORMATS,
} from "@/components/exports/formats";
import { FilterCountBadge } from "@/components/initiativeTools/shared/ToolFilterPanel";
import {
  type ToolArchiveChoice,
  ToolViewFilter,
} from "@/components/initiativeTools/shared/ToolViewFilter";
import { TaskFilters } from "@/components/tasks/TaskFilters";
import { ToolFilterFields, type ToolListFilters } from "@/components/tools/ToolFilterFields";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import {
  DateRangeField,
  dateRangeParams,
  type LocalDateRange,
  useFormatDateRange,
} from "@/components/ui/date-range-field";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Switch } from "@/components/ui/switch";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { WizardDialog } from "@/components/ui/wizard-dialog";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { useExportJob } from "@/hooks/useExportJob";
import { useWizard } from "@/hooks/useWizard";
import { formatBytes } from "@/lib/fileUtils";
import {
  DUE_LABEL_KEYS,
  EMPTY_TASK_FILTERS,
  type TaskFilterSpec,
  taskSpecConditions,
} from "@/lib/filters/taskFilters";
import { toolExportEndpoint, toolNavLabelKey, toolViews } from "@/lib/tools";
import { cn } from "@/lib/utils";

/** What the wizard exports: a whole initiative or community, or named
 *  entities of one tool (a tool's export card, a bulk selection). */
export type ExportWizardScope =
  | { kind: "initiative"; initiativeId: number }
  | { kind: "community" }
  | {
      kind: "entities";
      tool: Tool;
      ids: number[];
      /** The formats on offer: json under "Backup", the rest under "Report". */
      formats: ExportFormatOption[];
      /** Inline-download filename stem: `{stem}.{format}`. */
      filenameStem: string;
      extraActions?: ExportExtraAction[];
      /** What its content starts narrowed to: the exporting person's own
       *  view of it, where there is one. */
      content?: ExportContentSeed;
    };

/** One person's view of a project's tasks, for an export of that project to
 *  start from: its filters, its order, and the statuses the filters name. */
export interface ExportContentSeed {
  tasks: TaskFilterSpec;
  taskSorting: SortField[];
  /** The layout fields their table of the project shows, which its report
   *  shows. */
  taskColumns: string[];
  taskStatuses: TaskStatusRead[];
}

export interface ExportWizardProps {
  scope: ExportWizardScope;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

type AggregateScope = Exclude<ExportWizardScope, { kind: "entities" }>;
type EntitiesScope = Extract<ExportWizardScope, { kind: "entities" }>;

const DEFAULT_FILE_FORMATS = { lexical: "pdf", sheet: "xlsx" };

/** An export's `archived`: omitted exports live and archived alike. */
const ARCHIVED_FOR: Record<ToolArchiveChoice, boolean | undefined> = {
  all: undefined,
  active: false,
  archived: true,
};

const archiveChoice = (archived: boolean | null | undefined): ToolArchiveChoice =>
  archived == null ? "all" : archived ? "archived" : "active";

/** Filters only an export offers. A list page reaches the same rows through
 *  its view filter and tag tree, so they stay out of the shared filter fields:
 *  templates, for a tool with a templates view, and untagged rows, which only
 *  the files list takes. */
const UNTAGGED_TOOLS: ReadonlySet<Tool> = new Set([Tool.file]);

/** A tool's export-only list params, as one record over every tool's. */
type ExportOnlyParams = { is_template?: boolean; untagged?: boolean };

/** The templates choice, each with the value it sends: omitted exports
 *  templates and the rest alike. */
const TEMPLATE_CHOICES = [
  { value: "all", template: undefined, label: "common:toolViewFilter.all" },
  { value: "without", template: false, label: "wizard.filter.withoutTemplates" },
  { value: "only", template: true, label: "wizard.filter.templatesOnly" },
] as const;

/** Drops what narrows nothing — blank text, empty lists and objects, unset
 *  values — so only real filters are sent. */
const compact = (filters: object): Record<string, unknown> =>
  Object.fromEntries(
    Object.entries(filters).flatMap(([key, raw]) => {
      const value: unknown = typeof raw === "string" ? raw.trim() : raw;
      const empty =
        value == null ||
        value === "" ||
        (Array.isArray(value) && value.length === 0) ||
        (typeof value === "object" && !Array.isArray(value) && Object.keys(value).length === 0);
      return empty ? [] : [[key, value]];
    })
  );

/** What the wizard narrows tools' content by: a calendar's events by date, a
 *  project's tasks by the task list's own filters. */
interface ContentFilters {
  events: LocalDateRange;
  tasks: TaskFilterSpec;
  /** The order a project's tasks are listed in; empty for its own. */
  taskSorting: SortField[];
  /** The fields its report shows; empty for the shipped ones. */
  taskColumns: string[];
}

/** Nothing narrowed. A backup carries every task, archived ones too, and a
 *  report the ones its task list shows, so the archived switch starts where
 *  the chosen output does. */
const emptyContent = (backup: boolean): ContentFilters => ({
  events: {},
  tasks: { ...EMPTY_TASK_FILTERS, include_archived: backup },
  taskSorting: [],
  taskColumns: [],
});

/** The same filters for another output: the archived switch moves to where
 *  that output starts, and everything else stays as it was set. */
const forOutput = (content: ContentFilters, backup: boolean): ContentFilters => ({
  ...content,
  tasks: { ...content.tasks, include_archived: backup },
});

/** A project's `tasks`: the conditions and sort the task list sends and its
 *  archived switch, or nothing while they are where the output starts. */
const taskExportParams = (
  spec: TaskFilterSpec,
  sorting: SortField[],
  columns: string[],
  backup: boolean
): Record<string, unknown> => {
  const conditions = taskSpecConditions(spec);
  if (
    conditions.length === 0 &&
    sorting.length === 0 &&
    columns.length === 0 &&
    spec.include_archived === backup
  ) {
    return {};
  }
  return {
    ...(conditions.length > 0 ? { conditions: JSON.stringify(conditions) } : {}),
    ...(sorting.length > 0 ? { sorting: JSON.stringify(sorting) } : {}),
    ...(columns.length > 0 ? { columns } : {}),
    include_archived: spec.include_archived,
  };
};

interface ContentFieldProps {
  value: ContentFilters;
  onChange: (next: ContentFilters) => void;
  /** The initiative being exported, where there is one. */
  initiativeId?: number;
  /** The one project's statuses, when a single project is exported. */
  taskStatuses?: TaskStatusRead[];
}

/** A calendar's events, by the dates they start in. */
function EventDatesField({ value, onChange }: ContentFieldProps) {
  const { t } = useTranslation("exports");
  return (
    <div className="space-y-2">
      <Label htmlFor="calendar-content-dates" className="text-xs">
        {t("wizard.filter.eventDates")}
      </Label>
      <DateRangeField
        id="calendar-content-dates"
        value={value.events}
        onChange={(events) => onChange({ ...value, events })}
      />
    </div>
  );
}

/** A project's tasks, by the task list's own filters. With no one project to
 *  read statuses from, statuses are picked by category. */
function TaskFiltersField({ value, onChange, initiativeId, taskStatuses = [] }: ContentFieldProps) {
  const { t } = useTranslation("exports");
  return (
    <div className="space-y-2">
      <p className="font-medium text-xs">{t("wizard.filter.tasks")}</p>
      <TaskFilters
        scope={{
          kind: "project",
          memberScope:
            initiativeId == null ? { type: "community" } : { type: "initiative", initiativeId },
          statuses: taskStatuses,
          initiativeId: initiativeId,
        }}
        value={value.tasks}
        onChange={(tasks) => onChange({ ...value, tasks })}
      />
    </div>
  );
}

interface ContentFilter {
  /** What it adds to the tool's `filters` entry, for a backup or a report. */
  params: (content: ContentFilters, backup: boolean) => Record<string, unknown>;
  /** Its step's prompt and note, when exporting named entities. */
  prompt: string;
  note: string;
  Field: (props: ContentFieldProps) => ReactNode;
}

/** Tools whose content has a filter of its own. */
const CONTENT_FILTERS: Partial<Record<Tool, ContentFilter>> = {
  [Tool.calendar]: {
    params: ({ events }) => ({ events: dateRangeParams(events) }),
    prompt: "wizard.content.prompt",
    note: "wizard.content.allDatesNote",
    Field: EventDatesField,
  },
  [Tool.project]: {
    params: ({ tasks, taskSorting, taskColumns }, backup) => ({
      tasks: taskExportParams(tasks, taskSorting, taskColumns, backup),
    }),
    prompt: "wizard.content.tasksPrompt",
    note: "wizard.content.allTasksNote",
    Field: TaskFiltersField,
  },
};

/** One tool's `filters` entry: its list filters, and its content filter. */
const toolExportFilters = (
  tool: Tool,
  listFilters: ToolListFilters | undefined,
  content: ContentFilters,
  backup: boolean
): Record<string, unknown> =>
  compact({ ...listFilters, ...CONTENT_FILTERS[tool]?.params(content, backup) });

/** The wizard's step trail and its export job, reset to a fresh flow when the
 *  dialog closes (state only — a job already started keeps polling in the hook
 *  and delivers regardless). Re-opening while that job still renders resumes
 *  its progress view: the hook can't start a second job, so offering the
 *  option steps again would end in a "Start export" that silently tracked the
 *  OLD job. */
function useExportWizardFlow<S extends string>(open: boolean, first: S, resetState: () => void) {
  const exportJob = useExportJob();
  const wizard = useWizard<S | "progress">(first);

  // biome-ignore lint/correctness/useExhaustiveDependencies: runs only on open/close; job state is read at that moment, and reacting to every poll tick would re-fire the reset
  useEffect(() => {
    if (!open) {
      wizard.reset();
      resetState();
      exportJob.reset();
    } else if (exportJob.busy) {
      wizard.commit("progress");
    }
  }, [open]);

  return { ...wizard, exportJob };
}

/** The last step: the job's progress, then how it ended. */
function ExportProgress({
  phase,
  inline,
  onClose,
}: {
  phase: ReturnType<typeof useExportJob>["phase"];
  inline: boolean;
  onClose: () => void;
}) {
  const { t } = useTranslation("exports");
  return (
    <div className="flex flex-col items-center gap-3 py-6 text-center">
      {phase === "done" ? (
        <>
          <CheckCircle2 className="h-8 w-8 text-primary" />
          <p className="font-medium text-sm">{t("wizard.done.title")}</p>
          <p className="text-muted-foreground text-xs">
            {inline ? t("wizard.done.noteInline") : t("wizard.done.note")}
          </p>
        </>
      ) : phase === "failed" ? (
        <>
          <XCircle className="h-8 w-8 text-destructive" />
          <p className="font-medium text-sm">{t("wizard.failed.title")}</p>
          <p className="text-muted-foreground text-xs">{t("wizard.failed.note")}</p>
        </>
      ) : (
        <>
          <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
          <p className="font-medium text-sm">{t("wizard.progress.title")}</p>
          <p className="text-muted-foreground text-xs">{t("wizard.progress.note")}</p>
        </>
      )}
      <Button variant="outline" size="sm" onClick={onClose}>
        {t("wizard.close")}
      </Button>
    </div>
  );
}

/** A tool card's "Filter" disclosure: which of the tool's things to export
 *  (its list's own filters, plus live / archived / both), and what inside
 *  them where the content has a filter of its own. */
function ToolFilterSection({
  tool,
  value,
  onChange,
  content,
  onContentChange,
  backup,
  initiativeId,
}: {
  tool: Tool;
  value: ToolListFilters;
  onChange: (next: ToolListFilters) => void;
  content: ContentFilters;
  onContentChange: (next: ContentFilters) => void;
  backup: boolean;
  initiativeId?: number;
}) {
  const { t } = useTranslation(["exports", "nav", "common", "projects", "files"]);
  const id = useId();
  const [open, setOpen] = useState(false);
  const filters = toolExportFilters(tool, value, content, backup);
  const count = Object.keys(filters).length;
  const ContentField = CONTENT_FILTERS[tool]?.Field;
  const templates = toolViews(tool).includes("templates");
  const untagged = UNTAGGED_TOOLS.has(tool);
  const set = (params: ExportOnlyParams) => onChange({ ...value, ...params });

  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <CollapsibleTrigger asChild>
        <Button
          variant="ghost"
          size="sm"
          className="h-7 gap-2 px-2"
          aria-label={t("wizard.filter.toggleFor", {
            tool: t(`nav:${toolNavLabelKey(tool)}` as never),
          })}
        >
          <Filter className="h-3.5 w-3.5" />
          {t("wizard.filter.toggle")}
          <FilterCountBadge count={count} />
          <ChevronDown className={cn("h-3 w-3 transition-transform", open && "rotate-180")} />
        </Button>
      </CollapsibleTrigger>
      <CollapsibleContent className="space-y-3 pt-2">
        <ToolViewFilter
          tool={tool}
          includeAll
          value={archiveChoice(value.archived)}
          onChange={(choice) => onChange({ ...value, archived: ARCHIVED_FOR[choice] })}
        />
        {templates ? (
          <div className="space-y-2">
            <Label id={`${id}-templates`} className="text-xs">
              {t("wizard.filter.templates")}
            </Label>
            <ToggleGroup
              type="single"
              variant="outline"
              aria-labelledby={`${id}-templates`}
              value={TEMPLATE_CHOICES.find((c) => c.template === filters.is_template)?.value}
              onValueChange={(next) =>
                next &&
                set({ is_template: TEMPLATE_CHOICES.find((c) => c.value === next)?.template })
              }
              className="h-9 justify-start"
            >
              {TEMPLATE_CHOICES.map((choice) => (
                <ToggleGroupItem key={choice.value} value={choice.value} className="h-9 px-3">
                  {t(choice.label)}
                </ToggleGroupItem>
              ))}
            </ToggleGroup>
          </div>
        ) : null}
        {untagged ? (
          <div className="flex items-center gap-2">
            <Switch
              id={`${id}-untagged`}
              checked={filters.untagged === true}
              onCheckedChange={(checked) => set({ untagged: checked || undefined })}
            />
            <Label htmlFor={`${id}-untagged`} className="text-xs">
              {t("wizard.filter.untaggedOnly")}
            </Label>
          </div>
        ) : null}
        <div className="flex flex-col gap-3">
          <ToolFilterFields
            tool={tool}
            value={value}
            onChange={onChange}
            initiativeId={initiativeId}
          />
        </div>
        {ContentField ? (
          <ContentField value={content} onChange={onContentChange} initiativeId={initiativeId} />
        ) : null}
      </CollapsibleContent>
    </Collapsible>
  );
}

/** One tool's active filters, briefly: "1 Jul – 30 Sep 2026 · 2 tags". */
function useDescribeFilters() {
  const { t } = useTranslation(["exports", "projects"]);
  const formatRange = useFormatDateRange();
  return (
    tool: Tool,
    filters: Record<string, unknown>,
    content: ContentFilters,
    backup: boolean
  ): string => {
    const parts: string[] = [];
    if ("events" in filters) parts.push(formatRange(content.events));
    if ("tasks" in filters) {
      const { status_ids, status_categories, assignees, tag_ids, properties, due } = content.tasks;
      const statuses = status_ids.length + status_categories.length;
      const taskParts = [
        statuses > 0 && t("wizard.filterSummary.statuses", { count: statuses }),
        assignees.length > 0 && t("wizard.filterSummary.assignees", { count: assignees.length }),
        due && t(`projects:${DUE_LABEL_KEYS[due]}`),
        tag_ids.length > 0 && t("wizard.filterSummary.tags", { count: tag_ids.length }),
        properties.length > 0 && t("wizard.filterSummary.more", { count: properties.length }),
        // Said only where it differs from what the output carries anyway.
        content.tasks.include_archived !== backup &&
          t(backup ? "wizard.filterSummary.withoutArchived" : "wizard.filterSummary.withArchived"),
      ];
      parts.push(
        t("wizard.filterSummary.tasks", { filters: taskParts.filter(Boolean).join(", ") })
      );
    }
    if (typeof filters.search === "string") {
      parts.push(t("wizard.filterSummary.search", { search: filters.search }));
    }
    if (Array.isArray(filters.tag_ids)) {
      parts.push(t("wizard.filterSummary.tags", { count: filters.tag_ids.length }));
    }
    if (filters.archived === true) parts.push(t("wizard.filterSummary.archivedOnly"));
    if (filters.archived === false) parts.push(t("wizard.filterSummary.activeOnly"));
    if (typeof filters.is_template === "boolean") {
      parts.push(
        t(filters.is_template ? "wizard.filter.templatesOnly" : "wizard.filter.withoutTemplates")
      );
    }
    if (filters.untagged === true) parts.push(t("wizard.filter.untaggedOnly"));
    const described = new Set<string>([
      "events",
      "tasks",
      "search",
      "tag_ids",
      "archived",
      "is_template",
      "untagged",
    ]);
    const more = Object.keys(filters).filter((key) => !described.has(key)).length;
    if (more > 0) parts.push(t("wizard.filterSummary.more", { count: more }));
    return parts.join(" · ");
  };
}

/** The aggregate export flow: mode → (backup options with live estimate |
 * per-tool report formats), each tool with its filters → confirm → progress.
 * Delivery is the shared useExportJob poll — closing the dialog mid-render
 * doesn't cancel the job, the download still arrives (and lands in the
 * settings exports table). */
function AggregateExportWizard({
  scope,
  open,
  onOpenChange,
}: ExportWizardProps & { scope: AggregateScope }) {
  const { t } = useTranslation(["exports", "nav"]);
  const communityId = useActiveCommunityId();
  const describeFilters = useDescribeFilters();

  const [mode, setMode] = useState<"backup" | "report">("backup");
  const [include, setInclude] = useState<Record<string, boolean>>({});
  const [includeUploads, setIncludeUploads] = useState(true);
  const [formats, setFormats] = useState<Record<string, string>>({});
  const [fileFormats, setFileFormats] = useState(DEFAULT_FILE_FORMATS);
  const [listFilters, setListFilters] = useState<Partial<Record<Tool, ToolListFilters>>>({});
  const [content, setContent] = useState(() => emptyContent(true));

  const { step, go, commit, back, canGoBack, exportJob } = useExportWizardFlow<
    "mode" | "backup" | "report" | "confirm"
  >(open, "mode", () => {
    setMode("backup");
    setInclude({});
    setIncludeUploads(true);
    setFormats({});
    setFileFormats(DEFAULT_FILE_FORMATS);
    setListFilters({});
    setContent(emptyContent(true));
  });

  const visibleTools = AGGREGATE_EXPORT_TOOLS;
  const included = (tool: Tool) => include[tool] !== false;
  const setIncluded = (tool: Tool, value: boolean) =>
    setInclude((prev) => ({ ...prev, [tool]: value }));

  // Each included tool's filters, and only the tools that have some; no
  // `filters` param at all when none do.
  const activeFilters = visibleTools.flatMap((tool) => {
    const filters = included(tool)
      ? toolExportFilters(tool, listFilters[tool], content, mode === "backup")
      : {};
    return Object.keys(filters).length > 0 ? [[tool, filters] as const] : [];
  });
  const filtersParam =
    activeFilters.length > 0 ? JSON.stringify(Object.fromEntries(activeFilters)) : undefined;
  // A keystroke in a search box is not a request.
  const estimateFilters = useDebouncedValue(filtersParam, 300);

  const estimateQuery = useEstimateAggregateExport(
    communityId,
    {
      scope: scope.kind === "community" ? "community" : scope.kind,
      initiative_id: scope.kind === "initiative" ? scope.initiativeId : null,
      include_uploads: includeUploads,
      ...(estimateFilters ? { filters: estimateFilters } : {}),
    },
    { query: { enabled: open && step === "backup" } }
  );
  const estimate = estimateQuery.data;
  // The numbers below describe the filters as they were when asked; until
  // they describe the current ones, the backup step waits for them.
  const estimateCurrent = estimateFilters === filtersParam && !estimateQuery.isFetching;

  const toolDisabled = (tool: Tool) => estimate?.tools?.[tool]?.disabled === true;

  const overRowLimit =
    estimate != null && (estimate.estimated_rows ?? 0) > (estimate.max_rows ?? Infinity);
  const overUploadLimit =
    estimate != null &&
    includeUploads &&
    (estimate.uploads_bytes ?? 0) > (estimate.max_upload_bytes ?? Infinity);
  // Past the download bound the archive is written to the server's export
  // folder instead of being handed back. Say which of the two will happen
  // before anybody starts a build that runs for an hour.
  const overDownloadBound =
    estimate != null &&
    !overUploadLimit &&
    (estimate.uploads_bytes ?? 0) > (estimate.max_download_bytes ?? Infinity);
  const deliveryAvailable = estimate?.delivery_available === true;
  const blockedForNoDestination = overDownloadBound && !deliveryAvailable;

  // A disabled tool's switch is locked showing "off" — the payload must say
  // the same (the backend would skip it anyway, but the manifest's
  // included/excluded/disabled inventory should match what the user saw).
  const effectiveIncluded = (tool: Tool) => !toolDisabled(tool) && included(tool);
  const anyIncluded = visibleTools.some(effectiveIncluded);

  const toolLabel = (tool: Tool) => t(`nav:${toolNavLabelKey(tool)}` as never);

  const filterSection = (tool: Tool) => (
    <ToolFilterSection
      tool={tool}
      value={listFilters[tool] ?? {}}
      onChange={(next) => setListFilters((prev) => ({ ...prev, [tool]: next }))}
      content={content}
      onContentChange={setContent}
      backup={mode === "backup"}
      initiativeId={scope.kind === "initiative" ? scope.initiativeId : undefined}
    />
  );

  const startExport = () => {
    if (exportJob.busy) {
      return;
    }
    const includeParam: Record<string, boolean> = {};
    for (const tool of visibleTools) {
      includeParam[tool] = effectiveIncluded(tool);
    }
    const params: Record<string, unknown> = {
      mode,
      include: JSON.stringify(includeParam),
      ...(filtersParam ? { filters: filtersParam } : {}),
    };
    if (scope.kind === "initiative") {
      params.initiative_id = scope.initiativeId;
    }
    if (mode === "backup") {
      params.include_uploads = includeUploads;
    } else {
      const formatParam: Record<string, unknown> = { file: fileFormats };
      for (const tool of visibleTools) {
        const options = REPORT_TOOL_FORMATS[tool];
        if (options) {
          formatParam[tool] = formats[tool] ?? options[0].format;
        }
      }
      params.formats = JSON.stringify(formatParam);
    }
    commit("progress");
    void exportJob.start({
      endpoint: scope.kind === "community" ? "/exports/community" : "/exports/initiative",
      params,
      fallbackFilename: `${scope.kind}-export.zip`,
    });
  };

  const stepDescription = useMemo(() => {
    switch (step) {
      case "mode":
        return t("wizard.mode.prompt");
      case "backup":
        return t("wizard.backup.prompt");
      case "report":
        return t("wizard.report.fileOthersNote");
      case "confirm":
        return t("wizard.confirm.prompt");
      case "progress":
        return null;
    }
  }, [step, t]);

  // Three questions, whichever way round you answer them: the backup options
  // and the report formats are the same position, one on each route.
  const position = { mode: 1, backup: 2, report: 2, confirm: 3, progress: null }[step];

  return (
    <WizardDialog
      open={open}
      onOpenChange={onOpenChange}
      className="max-h-[85vh] overflow-y-auto sm:max-w-lg"
      title={scope.kind === "community" ? t("wizard.titleCommunity") : t("wizard.titleInitiative")}
      description={stepDescription}
      progress={position === null ? undefined : { current: position, total: 3 }}
      onBack={canGoBack ? back : undefined}
      backLabel={t("wizard.back")}
    >
      {step === "mode" && (
        <div className="space-y-2">
          {(["backup", "report"] as const).map((option) => (
            <button
              key={option}
              type="button"
              className="w-full rounded-lg border p-4 text-left transition-colors hover:bg-accent"
              onClick={() => {
                if (option !== mode) {
                  setContent((prev) => forOutput(prev, option === "backup"));
                }
                setMode(option);
                go(option);
              }}
            >
              <p className="font-medium text-sm">
                {option === "backup" ? t("wizard.mode.backupTitle") : t("wizard.mode.reportTitle")}
              </p>
              <p className="mt-1 text-muted-foreground text-xs">
                {option === "backup"
                  ? t("wizard.mode.backupDescription")
                  : t("wizard.mode.reportDescription")}
              </p>
            </button>
          ))}
        </div>
      )}

      {step === "backup" && (
        <div className="space-y-4">
          <div className="space-y-2">
            {visibleTools.map((tool) => {
              const disabled = toolDisabled(tool);
              const count = estimate?.tools?.[tool]?.count;
              return (
                <fieldset
                  key={tool}
                  aria-label={toolLabel(tool)}
                  className="min-w-0 space-y-2 rounded-lg border p-3"
                >
                  <div className="flex items-center justify-between">
                    <div className="min-w-0">
                      <Label htmlFor={`include-${tool}`} className="text-sm">
                        {toolLabel(tool)}
                      </Label>
                      <p className="text-muted-foreground text-xs">
                        {disabled
                          ? t("wizard.backup.disabled")
                          : count != null
                            ? t("wizard.backup.toolCount", { count })
                            : " "}
                      </p>
                    </div>
                    <Switch
                      id={`include-${tool}`}
                      checked={!disabled && included(tool)}
                      disabled={disabled}
                      onCheckedChange={(checked) => setIncluded(tool, checked)}
                    />
                  </div>
                  {!disabled && included(tool) && filterSection(tool)}
                </fieldset>
              );
            })}
          </div>
          <div className="flex items-center justify-between rounded-lg border p-3">
            <div className="min-w-0">
              <Label htmlFor="include-uploads" className="text-sm">
                {t("wizard.backup.includeUploads")}
              </Label>
              <p className="text-muted-foreground text-xs">
                {estimateQuery.isError
                  ? t("wizard.backup.estimateFailed")
                  : estimate
                    ? t("wizard.backup.uploadsSize", {
                        size: formatBytes(estimate.uploads_bytes ?? 0),
                      })
                    : " "}
              </p>
            </div>
            <Switch
              id="include-uploads"
              checked={includeUploads}
              onCheckedChange={setIncludeUploads}
            />
          </div>
          {(overRowLimit || overUploadLimit) && (
            <div className="flex items-start gap-2 rounded-lg border border-destructive/50 bg-destructive/5 p-3 text-destructive text-sm">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
              <span>
                {overUploadLimit
                  ? t("wizard.backup.overUploadLimit", {
                      limit: formatBytes(estimate?.max_upload_bytes ?? 0),
                    })
                  : t("wizard.backup.overRowLimit")}
              </span>
            </div>
          )}
          {overDownloadBound && (
            <div
              className={
                blockedForNoDestination
                  ? "flex items-start gap-2 rounded-lg border border-destructive/50 bg-destructive/5 p-3 text-destructive text-sm"
                  : "flex items-start gap-2 rounded-lg border bg-muted/40 p-3 text-muted-foreground text-sm"
              }
            >
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
              <span>
                {blockedForNoDestination
                  ? t("wizard.backup.noDestination", {
                      limit: formatBytes(estimate?.max_download_bytes ?? 0),
                    })
                  : t("wizard.backup.willBeDelivered", {
                      limit: formatBytes(estimate?.max_download_bytes ?? 0),
                    })}
              </span>
            </div>
          )}
          <Button
            className="w-full"
            disabled={
              !estimateCurrent ||
              !anyIncluded ||
              overRowLimit ||
              overUploadLimit ||
              blockedForNoDestination
            }
            onClick={() => go("confirm")}
          >
            {t("wizard.next")}
          </Button>
        </div>
      )}

      {step === "report" && (
        <div className="space-y-4">
          <div className="space-y-2">
            {visibleTools.map((tool) => {
              const options = REPORT_TOOL_FORMATS[tool];
              const isFiles = options == null;
              return (
                <fieldset
                  key={tool}
                  aria-label={toolLabel(tool)}
                  className="min-w-0 space-y-2 rounded-lg border p-3"
                >
                  <div className="flex items-center justify-between">
                    <Label htmlFor={`report-${tool}`} className="text-sm">
                      {toolLabel(tool)}
                    </Label>
                    <Switch
                      id={`report-${tool}`}
                      checked={included(tool)}
                      onCheckedChange={(checked) => setIncluded(tool, checked)}
                    />
                  </div>
                  {included(tool) && !isFiles && (
                    <RadioGroup
                      value={formats[tool] ?? options[0].format}
                      onValueChange={(value) => setFormats((prev) => ({ ...prev, [tool]: value }))}
                      className="flex flex-wrap gap-3"
                    >
                      {options.map((option) => (
                        <div key={option.format} className="flex items-center gap-1.5">
                          <RadioGroupItem value={option.format} id={`${tool}-${option.format}`} />
                          <Label htmlFor={`${tool}-${option.format}`} className="text-xs">
                            {t(option.labelKey as never)}
                          </Label>
                        </div>
                      ))}
                    </RadioGroup>
                  )}
                  {included(tool) && isFiles && (
                    <div className="space-y-2">
                      {(["lexical", "sheet"] as const).map((docType) => (
                        <div key={docType} className="space-y-1">
                          <p className="text-muted-foreground text-xs">
                            {docType === "lexical"
                              ? t("wizard.report.fileNative")
                              : t("wizard.report.fileSpreadsheet")}
                          </p>
                          <RadioGroup
                            value={fileFormats[docType]}
                            onValueChange={(value) =>
                              setFileFormats((prev) => ({ ...prev, [docType]: value }))
                            }
                            className="flex flex-wrap gap-3"
                          >
                            {REPORT_FILE_FORMATS[docType].map((option) => (
                              <div key={option.format} className="flex items-center gap-1.5">
                                <RadioGroupItem
                                  value={option.format}
                                  id={`doc-${docType}-${option.format}`}
                                />
                                <Label
                                  htmlFor={`doc-${docType}-${option.format}`}
                                  className="text-xs"
                                >
                                  {t(option.labelKey as never)}
                                </Label>
                              </div>
                            ))}
                          </RadioGroup>
                        </div>
                      ))}
                    </div>
                  )}
                  {included(tool) && filterSection(tool)}
                </fieldset>
              );
            })}
          </div>
          <Button className="w-full" disabled={!anyIncluded} onClick={() => go("confirm")}>
            {t("wizard.next")}
          </Button>
        </div>
      )}

      {step === "confirm" && (
        <div className="space-y-4">
          <div className="space-y-1 rounded-lg border p-3 text-sm">
            <p className="font-medium">
              {mode === "backup" ? t("wizard.confirm.modeBackup") : t("wizard.confirm.modeReport")}
            </p>
            <p className="text-muted-foreground text-xs">
              {/* Same predicate as the submitted payload — a disabled
                    tool's locked-off switch must not reappear here. */}
              {visibleTools.filter(effectiveIncluded).map(toolLabel).join(" · ")}
            </p>
            {activeFilters
              .filter(([tool]) => effectiveIncluded(tool))
              .map(([tool, filters]) => (
                <p key={tool} className="text-muted-foreground text-xs">
                  {t("wizard.confirm.toolFilters", {
                    tool: toolLabel(tool),
                    filters: describeFilters(tool, filters, content, mode === "backup"),
                  })}
                </p>
              ))}
            {mode === "backup" && (
              <p className="text-muted-foreground text-xs">
                {includeUploads
                  ? t("wizard.confirm.uploadsIncluded")
                  : t("wizard.confirm.uploadsExcluded")}
              </p>
            )}
          </div>
          <p className="text-muted-foreground text-xs">{t("wizard.confirm.note")}</p>
          {/* busy guard: the hook can only track one job — starting while a
                previous job still polls would show its progress as this
                export's and deliver the wrong download. */}
          <Button className="w-full" disabled={exportJob.busy} onClick={startExport}>
            {t("wizard.start")}
          </Button>
        </div>
      )}

      {step === "progress" && (
        <ExportProgress
          phase={exportJob.phase}
          inline={exportJob.inline}
          onClose={() => onOpenChange(false)}
        />
      )}
    </WizardDialog>
  );
}

/** Exporting named entities of one tool: format → the tool's content filter
 * (skipped for a tool whose content has none) → confirm → progress. A small
 * export downloads straight away; a large one queues, as useExportJob does
 * for every surface. */
function EntitiesExportWizard({
  scope,
  open,
  onOpenChange,
}: ExportWizardProps & { scope: EntitiesScope }) {
  const { t } = useTranslation("exports");
  const describeFilters = useDescribeFilters();
  const { tool, ids, formats, filenameStem, extraActions = [], content: seed } = scope;
  const contentFilter = CONTENT_FILTERS[tool];

  // A tool with one format and nothing client-side has no choice to offer,
  // so the wizard starts past it.
  const only = formats.length === 1 && extraActions.length === 0 ? formats[0] : null;
  const [option, setOption] = useState<ExportFormatOption | null>(only);
  const backup = option?.format === "json";
  // The exporting person's own view, where there is one, exactly as it
  // shows: it is what they asked to export, whichever format carries it.
  const startContent = (forBackup: boolean): ContentFilters =>
    seed ? { ...emptyContent(forBackup), ...seed } : emptyContent(forBackup);
  const [content, setContent] = useState(() => startContent(only?.format === "json"));

  const { step, go, commit, back, canGoBack, exportJob } = useExportWizardFlow<
    "format" | "content" | "confirm"
  >(open, only ? (contentFilter ? "content" : "confirm") : "format", () => {
    setOption(only);
  });
  // The view loads after the wizard mounts, and can change while it is
  // closed, so each opening starts from it as it is then.
  // biome-ignore lint/correctness/useExhaustiveDependencies: runs on opening only; the seed is read at that moment
  useEffect(() => {
    if (open && !exportJob.busy) setContent(startContent(only?.format === "json"));
  }, [open]);

  // Only the content filter travels for named entities: the ids already say
  // which things.
  const filters = toolExportFilters(tool, undefined, content, backup);

  // The menu's grouping, kept: the JSON envelope is the importable backup;
  // every other format, and the client-side extras, is a report.
  const backupFormats = formats.filter((format) => format.format === "json");
  const reportFormats = formats.filter((format) => format.format !== "json");

  const startExport = () => {
    if (exportJob.busy || !option) {
      return;
    }
    commit("progress");
    void exportJob.start({
      endpoint: toolExportEndpoint(tool),
      params: {
        ids,
        format: option.format,
        ...option.extraParams,
        ...(Object.keys(filters).length > 0 ? { filters: JSON.stringify(filters) } : {}),
      },
      fallbackFilename: `${option.filenameStem ?? filenameStem}.${option.format}`,
    });
  };

  const formatButton = (format: ExportFormatOption) => (
    <Button
      key={format.labelKey}
      variant="outline"
      className="w-full justify-start"
      onClick={() => {
        if (!seed && (format.format === "json") !== backup) {
          setContent((prev) => forOutput(prev, format.format === "json"));
        }
        setOption(format);
        go(contentFilter ? "content" : "confirm");
      }}
    >
      {t(format.labelKey as never)}
    </Button>
  );

  const stepDescription = {
    format: t("wizard.format.prompt"),
    content: contentFilter ? t(contentFilter.prompt as never) : null,
    confirm: t("wizard.confirm.prompt"),
    progress: null,
  }[step];
  const steps = [...(only ? [] : ["format"]), ...(contentFilter ? ["content"] : []), "confirm"];
  const total = steps.length;
  const position = step === "progress" ? null : steps.indexOf(step) + 1;

  return (
    <WizardDialog
      open={open}
      onOpenChange={onOpenChange}
      className="max-h-[85vh] overflow-y-auto sm:max-w-lg"
      title={t("wizard.titleEntities", { count: ids.length })}
      description={stepDescription}
      progress={position === null ? undefined : { current: position, total }}
      onBack={canGoBack ? back : undefined}
      backLabel={t("wizard.back")}
    >
      {step === "format" && (
        <div className="space-y-4">
          {backupFormats.length > 0 && (
            <div className="space-y-2">
              <p className="font-medium text-muted-foreground text-xs">
                {t("export.headingBackup")}
              </p>
              {backupFormats.map(formatButton)}
            </div>
          )}
          {(reportFormats.length > 0 || extraActions.length > 0) && (
            <div className="space-y-2">
              <p className="font-medium text-muted-foreground text-xs">
                {t("export.headingReport")}
              </p>
              {reportFormats.map(formatButton)}
              {extraActions.map((action) => (
                <Button
                  key={action.labelKey}
                  variant="outline"
                  className="w-full justify-start"
                  onClick={() => {
                    action.onSelect();
                    onOpenChange(false);
                  }}
                >
                  {t(action.labelKey as never)}
                </Button>
              ))}
            </div>
          )}
        </div>
      )}

      {step === "content" && contentFilter && (
        <div className="space-y-4">
          <contentFilter.Field
            value={content}
            onChange={setContent}
            taskStatuses={seed?.taskStatuses}
          />
          <p className="text-muted-foreground text-xs">{t(contentFilter.note as never)}</p>
          <Button className="w-full" onClick={() => go("confirm")}>
            {t("wizard.next")}
          </Button>
        </div>
      )}

      {step === "confirm" && option && (
        <div className="space-y-4">
          <div className="space-y-1 rounded-lg border p-3 text-sm">
            <p className="font-medium">{t(option.labelKey as never)}</p>
            <p className="text-muted-foreground text-xs">
              {t("wizard.confirm.selected", { count: ids.length })}
            </p>
            {Object.keys(filters).length > 0 ? (
              <p className="text-muted-foreground text-xs">
                {describeFilters(tool, filters, content, backup)}
              </p>
            ) : null}
          </div>
          <Button className="w-full" disabled={exportJob.busy} onClick={startExport}>
            {t("wizard.start")}
          </Button>
        </div>
      )}

      {step === "progress" && (
        <ExportProgress
          phase={exportJob.phase}
          inline={exportJob.inline}
          onClose={() => onOpenChange(false)}
        />
      )}
    </WizardDialog>
  );
}

/** The export wizard, for every scope: an initiative, the community, or named
 *  entities of one tool. */
export function ExportWizard({ scope, ...props }: ExportWizardProps) {
  return scope.kind === "entities" ? (
    <EntitiesExportWizard scope={scope} {...props} />
  ) : (
    <AggregateExportWizard scope={scope} {...props} />
  );
}
