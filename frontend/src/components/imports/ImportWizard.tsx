import { SiAtlassian, SiTicktick, SiTodoist, SiVikunja } from "@icons-pack/react-simple-icons";
import { AlertTriangle, CheckCircle2, FileUp, Loader2, XCircle } from "lucide-react";
import {
  type ChangeEvent,
  type ReactNode,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useTranslation } from "react-i18next";

import {
  useCancelImportJob,
  useConfirmImport,
  useImportForeign,
  usePreviewForeignImport,
  useUploadBackup,
} from "@/api/generated/imports/imports";
import type { DataJobRead, ForeignPreview } from "@/api/generated/initiativeAPI.schemas";
import { Tool } from "@/api/generated/initiativeAPI.schemas";
import {
  AtlassianChooseStep,
  type AtlassianConnection,
  AtlassianConnectStep,
  AtlassianExportStep,
  AtlassianFetchingStep,
  AtlassianReviewSummary,
} from "@/components/imports/AtlassianImportSteps";
import { ImportPeopleStep, type PlanPerson } from "@/components/imports/ImportPeopleStep";
import { ImportReport } from "@/components/imports/ImportReport";
import { LogoIcon } from "@/components/LogoIcon";
import { Button } from "@/components/ui/button";
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
import { WizardDialog } from "@/components/ui/wizard-dialog";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { useImportJob } from "@/hooks/useImportJob";
import { liveInitiatives } from "@/hooks/useInitiativeAccess";
import { useInitiatives } from "@/hooks/useInitiatives";
import { useWizard } from "@/hooks/useWizard";
import { BackupPeekError, type PeekedManifest, peekBackupManifest } from "@/lib/backupPeek";
import { getErrorMessage } from "@/lib/errorMessage";
import { formatBytes } from "@/lib/fileUtils";
import { formatDateTime } from "@/lib/formatDate";
import { numberFormat } from "@/lib/intl";
import { toast } from "@/lib/mascotToast";
import { uploadInPieces } from "@/lib/resumableUpload";
import { getItem, removeItem, setItem } from "@/lib/storage";

// Mirrors the backend's IMPORT_MAX_BACKUP_UPLOAD_BYTES — the UX
// layer; the server (ASGI middleware + bounded read) is the enforcement.
const MAX_UPLOAD_BYTES = 268_435_456;

// Mirrors IMPORT_MAX_ENVELOPE_BYTES, for the same reason: a foreign export
// travels as its own text in the request body.
const MAX_FOREIGN_BYTES = 20 * 1024 * 1024;

export interface ImportWizardProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/** Where an import can come from. ``backup`` is this app's own archive; the
 * rest are other products, each read by a mapper on the server that turns
 * the file into the same envelope a project export writes. */
type ForeignSourceKey = "todoist" | "ticktick" | "vikunja";
/** ``atlassian`` reads a site over its API rather than an uploaded file —
 * Jira projects and Confluence spaces in one go: the server fetches, parks
 * the result for review, then applies it like a backup. */
type Source = "backup" | "atlassian" | ForeignSourceKey;

/** Each source's mark on its tile, in its own brand colour. A backup is this
 * app's own archive, so it carries this app's logo. */
const SOURCE_ICONS: Record<Source, ReactNode> = {
  backup: <LogoIcon className="h-8 w-8 shrink-0" aria-hidden="true" focusable="false" />,
  atlassian: <SiAtlassian color="#0052CC" className="h-8 w-8 shrink-0" aria-hidden="true" />,
  todoist: <SiTodoist color="#E44332" className="h-8 w-8 shrink-0" aria-hidden="true" />,
  ticktick: <SiTicktick color="#4772FA" className="h-8 w-8 shrink-0" aria-hidden="true" />,
  vikunja: <SiVikunja color="#196AFF" className="h-8 w-8 shrink-0" aria-hidden="true" />,
};

