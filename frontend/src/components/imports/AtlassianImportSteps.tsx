import { AlertTriangle, ExternalLink, FileUp, Loader2 } from "lucide-react";
import { type FormEvent, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { useGetDataJob } from "@/api/generated/data-jobs/data-jobs";
import {
  useCancelImportJob,
  useConnectAtlassian,
  useStartAtlassianImport,
  useStartConfluenceExportImport,
} from "@/api/generated/imports/imports";
import type {
  AtlassianConfluenceSpace,
  AtlassianJiraProject,
  DataJobRead,
} from "@/api/generated/initiativeAPI.schemas";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Progress } from "@/components/ui/progress";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { getErrorCode, getErrorMessage, messageForCode } from "@/lib/errorMessage";
import { formatBytes } from "@/lib/fileUtils";
import { numberFormat } from "@/lib/intl";
import { uploadInPieces } from "@/lib/resumableUpload";

/** Where somebody makes the token the connect step asks for. */
const API_TOKEN_URL = "https://id.atlassian.com/manage-profile/security/api-tokens";

const FETCH_POLL_MS = 2000;

/** Statuses a fetch is still working through. Anything else is an answer:
 * ``staged`` is ready for review, the rest are how it ended. */
const FETCHING = new Set(["queued", "fetching"]);

/** What the site was reached with. Held in memory for the length of the
 * wizard and sent again when the import starts — the job row is what keeps
 * it from there, and nothing here writes it anywhere. */
export interface AtlassianCredentials {
  site_url: string;
  email: string;
  api_token: string;
}

export interface AtlassianConnection {
  credentials: AtlassianCredentials;
  projects: AtlassianJiraProject[];
  spaces: AtlassianConfluenceSpace[];
}

/** The plan's ``atlassian`` block. Declared here for the same reason
 * ``PlanPerson`` is: a job's plan crosses the wire as a free-form object. */
export interface AtlassianPlanSummary {
  projects?: number;
  tasks?: number;
  dropped_nodes?: number;
  skipped_issues?: number;
  unreadable_projects?: string[];
  projects_over_limit?: string[];
  links?: number;
  links_outside_selection?: number;
  properties?: Array<{ name: string; type: string; issue_count: number }>;
  dropped_fields?: string[];
  sprints?: number;
  sprint_calendars?: number;
  sprints_undated?: number;
  sprints_skipped?: string | null;
  comments?: number;
  comments_restricted?: number;
  images?: number;
  image_bytes?: number;
  images_oversize?: number;
  images_unreadable?: number;
  other_attachments?: number;
  files?: number;
  file_bytes?: number;
  cross_links?: number;
  spaces?: number;
  pages?: number;
  page_containers?: number;
  unreadable_spaces?: string[];
  spaces_over_limit?: string[];
  pages_over_limit?: number;
  page_attachments?: number;
  page_images?: number;
  page_files?: number;
  page_attachment_bytes?: number;
  page_attachments_skipped?: number;
  page_files_blocked?: number;
  page_comments?: number;
  page_comments_resolved?: number;
  labels?: number;
  dropped_macros?: Array<{ name: string; count: number }>;
}

export function atlassianSummary(job: DataJobRead | null | undefined): AtlassianPlanSummary {
  const plan = job?.plan as { atlassian?: AtlassianPlanSummary } | null | undefined;
  return plan?.atlassian ?? {};
}

// ---------------------------------------------------------------------------
// Connect
// ---------------------------------------------------------------------------

export interface AtlassianConnectStepProps {
  onConnected: (connection: AtlassianConnection) => void;
  /** Take a Confluence HTML export instead of connecting to a site. */
  onUseExport?: () => void;
}

/** The site, the account, and a token for it — proved by using it. The
 * answer is also the list of what the token can see in both products, so
 * connecting and looking around are one request. */