const SOURCES: Source[] = ["backup", "atlassian", "todoist", "ticktick", "vikunja"];

/** An Atlassian job this wizard started and has not seen the end of. A fetch
 * runs for minutes and outlives the dialog, so reopening picks it up where it
 * is — still reading, or waiting for review — rather than losing it. */
const atlassianJobKey = (communityId: number) => `imports:atlassian-job:${communityId}`;

type Step =
  | "source"
  // Restoring this app's own backup zip.
  | "pick"
  | "peek"
  | "uploading"
  | "plan"
  // Reading another product's export.
  | "file"
  | "choose"
  // Reading an Atlassian site.
  | "connect"
  | "projects"
  | "export"
  | "fetching"
  | "review"
  // Shared tail.
  | "people"
  | "progress"
  | "report";

/** Importing into a community: pick where the work is coming from, then
 * answer that source's own questions.
 *
 * A **backup** is this app's archive going back where it came from — picked,
 * previewed in-browser (the zip's central directory is read locally, nothing
 * uploaded yet), uploaded, planned by the server, confirmed.
 *
 * **Another product's export** is a file the server reads and describes
 * without keeping: it says what is in there, the step after picks which part
 * and where it lands, and the import itself is an ordinary envelope import
 * from that point on.
 *
 * Both rejoin at the same tail — say who the file's people are where it
 * quotes anybody, then watch it run. Closing the dialog after confirm does
 * not cancel the job; the report also lands in the Data tab's jobs table and
 * the inbox notification.
 */
export function ImportWizard({ open, onOpenChange }: ImportWizardProps) {
  const { t, i18n } = useTranslation("imports");
  const percent = numberFormat(i18n.resolvedLanguage ?? i18n.language, {
    style: "percent",
    maximumFractionDigits: 0,
  });
  const communityId = useActiveCommunityId();
  const importJob = useImportJob();

  const { step, go, commit, back, reset } = useWizard<Step>("source");
  const [source, setSource] = useState<Source | null>(null);
  // The file and choose steps are reachable only from a foreign tile, so the
  // one narrowing here spares every read of it below.
  const foreignSource: ForeignSourceKey | null =
    source !== null && source !== "backup" && source !== "atlassian" ? source : null;

  // Backup branch.
  const [file, setFile] = useState<File | null>(null);
  const [peeked, setPeeked] = useState<PeekedManifest | null>(null);

  // Foreign branch.
  const [foreignText, setForeignText] = useState<string>("");
  const [preview, setPreview] = useState<ForeignPreview | null>(null);
  const [selection, setSelection] = useState<string>("");
  const [initiativeId, setInitiativeId] = useState<string>("");

  // Atlassian branch.
  const [jiraConnection, setJiraConnection] = useState<AtlassianConnection | null>(null);
  const [jiraJobId, setJiraJobId] = useState<number | null>(null);
  // Properties unticked on the review: not created when the import runs.
  const [excludedProperties, setExcludedProperties] = useState<Set<string>>(new Set());

  const [pickError, setPickError] = useState<string | null>(null);
  const [stagedJob, setStagedJob] = useState<DataJobRead | null>(null);
  // How much of the backup has arrived, and how to stop it.
  const [sent, setSent] = useState(0);
  const sending = useRef<AbortController | null>(null);
  // Closing the wizard stops a backup still on its way.
  useEffect(() => {
    if (!open) sending.current?.abort();
  }, [open]);
  useEffect(() => () => sending.current?.abort(), []);
  // Source handle → the account picked for it. Seeded from the plan's exact
  // matches; a handle left out of it stays unmapped on purpose.
  const [peopleMap, setPeopleMap] = useState<Record<string, number | null>>({});

  const uploadMutation = useUploadBackup();
  const confirmMutation = useConfirmImport();
  const cancelMutation = useCancelImportJob();
  const previewMutation = usePreviewForeignImport();
  const importMutation = useImportForeign();

  const initiativesQuery = useInitiatives();
  const creatableInitiatives = useMemo(
    () =>
      liveInitiatives(initiativesQuery.data).filter((initiative) =>
        initiative.can.create.includes(Tool.project)
      ),
    [initiativesQuery.data]
  );
  // Where an Atlassian import can land, and what may be made in each: its
  // projects need project creation there, its spaces wiki creation.
  const atlassianTargets = useMemo(
    () =>
      liveInitiatives(initiativesQuery.data).map((initiative) => ({
        id: initiative.id,
        name: initiative.name,
        canCreateProjects: initiative.can.create.includes(Tool.project),
        canCreateWikis: initiative.can.create.includes(Tool.wiki),
      })),
    [initiativesQuery.data]
  );

  // biome-ignore lint/correctness/useExhaustiveDependencies: runs only on open/close; job state is read at that moment
  useEffect(() => {
    if (!open) {
      reset();
      setSource(null);
      setFile(null);
      setPeeked(null);
      setForeignText("");
      setPreview(null);
      setSelection("");
      setInitiativeId("");
      setPickError(null);
      setStagedJob(null);
      setPeopleMap({});
      setJiraConnection(null);
      setJiraJobId(null);
      setExcludedProperties(new Set());
      importJob.reset();
    } else if (importJob.busy) {
      // A job from a previous wizard session is still applying — resume its
      // progress view instead of offering a new flow.
      commit("progress");
    } else {
      const pending = Number(getItem(atlassianJobKey(communityId)));
      if (Number.isFinite(pending) && pending > 0) {
        setSource("atlassian");
        setJiraJobId(pending);
        commit("fetching");
      }
    }
  }, [open]);

  // Seed the mapping from the plan's exact matches, once, when the plan
  // arrives. Only the suggestions: a person the server could not match is
  // left blank for somebody to answer.
  useEffect(() => {
    const suggested = (stagedJob?.plan as { people?: PlanPerson[] } | null)?.people;
    if (!suggested) {
      return;
    }
    setPeopleMap(
      Object.fromEntries(
        suggested
          .filter((person) => person.suggested_user_id != null)
          .map((person) => [person.handle, person.suggested_user_id as number])
      )
    );
  }, [stagedJob]);

  // The poll ending flips progress → report.
  useEffect(() => {
    if (step === "progress" && importJob.terminal != null) {
      commit("report");
    }
  }, [step, importJob.terminal, commit]);

  const chooseSource = (picked: Source) => {
    setSource(picked);
    setPickError(null);
    go(picked === "backup" ? "pick" : picked === "atlassian" ? "connect" : "file");
  };

  const forgetJiraJob = () => removeItem(atlassianJobKey(communityId));

  const handleJiraStarted = (job: DataJobRead) => {
    setItem(atlassianJobKey(communityId), String(job.id));
    setJiraJobId(job.id);
    // Past this point the site is being read; the way out is Cancel.
    commit("fetching");
  };

  const handleJiraStaged = useCallback(
    (job: DataJobRead) => {
      setStagedJob(job);
      commit("review");
    },
    [commit]
  );

  const handleJiraStopped = () => {
    forgetJiraJob();
    setJiraJobId(null);
    setStagedJob(null);
    // The connection is still good for another go, if there is one.
    commit(jiraConnection ? "projects" : "connect");
  };

  const handleFileChange = async (e: ChangeEvent<HTMLInputElement>) => {
    setPickError(null);
    setPeeked(null);
    const picked = e.target.files?.[0];
    if (!picked) {
      return;
    }
    if (picked.size > MAX_UPLOAD_BYTES) {
      setPickError(t("wizard.pick.tooLarge", { limit: formatBytes(MAX_UPLOAD_BYTES) }));
      return;
    }
    try {
      const manifest = await peekBackupManifest(picked);
      setFile(picked);
      setPeeked(manifest);
      go("peek");
    } catch (err) {
      // "not_backup" → wrong/corrupt file; "unreadable" (and any non-peek
      // throw: a DecompressionStream/TextDecoder failure, OOM) → we couldn't
      // read the zip.
      setPickError(
        err instanceof BackupPeekError && err.code === "not_backup"
          ? t("wizard.pick.notZip")
          : t("wizard.pick.readFailed")
      );
    }
  };

  const handleForeignFileChange = async (e: ChangeEvent<HTMLInputElement>) => {
    setPickError(null);
    setPreview(null);
    const picked = e.target.files?.[0];
    if (!picked || !source || source === "backup") {
      return;
    }
    if (picked.size > MAX_FOREIGN_BYTES) {
      setPickError(t("wizard.pick.tooLarge", { limit: formatBytes(MAX_FOREIGN_BYTES) }));
      return;
    }
    let text: string;
    try {
      text = await picked.text();
    } catch {
      setPickError(t("wizard.pick.readFailed"));
      return;
    }
    try {
      const described = await previewMutation.mutateAsync({
        communityId: communityId,
        source,
        data: text,
      });
      if (described.options.length === 0) {
        setPickError(t("wizard.file.nothingInIt"));
        return;
      }
      setForeignText(text);
      setPreview(described);
      // A file holding one thing needs no choice made about it; a file
      // holding several opens on none picked.
      setSelection(described.picks_one ? "" : described.options[0].key);
      setInitiativeId(creatableInitiatives.length === 1 ? String(creatableInitiatives[0].id) : "");
      go("choose");
    } catch (err) {
      setPickError(getErrorMessage(err, "imports:wizard.file.unreadable"));
    }
  };

  const handleUpload = async () => {
    if (!file) {
      return;
    }
    go("uploading");
    sending.current = new AbortController();
    setSent(0);
    try {
      const job = await uploadInPieces(
        communityId,
        file,
        file.name,
        { purpose: "backup" },
        (upload_id) => uploadMutation.mutateAsync({ communityId, data: { upload_id } }),
        {
          signal: sending.current.signal,
          onProgress: (arrived, total) => setSent(total ? arrived / total : 1),
        }
      );
      setStagedJob(job);
      commit("plan");
    } catch (err) {
      // Stopped by closing the wizard: nothing went wrong.
      if (sending.current?.signal.aborted) return;
      toast.error(getErrorMessage(err, "imports:envelope.error"));
      back();
    }
  };

  const handleForeignImport = async () => {
    if (!source || source === "backup" || !initiativeId) {
      return;
    }
    try {
      const response = (await importMutation.mutateAsync({
        communityId: communityId,
        source,
        data: {
          initiative_id: Number(initiativeId),
          selection,
          content: foreignText,
        },
      })) as { result: { entity_title: string; unmatched_handles: string[] } } | DataJobRead;
      // `id` rather than `result`, which a job row also carries (its report):
      // only a job has an id, so that is what tells the two apart.
      if (!("id" in response)) {
        toast.success(t("envelope.success", { name: response.result.entity_title }));
        if (response.result.unmatched_handles.length > 0) {
          toast.warning(
            t("envelope.warningUnmatched", {
              count: response.result.unmatched_handles.length,
              handles: response.result.unmatched_handles.join(", "),
            })
          );
        }
        onOpenChange(false);
        return;
      }
      if (response.status === "staged") {
        // Nothing is imported yet: the server is asking who the file's people
        // are. Hold on the people step rather than reporting a success that
        // has not happened.
        setStagedJob(response);
        go("people");
        return;
      }
      importJob.watch(response.id);
      commit("progress");
    } catch (err) {
      toast.error(getErrorMessage(err, "imports:envelope.error"));
    }
  };

  const handleConfirm = async () => {
    if (!stagedJob) {
      return;
    }
    // Only the rows somebody actually pointed at an account travel. A blank
    // row is an answer — "nobody here" — and saying nothing is how it is said.
    const mapped = Object.fromEntries(Object.entries(peopleMap).filter(([, id]) => id != null));
    try {
      const job = await confirmMutation.mutateAsync({
        communityId: communityId,
        jobId: stagedJob.id,
        data: {
          ...(Object.keys(mapped).length > 0 ? { people_map: mapped } : {}),
          ...(excludedProperties.size > 0 ? { exclude_properties: [...excludedProperties] } : {}),
        },
      });
      // From here the apply is an ordinary job the progress view watches.
      forgetJiraJob();
      importJob.watch(job.id);
      commit("progress");
    } catch (err) {
      toast.error(getErrorMessage(err, "imports:envelope.error"));
    }
  };

  const handleCancelStaged = async () => {
    forgetJiraJob();
    if (!stagedJob) {
      onOpenChange(false);
      return;
    }
    try {
      await cancelMutation.mutateAsync({ communityId: communityId, jobId: stagedJob.id });
    } catch {
      // Already expired/started — nothing to cancel; closing is still right.
    }
    onOpenChange(false);
  };

  const plan = stagedJob?.plan as
    | {
        source_community_name?: string;
        app_version?: string;
        exported_at?: string;
        initiatives?: Array<{
          source_id: number;
          name: string;
          proposed_name: string;
          entry_counts: Record<string, number>;
        }>;
        asset_count?: number;
        asset_bytes?: number;
        skipped?: unknown[];
        unknown_types?: string[];
        people?: PlanPerson[];
      }
    | null
    | undefined;

  const people = plan?.people ?? [];

  const peekSummary = useMemo(() => {
    if (!peeked) {
      return null;
    }
    return {
      communityName: peeked.guild?.name ?? "",
      appVersion: peeked.app_version ?? "",
      exportedAt: formatDateTime(peeked.exported_at),
      initiativeCount: peeked.initiatives?.length ?? 0,
      entryCount: peeked.entries?.length ?? 0,
      assetCount: peeked.assets?.length ?? 0,
      assetBytes: (peeked.assets ?? []).reduce((sum, a) => sum + (a.size_bytes ?? 0), 0),
    };
  }, [peeked]);

  const stepDescriptions: Partial<Record<Step, string>> = {
    source: t("wizard.source.prompt"),
    pick: t("wizard.pick.hint"),
    file: t("wizard.file.hint", { source: t(`wizard.source.names.${source ?? "backup"}`) }),
    choose: t("wizard.choose.prompt"),
    plan: t("wizard.plan.prompt"),
    people: t("wizard.people.prompt"),
    connect: t("wizard.atlassian.connect.prompt"),
    projects: t("wizard.atlassian.choose.prompt"),
    export: t("wizard.atlassian.export.prompt"),
    review: t("wizard.jira.review.prompt"),
  };
  const stepDescription = stepDescriptions[step] ?? null;

  // The questions to answer; the upload, the run and the report are what
  // happens afterwards. The people step appears only where the file quotes
  // somebody — one quoting nobody has nothing to ask about.
  const foreign = source != null && source !== "backup" && source !== "atlassian";
  const total = (foreign ? 3 : 4) + (people.length > 0 ? 1 : 0);
  const position: Record<Step, number | null> = {
    source: 1,
    pick: 2,
    peek: 3,
    uploading: null,
    plan: 4,
    file: 2,
    choose: 3,
    connect: 2,
    projects: 3,
    export: 3,
    fetching: null,
    review: 4,
    people: foreign ? 4 : 5,
    progress: null,
    report: null,
  };
  const current = position[step];

  const canImportForeign =
    initiativeId !== "" && (!preview?.picks_one || selection !== "") && !importMutation.isPending;

  return (
    <WizardDialog
      open={open}
      onOpenChange={onOpenChange}
      className="max-h-[85vh] overflow-y-auto sm:max-w-lg"
      title={t("wizard.title")}
      description={stepDescription}
      progress={current === null ? undefined : { current, total }}
      // Back where it costs nothing: choosing a source again, re-reading a
      // file, or out of the people step. Between the upload and the confirm
      // a job is staged server-side, and the way out of that is Cancel.
      onBack={
        step === "pick" ||
        step === "peek" ||
        step === "file" ||
        step === "choose" ||
        step === "connect" ||
        step === "projects"
          ? back
          : step === "people" && !foreign
            ? back
            : undefined
      }
      backLabel={t("wizard.back")}
    >
      {step === "source" && (
        <div className="grid grid-cols-pair gap-3">
          {SOURCES.map((option) => (
            <button
              key={option}
              type="button"
              onClick={() => chooseSource(option)}
              className="flex cursor-pointer items-start gap-3 rounded-lg border p-4 text-left transition-colors hover:border-primary hover:bg-accent"
            >
              {SOURCE_ICONS[option]}
              <span className="flex-1">
                <span className="block font-medium text-sm">
                  {t(`wizard.source.names.${option}`)}
                </span>
                <span className="block text-muted-foreground text-xs">
                  {t(`wizard.source.descriptions.${option}`)}
                </span>
              </span>
            </button>
          ))}
        </div>
      )}

      {step === "pick" && (
        <div className="space-y-3">
          <label className="flex cursor-pointer flex-col items-center gap-2 rounded-lg border border-dashed p-8 text-center transition-colors hover:bg-accent">
            <FileUp className="h-8 w-8 text-muted-foreground" />
            <span className="font-medium text-sm">{t("wizard.pick.prompt")}</span>
            <input
              type="file"
              accept=".zip,application/zip"
              className="hidden"
              onChange={handleFileChange}
            />
          </label>
          {pickError && <p className="text-destructive text-sm">{pickError}</p>}
        </div>
      )}

      {step === "file" && (
        <div className="space-y-3">
          <label className="flex cursor-pointer flex-col items-center gap-2 rounded-lg border border-dashed p-8 text-center transition-colors hover:bg-accent">
            {previewMutation.isPending ? (
              <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
            ) : (
              <FileUp className="h-8 w-8 text-muted-foreground" />
            )}
            <span className="font-medium text-sm">{t("wizard.file.prompt")}</span>
            <span className="text-muted-foreground text-xs">
              {t(`wizard.file.where.${foreignSource ?? "todoist"}`)}
            </span>
            <input
              type="file"
              accept=".csv,.json,text/csv,application/json"
              className="hidden"
              onChange={handleForeignFileChange}
            />
          </label>
          {source === "todoist" && (
            <p className="flex items-start gap-2 text-muted-foreground text-xs">
              <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              {t("wizard.file.todoistOmitsCompleted")}
            </p>
          )}
          {pickError && <p className="text-destructive text-sm">{pickError}</p>}
        </div>
      )}

      {step === "choose" && preview && (
        <div className="space-y-4">
          {preview.picks_one ? (
            <div className="space-y-2">
              <Label htmlFor="import-selection">{t("wizard.choose.whichLabel")}</Label>
              <Select value={selection} onValueChange={setSelection}>
                <SelectTrigger id="import-selection">
                  <SelectValue placeholder={t("wizard.choose.whichPlaceholder")} />
                </SelectTrigger>
                <SelectContent>
                  {preview.options.map((option) => (
                    <SelectItem key={option.key} value={option.key}>
                      {t("wizard.choose.option", {
                        name: option.name,
                        count: option.task_count,
                      })}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          ) : (
            <div className="space-y-2">
              <Label htmlFor="import-name">{t("wizard.choose.nameLabel")}</Label>
              <Input
                id="import-name"
                value={selection}
                placeholder={t("wizard.choose.namePlaceholder")}
                onChange={(e) => setSelection(e.target.value)}
              />
              <p className="text-muted-foreground text-xs">
                {t("wizard.choose.taskCount", { count: preview.options[0]?.task_count ?? 0 })}
              </p>
            </div>
          )}

          <div className="space-y-2">
            <Label htmlFor="import-initiative">{t("wizard.choose.initiativeLabel")}</Label>
            <Select value={initiativeId} onValueChange={setInitiativeId}>
              <SelectTrigger id="import-initiative">
                <SelectValue placeholder={t("wizard.choose.initiativePlaceholder")} />
              </SelectTrigger>
              <SelectContent>
                {creatableInitiatives.map((initiative) => (
                  <SelectItem key={initiative.id} value={String(initiative.id)}>
                    {initiative.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <p className="text-muted-foreground text-xs">{t("wizard.choose.note")}</p>
          <Button
            className="w-full"
            disabled={!canImportForeign}
            onClick={() => void handleForeignImport()}
          >
            {t("wizard.start")}
          </Button>
        </div>
      )}

      {step === "connect" && (
        <AtlassianConnectStep
          onConnected={(connection) => {
            setJiraConnection(connection);
            go("projects");
          }}
          onUseExport={() => go("export")}
        />
      )}

      {step === "export" && (
        <AtlassianExportStep initiatives={atlassianTargets} onStarted={handleJiraStarted} />
      )}

      {step === "projects" && jiraConnection && (
        <AtlassianChooseStep
          connection={jiraConnection}
          initiatives={atlassianTargets}
          onStarted={handleJiraStarted}
        />
      )}

      {step === "fetching" && jiraJobId != null && (
        <AtlassianFetchingStep
          jobId={jiraJobId}
          onStaged={handleJiraStaged}
          onStopped={handleJiraStopped}
        />
      )}

      {step === "review" && stagedJob && (
        <div className="space-y-4">
          <AtlassianReviewSummary
            job={stagedJob}
            excluded={excludedProperties}
            onExcludedChange={setExcludedProperties}
          />
          <p className="text-muted-foreground text-xs">{t("wizard.jira.review.note")}</p>
          <div className="flex gap-2">
            <Button variant="outline" className="flex-1" onClick={() => void handleCancelStaged()}>
              {t("wizard.cancelUpload")}
            </Button>
            {people.length > 0 ? (
              <Button className="flex-1" onClick={() => go("people")}>
                {t("wizard.next")}
              </Button>
            ) : (
              <Button
                className="flex-1"
                disabled={confirmMutation.isPending}
                onClick={() => void handleConfirm()}
              >
                {t("wizard.start")}
              </Button>
            )}
          </div>
        </div>
      )}

      {step === "peek" && peekSummary && (
        <div className="space-y-4">
          <div className="space-y-1 rounded-lg border p-3 text-sm">
            <p className="font-medium">
              {t("wizard.peek.source", { name: peekSummary.communityName })}
            </p>
            <p className="text-muted-foreground text-xs">
              {t("wizard.peek.exportedAt", {
                date: peekSummary.exportedAt,
                version: peekSummary.appVersion,
              })}
            </p>
            <p className="text-muted-foreground text-xs">
              {t("wizard.peek.initiative", { count: peekSummary.initiativeCount })} ·{" "}
              {t("wizard.peek.entries", { count: peekSummary.entryCount })}
            </p>
            <p className="text-muted-foreground text-xs">
              {peekSummary.assetCount > 0
                ? t("wizard.peek.assets", {
                    count: peekSummary.assetCount,
                    size: formatBytes(peekSummary.assetBytes),
                  })
                : t("wizard.peek.noAssets")}
            </p>
          </div>
          <p className="text-muted-foreground text-xs">{t("wizard.peek.note")}</p>
          <Button className="w-full" onClick={() => void handleUpload()}>
            {t("wizard.upload")}
          </Button>
        </div>
      )}

      {step === "uploading" && (
        <div className="flex flex-col items-center gap-3 py-8">
          <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
          <p className="text-muted-foreground text-sm">{t("wizard.uploading")}</p>
          <Progress value={sent * 100} aria-label={t("wizard.uploading")} />
          <p className="text-muted-foreground text-xs tabular-nums">{percent.format(sent)}</p>
        </div>
      )}

      {step === "plan" && plan && (
        <div className="space-y-4">
          <div className="space-y-2">
            {(plan.initiatives ?? []).map((initiative) => (
              <div key={initiative.source_id} className="space-y-1 rounded-lg border p-3">
                <p className="font-medium text-sm">
                  {t("wizard.plan.willCreate", {
                    name: initiative.name,
                    proposed: initiative.proposed_name,
                  })}
                </p>
                <p className="text-muted-foreground text-xs">
                  {Object.entries(initiative.entry_counts)
                    .map(([tool, count]) => `${tool}: ${count}`)
                    .join(" · ")}
                </p>
              </div>
            ))}
          </div>
          {(plan.skipped?.length ?? 0) > 0 && (
            <p className="flex items-start gap-2 text-muted-foreground text-xs">
              <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              {t("wizard.plan.skipped", { count: plan.skipped?.length ?? 0 })}
            </p>
          )}
          {(plan.unknown_types?.length ?? 0) > 0 && (
            <p className="flex items-start gap-2 text-muted-foreground text-xs">
              <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              {t("wizard.plan.unknownTypes", {
                types: (plan.unknown_types ?? []).join(", "),
              })}
            </p>
          )}
          <p className="text-muted-foreground text-xs">{t("wizard.plan.note")}</p>
          <div className="flex gap-2">
            <Button variant="outline" className="flex-1" onClick={() => void handleCancelStaged()}>
              {t("wizard.cancelUpload")}
            </Button>
            {people.length > 0 ? (
              <Button className="flex-1" onClick={() => go("people")}>
                {t("wizard.next")}
              </Button>
            ) : (
              <Button
                className="flex-1"
                disabled={confirmMutation.isPending}
                onClick={() => void handleConfirm()}
              >
                {t("wizard.start")}
              </Button>
            )}
          </div>
        </div>
      )}

      {step === "people" && (
        <div className="space-y-4">
          <ImportPeopleStep people={people} value={peopleMap} onChange={setPeopleMap} />
          <div className="flex gap-2">
            <Button variant="outline" className="flex-1" onClick={() => void handleCancelStaged()}>
              {t("wizard.cancelUpload")}
            </Button>
            <Button
              className="flex-1"
              disabled={confirmMutation.isPending}
              onClick={() => void handleConfirm()}
            >
              {t("wizard.start")}
            </Button>
          </div>
        </div>
      )}

      {step === "progress" && (
        <div className="flex flex-col items-center gap-3 py-6 text-center">
          <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
          <p className="font-medium text-sm">{t("wizard.progress.title")}</p>
          <p className="text-muted-foreground text-xs">{t("wizard.progress.note")}</p>
          <Button variant="outline" size="sm" onClick={() => onOpenChange(false)}>
            {t("wizard.close")}
          </Button>
        </div>
      )}

      {step === "report" && importJob.terminal && (
        <div className="space-y-4">
          <div className="flex items-center gap-2">
            {importJob.terminal.status === "done" ? (
              <>
                <CheckCircle2 className="h-6 w-6 text-primary" />
                <p className="font-medium">{t("wizard.report.title")}</p>
              </>
            ) : (
              <>
                <XCircle className="h-6 w-6 text-destructive" />
                <p className="font-medium">{t("wizard.report.failedTitle")}</p>
              </>
            )}
          </div>
          <ImportReport job={importJob.terminal} />
          <Button className="w-full" onClick={() => onOpenChange(false)}>
            {t("wizard.close")}
          </Button>
        </div>
      )}
    </WizardDialog>
  );
}