export function AtlassianConnectStep({ onConnected, onUseExport }: AtlassianConnectStepProps) {
  const { t } = useTranslation("imports");
  const communityId = useActiveCommunityId();
  const connect = useConnectAtlassian();
  const [siteUrl, setSiteUrl] = useState("");
  const [email, setEmail] = useState("");
  const [apiToken, setApiToken] = useState("");
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    try {
      const response = await connect.mutateAsync({
        communityId: communityId,
        data: { site_url: siteUrl.trim(), email: email.trim(), api_token: apiToken },
      });
      const projects = response.jira?.available ? (response.jira.projects ?? []) : [];
      const spaces = response.confluence?.available ? (response.confluence.spaces ?? []) : [];
      if (projects.length === 0 && spaces.length === 0) {
        setError(
          messageForCode(
            response.jira?.reason ?? response.confluence?.reason ?? null,
            "imports:wizard.atlassian.connect.noProducts"
          )
        );
        return;
      }
      onConnected({
        // The site as the server normalised it — what the import will call.
        credentials: { site_url: response.site_url, email: email.trim(), api_token: apiToken },
        projects,
        spaces,
      });
    } catch (err) {
      setError(getErrorMessage(err, "imports:wizard.atlassian.connect.failed"));
    }
  };

  const ready = siteUrl.trim() !== "" && email.trim() !== "" && apiToken !== "";

  return (
    <form className="space-y-4" onSubmit={(event) => void handleSubmit(event)}>
      <div className="space-y-2">
        <Label htmlFor="jira-site">{t("wizard.atlassian.connect.siteLabel")}</Label>
        <Input
          id="jira-site"
          value={siteUrl}
          placeholder={t("wizard.atlassian.connect.sitePlaceholder")}
          autoComplete="url"
          onChange={(event) => setSiteUrl(event.target.value)}
        />
      </div>
      <div className="space-y-2">
        <Label htmlFor="jira-email">{t("wizard.atlassian.connect.emailLabel")}</Label>
        <Input
          id="jira-email"
          type="email"
          value={email}
          autoComplete="email"
          onChange={(event) => setEmail(event.target.value)}
        />
      </div>
      <div className="space-y-2">
        <Label htmlFor="jira-token">{t("wizard.atlassian.connect.tokenLabel")}</Label>
        <Input
          id="jira-token"
          type="password"
          value={apiToken}
          autoComplete="off"
          onChange={(event) => setApiToken(event.target.value)}
        />
        <a
          href={API_TOKEN_URL}
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center gap-1 text-primary text-xs hover:underline"
        >
          {t("wizard.atlassian.connect.tokenLink")}
          <ExternalLink className="h-3 w-3" />
        </a>
      </div>
      <p className="text-muted-foreground text-xs">{t("wizard.atlassian.connect.note")}</p>
      {error && <p className="text-destructive text-sm">{error}</p>}
      <Button type="submit" className="w-full" disabled={!ready || connect.isPending}>
        {connect.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
        {t("wizard.atlassian.connect.submit")}
      </Button>
      {onUseExport && (
        <Button
          type="button"
          variant="link"
          className="h-auto w-full p-0 text-xs"
          onClick={onUseExport}
        >
          {t("wizard.atlassian.export.offer")}
        </Button>
      )}
    </form>
  );
}

// ---------------------------------------------------------------------------
// A Confluence HTML export
// ---------------------------------------------------------------------------

export interface AtlassianExportStepProps {
  initiatives: AtlassianTarget[];
  onStarted: (job: DataJobRead) => void;
}

/** The zip Confluence's space export writes, for a site this server cannot
 * reach or nobody wants to hand a token to. Uploaded, then read the way a
 * site is — the same review follows. */
export function AtlassianExportStep({ initiatives, onStarted }: AtlassianExportStepProps) {
  const { t, i18n } = useTranslation("imports");
  const percent = numberFormat(i18n.resolvedLanguage ?? i18n.language, {
    style: "percent",
    maximumFractionDigits: 0,
  });
  const communityId = useActiveCommunityId();
  const start = useStartConfluenceExportImport();
  // How much of the export has arrived while it is on its way, and how to
  // stop it on leaving.
  const [sent, setSent] = useState<number | null>(null);
  const sending = useRef<AbortController | null>(null);
  useEffect(() => () => sending.current?.abort(), []);
  const [file, setFile] = useState<File | null>(null);
  const [initiativeId, setInitiativeId] = useState<string>("");
  const [includeAttachments, setIncludeAttachments] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const targets = initiatives.filter((initiative) => initiative.canCreateWikis);
  const chosen = targets.some((initiative) => String(initiative.id) === initiativeId)
    ? initiativeId
    : targets.length === 1
      ? String(targets[0].id)
      : "";

  const handleStart = async () => {
    if (!file) return;
    setError(null);
    sending.current = new AbortController();
    setSent(0);
    const initiativeId = Number(chosen);
    try {
      const job = await uploadInPieces(
        communityId,
        file,
        file.name,
        { purpose: "atlassian_export", initiativeId },
        (upload_id) =>
          start.mutateAsync({
            communityId,
            data: {
              initiative_id: initiativeId,
              include_attachments: includeAttachments,
              upload_id,
            },
          }),
        {
          signal: sending.current.signal,
          onProgress: (arrived, total) => setSent(total ? arrived / total : 1),
        }
      );
      onStarted(job);
    } catch (err) {
      if (sending.current?.signal.aborted) return;
      // A zip that is not a space export is a different mistake from a
      // broken backup, and says so.
      setError(
        getErrorCode(err) === "IMPORT_ZIP_INVALID"
          ? t("wizard.atlassian.export.notExport")
          : getErrorMessage(err, "imports:wizard.atlassian.export.failed")
      );
    } finally {
      setSent(null);
    }
  };
  const busy = sent !== null || start.isPending;

  return (
    <div className="space-y-4">
      <label className="flex cursor-pointer flex-col items-center gap-2 rounded-lg border border-dashed p-6 text-center transition-colors hover:bg-accent">
        <FileUp className="h-8 w-8 text-muted-foreground" />
        <span className="font-medium text-sm">
          {file ? file.name : t("wizard.atlassian.export.pick")}
        </span>
        <span className="text-muted-foreground text-xs">{t("wizard.atlassian.export.where")}</span>
        <input
          type="file"
          accept=".zip,application/zip"
          className="hidden"
          aria-label={t("wizard.atlassian.export.pick")}
          onChange={(event) => setFile(event.target.files?.[0] ?? null)}
        />
      </label>

      <div className="space-y-2">
        <Label htmlFor="export-initiative">{t("wizard.choose.initiativeLabel")}</Label>
        <Select value={chosen} onValueChange={setInitiativeId}>
          <SelectTrigger id="export-initiative">
            <SelectValue placeholder={t("wizard.choose.initiativePlaceholder")} />
          </SelectTrigger>
          <SelectContent>
            {targets.map((initiative) => (
              <SelectItem key={initiative.id} value={String(initiative.id)}>
                {initiative.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="flex items-center justify-between gap-3 rounded-lg border p-3">
        <Label htmlFor="export-attachments" className="font-normal text-sm">
          {t("wizard.atlassian.choose.includeAttachments")}
        </Label>
        <Switch
          id="export-attachments"
          checked={includeAttachments}
          onCheckedChange={setIncludeAttachments}
        />
      </div>

      <p className="text-muted-foreground text-xs">{t("wizard.atlassian.export.note")}</p>
      {error && <p className="text-destructive text-sm">{error}</p>}
      {sent !== null && (
        <div className="flex items-center gap-3">
          <Progress value={sent * 100} aria-label={t("wizard.atlassian.choose.submit")} />
          <span className="text-muted-foreground text-xs tabular-nums">{percent.format(sent)}</span>
        </div>
      )}
      <Button
        className="w-full"
        disabled={!file || !chosen || busy}
        onClick={() => void handleStart()}
      >
        {busy && <Loader2 className="h-4 w-4 animate-spin" />}
        {t("wizard.atlassian.choose.submit")}
      </Button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Choose
// ---------------------------------------------------------------------------

/** An initiative the import could land in, and what may be made there. */
export interface AtlassianTarget {
  id: number;
  name: string;
  canCreateProjects: boolean;
  canCreateWikis: boolean;
}

export interface AtlassianChooseStepProps {
  connection: AtlassianConnection;
  initiatives: AtlassianTarget[];
  onStarted: (job: DataJobRead) => void;
}

function useTicks() {
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const toggle = (key: string, on: boolean) =>
    setSelected((current) => {
      const next = new Set(current);
      if (on) {
        next.add(key);
      } else {
        next.delete(key);
      }
      return next;
    });
  return { selected, setSelected, toggle };
}

interface TickListProps {
  label: string;
  idPrefix: string;
  items: Array<{ key: string; name: string; count: string }>;
  selected: Set<string>;
  setSelected: (next: Set<string>) => void;
  toggle: (key: string, on: boolean) => void;
}

function TickList({ label, idPrefix, items, selected, setSelected, toggle }: TickListProps) {
  const { t } = useTranslation("imports");
  const allSelected = items.length > 0 && selected.size === items.length;
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <Label>{label}</Label>
        {items.length > 1 && (
          <Button
            type="button"
            variant="link"
            size="sm"
            className="h-auto p-0 text-xs"
            onClick={() => setSelected(allSelected ? new Set() : new Set(items.map((i) => i.key)))}
          >
            {allSelected
              ? t("wizard.atlassian.choose.selectNone")
              : t("wizard.atlassian.choose.selectAll")}
          </Button>
        )}
      </div>
      <ul className="max-h-48 space-y-1 overflow-y-auto rounded-lg border p-2">
        {items.map((item) => {
          const id = `${idPrefix}-${item.key}`;
          return (
            <li key={item.key} className="flex items-center gap-2 rounded px-1 py-1.5">
              <Checkbox
                id={id}
                checked={selected.has(item.key)}
                onCheckedChange={(checked) => toggle(item.key, checked === true)}
              />
              <Label htmlFor={id} className="flex flex-1 items-baseline gap-2 font-normal">
                <span className="text-sm">{item.name}</span>
                <span className="font-mono text-muted-foreground text-xs">{item.key}</span>
                <span className="ml-auto text-muted-foreground text-xs">{item.count}</span>
              </Label>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

/** Which projects and which spaces, into which initiative, and whether the
 * issues' comments and images come too. Starting reads nothing yet — it
 * queues the one job that reads them all. */
export function AtlassianChooseStep({
  connection,
  initiatives,
  onStarted,
}: AtlassianChooseStepProps) {
  const { t } = useTranslation("imports");
  const communityId = useActiveCommunityId();
  const start = useStartAtlassianImport();
  const projectTicks = useTicks();
  const spaceTicks = useTicks();
  const [initiativeId, setInitiativeId] = useState<string>("");
  const [includeComments, setIncludeComments] = useState(true);
  const [includeAttachments, setIncludeAttachments] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const { projects, spaces } = connection;
  const wantsProjects = projectTicks.selected.size > 0;
  const wantsSpaces = spaceTicks.selected.size > 0;
  // Somewhere everything ticked can go: projects need an initiative that
  // lets this person make projects, spaces one that lets them make wikis.
  const targets = initiatives.filter(
    (initiative) =>
      (initiative.canCreateProjects || initiative.canCreateWikis) &&
      (!wantsProjects || initiative.canCreateProjects) &&
      (!wantsSpaces || initiative.canCreateWikis)
  );
  const chosen = targets.some((initiative) => String(initiative.id) === initiativeId)
    ? initiativeId
    : targets.length === 1
      ? String(targets[0].id)
      : "";

  const handleStart = async () => {
    setError(null);
    try {
      const job = await start.mutateAsync({
        communityId: communityId,
        data: {
          ...connection.credentials,
          initiative_id: Number(chosen),
          // In the order the site listed them, whatever order they were ticked.
          project_keys: projects.map((p) => p.key).filter((key) => projectTicks.selected.has(key)),
          space_keys: spaces.map((s) => s.key).filter((key) => spaceTicks.selected.has(key)),
          include_comments: includeComments,
          include_attachments: includeAttachments,
        },
      });
      onStarted(job);
    } catch (err) {
      setError(getErrorMessage(err, "imports:wizard.atlassian.choose.failed"));
    }
  };

  return (
    <div className="space-y-4">
      {projects.length > 0 && (
        <TickList
          label={t("wizard.atlassian.choose.projectsLabel")}
          idPrefix="jira-project"
          items={projects.map((project) => ({
            key: project.key,
            name: project.name,
            count:
              project.issue_count == null
                ? t("wizard.atlassian.choose.notCounted")
                : t("wizard.atlassian.choose.issues", { count: project.issue_count }),
          }))}
          {...projectTicks}
        />
      )}
      {spaces.length > 0 && (
        <TickList
          label={t("wizard.atlassian.choose.spacesLabel")}
          idPrefix="confluence-space"
          items={spaces.map((space) => ({
            key: space.key,
            name: space.name,
            count:
              space.page_count == null
                ? t("wizard.atlassian.choose.notCounted")
                : t("wizard.atlassian.choose.pages", { count: space.page_count }),
          }))}
          {...spaceTicks}
        />
      )}

      <div className="space-y-2">
        <Label htmlFor="atlassian-initiative">{t("wizard.choose.initiativeLabel")}</Label>
        <Select value={chosen} onValueChange={setInitiativeId}>
          <SelectTrigger id="atlassian-initiative">
            <SelectValue placeholder={t("wizard.choose.initiativePlaceholder")} />
          </SelectTrigger>
          <SelectContent>
            {targets.map((initiative) => (
              <SelectItem key={initiative.id} value={String(initiative.id)}>
                {initiative.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {wantsProjects && wantsSpaces && (
          <p className="text-muted-foreground text-xs">
            {t("wizard.atlassian.choose.initiativeHint")}
          </p>
        )}
      </div>

      <div className="space-y-3 rounded-lg border p-3">
        <div className="flex items-center justify-between gap-3">
          <Label htmlFor="atlassian-comments" className="font-normal text-sm">
            {t("wizard.atlassian.choose.includeComments")}
          </Label>
          <Switch
            id="atlassian-comments"
            checked={includeComments}
            disabled={!wantsProjects && !wantsSpaces}
            onCheckedChange={setIncludeComments}
          />
        </div>
        <div className="flex items-center justify-between gap-3">
          <Label htmlFor="atlassian-attachments" className="font-normal text-sm">
            {t("wizard.atlassian.choose.includeAttachments")}
          </Label>
          <Switch
            id="atlassian-attachments"
            checked={includeAttachments}
            disabled={!wantsProjects && !wantsSpaces}
            onCheckedChange={setIncludeAttachments}
          />
        </div>
      </div>

      <p className="text-muted-foreground text-xs">{t("wizard.atlassian.choose.note")}</p>
      {error && <p className="text-destructive text-sm">{error}</p>}
      <Button
        className="w-full"
        disabled={(!wantsProjects && !wantsSpaces) || chosen === "" || start.isPending}
        onClick={() => void handleStart()}
      >
        {t("wizard.atlassian.choose.submit")}
      </Button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Fetching
// ---------------------------------------------------------------------------

export interface AtlassianFetchingStepProps {
  jobId: number;
  /** The site has been read and the job is waiting for review. */
  onStaged: (job: DataJobRead) => void;
  /** The fetch is over without a bundle — cancelled, or failed and dismissed. */
  onStopped: () => void;
}

/** The worker reading the site. Counts climb as each project is read; the
 * job keeps going if the dialog is closed, and the wizard picks it up again
 * when it is reopened. */
export function AtlassianFetchingStep({ jobId, onStaged, onStopped }: AtlassianFetchingStepProps) {
  const { t } = useTranslation("imports");
  const communityId = useActiveCommunityId();
  const cancel = useCancelImportJob();
  const jobQuery = useGetDataJob(communityId, jobId, {
    query: {
      refetchInterval: (query) =>
        FETCHING.has(query.state.data?.status ?? "queued") ? FETCH_POLL_MS : false,
    },
  });
  const job = jobQuery.data;

  useEffect(() => {
    if (job?.status === "staged") {
      onStaged(job);
    }
  }, [job, onStaged]);

  const handleCancel = async () => {
    try {
      await cancel.mutateAsync({ communityId: communityId, jobId });
    } catch {
      // Already over; stopping is still the right answer.
    }
    onStopped();
  };

  if (job && !FETCHING.has(job.status) && job.status !== "staged") {
    return (
      <div className="space-y-4">
        <div className="flex items-start gap-2 text-sm">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-destructive" />
          <p>
            {job.status === "failed"
              ? messageForCode(job.error, "imports:wizard.atlassian.fetch.failed")
              : t("wizard.atlassian.fetch.stopped")}
          </p>
        </div>
        <Button className="w-full" variant="outline" onClick={onStopped}>
          {t("wizard.atlassian.fetch.startOver")}
        </Button>
      </div>
    );
  }

  const summary = atlassianSummary(job);
  return (
    <div className="flex flex-col items-center gap-3 py-6 text-center">
      <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      <p className="font-medium text-sm">{t("wizard.atlassian.fetch.title")}</p>
      <p className="text-muted-foreground text-xs">
        {t("wizard.atlassian.fetch.progress", {
          projects: summary.projects ?? 0,
          tasks: summary.tasks ?? 0,
          spaces: summary.spaces ?? 0,
          pages: summary.pages ?? 0,
        })}
      </p>
      <p className="text-muted-foreground text-xs">{t("wizard.atlassian.fetch.note")}</p>
      <Button variant="outline" size="sm" onClick={() => void handleCancel()}>
        {t("wizard.atlassian.fetch.cancel")}
      </Button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Review
// ---------------------------------------------------------------------------

export interface JiraReviewSummaryProps {
  job: DataJobRead;
  /** Property names unticked so far. */
  excluded: Set<string>;
  onExcludedChange: (next: Set<string>) => void;
}

/** What the fetch found, before anything is written: what will arrive, and —
 * said as plainly — what will not. Each property the import would add to the
 * initiative can be unticked here; an unticked one is not created, and no
 * task carries its values. */
export function JiraReviewSummary({ job, excluded, onExcludedChange }: JiraReviewSummaryProps) {
  const { t } = useTranslation("imports");
  const summary = atlassianSummary(job);
  const properties = summary.properties ?? [];

  const arriving = [
    t("wizard.jira.review.tasks", { count: summary.tasks ?? 0, projects: summary.projects ?? 0 }),
    (summary.links ?? 0) > 0 ? t("wizard.jira.review.links", { count: summary.links }) : null,
    (summary.comments ?? 0) > 0
      ? t("wizard.jira.review.comments", { count: summary.comments })
      : null,
    (summary.images ?? 0) > 0
      ? t("wizard.jira.review.images", {
          count: summary.images,
          size: formatBytes(summary.image_bytes ?? 0),
        })
      : null,
    (summary.files ?? 0) > 0
      ? t("wizard.jira.review.files", {
          count: summary.files,
          size: formatBytes(summary.file_bytes ?? 0),
        })
      : null,
    (summary.sprint_calendars ?? 0) > 0
      ? t("wizard.jira.review.sprints", {
          count: (summary.sprints ?? 0) - (summary.sprints_undated ?? 0),
          calendars: summary.sprint_calendars,
        })
      : null,
  ].filter((line): line is string => line !== null);

  const leftBehind = [
    (summary.unreadable_projects?.length ?? 0) > 0
      ? t("wizard.jira.review.unreadableProjects", {
          keys: (summary.unreadable_projects ?? []).join(", "),
        })
      : null,
    (summary.projects_over_limit?.length ?? 0) > 0
      ? t("wizard.jira.review.projectsOverLimit", {
          keys: (summary.projects_over_limit ?? []).join(", "),
        })
      : null,
    summary.sprints_skipped && (summary.sprints ?? 0) > 0
      ? t("wizard.jira.review.sprintsSkipped", {
          count: summary.sprints,
          reason: messageForCode(summary.sprints_skipped, "imports:wizard.jira.review.noCalendar"),
        })
      : null,
    (summary.sprints_undated ?? 0) > 0 && !summary.sprints_skipped
      ? t("wizard.jira.review.sprintsUndated", { count: summary.sprints_undated })
      : null,
    (summary.links_outside_selection ?? 0) > 0
      ? t("wizard.jira.review.linksOutside", { count: summary.links_outside_selection })
      : null,
    (summary.comments_restricted ?? 0) > 0
      ? t("wizard.jira.review.commentsRestricted", { count: summary.comments_restricted })
      : null,
    (summary.images_oversize ?? 0) + (summary.images_unreadable ?? 0) > 0
      ? t("wizard.jira.review.imagesSkipped", {
          count: (summary.images_oversize ?? 0) + (summary.images_unreadable ?? 0),
        })
      : null,
    (summary.other_attachments ?? 0) > 0
      ? t("wizard.jira.review.otherAttachments", { count: summary.other_attachments })
      : null,
    (summary.dropped_fields?.length ?? 0) > 0
      ? t("wizard.jira.review.droppedFields", {
          fields: (summary.dropped_fields ?? []).join(", "),
        })
      : null,
    (summary.skipped_issues ?? 0) > 0
      ? t("wizard.jira.review.skippedIssues", { count: summary.skipped_issues })
      : null,
  ].filter((line): line is string => line !== null);

  return (
    <div className="space-y-4">
      <ul className="space-y-1 rounded-lg border p-3 text-sm">
        {arriving.map((line) => (
          <li key={line}>{line}</li>
        ))}
      </ul>

      {properties.length > 0 && (
        <div className="space-y-1">
          <p className="font-medium text-sm">{t("wizard.jira.review.propertiesTitle")}</p>
          <p className="text-muted-foreground text-xs">{t("wizard.jira.review.propertiesHint")}</p>
          <ul className="max-h-48 space-y-0.5 overflow-y-auto rounded-lg border p-2 text-xs">
            {properties.map((property) => {
              const id = `jira-property-${property.name}`;
              return (
                <li key={property.name} className="flex items-center gap-2 rounded px-1 py-1">
                  <Checkbox
                    id={id}
                    checked={!excluded.has(property.name)}
                    onCheckedChange={(checked) => {
                      const next = new Set(excluded);
                      if (checked === true) {
                        next.delete(property.name);
                      } else {
                        next.add(property.name);
                      }
                      onExcludedChange(next);
                    }}
                  />
                  <Label htmlFor={id} className="flex flex-1 justify-between gap-2 font-normal">
                    <span className="text-xs">{property.name}</span>
                    <span className="text-muted-foreground text-xs">
                      {t("wizard.jira.review.propertyCount", { count: property.issue_count })}
                    </span>
                  </Label>
                </li>
              );
            })}
          </ul>
        </div>
      )}

      {leftBehind.length > 0 && (
        <div className="space-y-1">
          <p className="font-medium text-sm">{t("wizard.jira.review.leftBehindTitle")}</p>
          <ul className="space-y-1">
            {leftBehind.map((line) => (
              <li key={line} className="flex items-start gap-2 text-muted-foreground text-xs">
                <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                {line}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

/** What reading the spaces found, before anything is written: the pages
 * arriving, and what they held that will not. */
export function ConfluenceReviewSummary({ job }: { job: DataJobRead }) {
  const { t } = useTranslation("imports");
  const summary = atlassianSummary(job);

  const arriving = [
    t("wizard.confluence.review.pages", {
      count: summary.pages ?? 0,
      spaces: summary.spaces ?? 0,
    }),
    (summary.page_containers ?? 0) > 0
      ? t("wizard.confluence.review.containers", { count: summary.page_containers })
      : null,
    (summary.labels ?? 0) > 0
      ? t("wizard.confluence.review.labels", { count: summary.labels })
      : null,
    (summary.page_comments ?? 0) > 0
      ? t("wizard.confluence.review.comments", { count: summary.page_comments })
      : null,
    (summary.page_images ?? 0) + (summary.page_files ?? 0) > 0
      ? t("wizard.confluence.review.attachmentsArriving", {
          count: (summary.page_images ?? 0) + (summary.page_files ?? 0),
          size: formatBytes(summary.page_attachment_bytes ?? 0),
        })
      : null,
  ].filter((line): line is string => line !== null);

  const dropped = summary.dropped_macros ?? [];
  const leftBehind = [
    (summary.unreadable_spaces?.length ?? 0) > 0
      ? t("wizard.confluence.review.unreadableSpaces", {
          keys: (summary.unreadable_spaces ?? []).join(", "),
        })
      : null,
    (summary.spaces_over_limit?.length ?? 0) > 0
      ? t("wizard.confluence.review.spacesOverLimit", {
          keys: (summary.spaces_over_limit ?? []).join(", "),
        })
      : null,
    (summary.pages_over_limit ?? 0) > 0
      ? t("wizard.confluence.review.overLimit", { count: summary.pages_over_limit })
      : null,
    (summary.page_attachments ?? 0) > 0
      ? t("wizard.confluence.review.attachments", { count: summary.page_attachments })
      : null,
    (summary.page_comments_resolved ?? 0) > 0
      ? t("wizard.confluence.review.commentsResolved", {
          count: summary.page_comments_resolved,
        })
      : null,
    (summary.page_attachments_skipped ?? 0) > 0
      ? t("wizard.confluence.review.attachmentsSkipped", {
          count: summary.page_attachments_skipped,
        })
      : null,
    (summary.page_files_blocked ?? 0) > 0
      ? t("wizard.confluence.review.filesBlocked", { count: summary.page_files_blocked })
      : null,
    dropped.length > 0
      ? t("wizard.confluence.review.dropped", {
          items: dropped.map((item) => `${item.name} ×${item.count}`).join(", "),
        })
      : null,
  ].filter((line): line is string => line !== null);

  return (
    <div className="space-y-4">
      <ul className="space-y-1 rounded-lg border p-3 text-sm">
        {arriving.map((line) => (
          <li key={line}>{line}</li>
        ))}
      </ul>
      {leftBehind.length > 0 && (
        <div className="space-y-1">
          <p className="font-medium text-sm">{t("wizard.jira.review.leftBehindTitle")}</p>
          <ul className="space-y-1">
            {leftBehind.map((line) => (
              <li key={line} className="flex items-start gap-2 text-muted-foreground text-xs">
                <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                {line}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

/** The review for a whole Atlassian import: what each product brings and
 * leaves behind, and how many links between the two will be joined up. */
export function AtlassianReviewSummary({
  job,
  excluded,
  onExcludedChange,
}: JiraReviewSummaryProps) {
  const { t } = useTranslation("imports");
  const summary = atlassianSummary(job);
  const readJira = (summary.projects ?? 0) > 0 || (summary.unreadable_projects?.length ?? 0) > 0;
  const readConfluence = (summary.spaces ?? 0) > 0 || (summary.unreadable_spaces?.length ?? 0) > 0;
  return (
    <div className="space-y-4">
      {readJira && (
        <JiraReviewSummary job={job} excluded={excluded} onExcludedChange={onExcludedChange} />
      )}
      {readConfluence && <ConfluenceReviewSummary job={job} />}
      {(summary.cross_links ?? 0) > 0 && (
        <p className="text-sm">
          {t("wizard.atlassian.crossLinks", { count: summary.cross_links })}
        </p>
      )}
    </div>
  );
}
