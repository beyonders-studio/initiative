import { type ChangeEvent, type FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  useCancelImportJob,
  useConfirmImport,
  useImportEnvelope,
  useImportEnvelopeArchive,
} from "@/api/generated/imports/imports";
import type { DataJobRead, Tool } from "@/api/generated/initiativeAPI.schemas";
import { invalidate, q } from "@/api/query-keys";
import { ImportPeopleStep, type PlanPerson } from "@/components/imports/ImportPeopleStep";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { useAppConfig } from "@/hooks/useAppConfig";
import { liveInitiatives } from "@/hooks/useInitiativeAccess";
import { useInitiatives } from "@/hooks/useInitiatives";
import { getErrorMessage } from "@/lib/errorMessage";
import { toast } from "@/lib/mascotToast";
import { toolEnvelopeType, toolForEnvelopeType } from "@/lib/tools";

// The real upload cap is server-owned and arrives via /api/v1/config
// (max_upload_bytes). Until it has loaded, file.text()/JSON.parse below still
// need SOME bound to run safely in the browser — this deliberately
// conservative degraded-mode budget covers that window. It is not a copy of
// the server limit and must stay well below any plausible value of it.
const DEGRADED_PARSE_BUDGET_BYTES = 10 * 1024 * 1024;

/** Whether a picked file is a zipped export rather than a bare envelope. */
const isZip = (file: File): boolean =>
  file.type === "application/zip" ||
  file.type === "application/x-zip-compressed" ||
  file.name.toLowerCase().endsWith(".zip");

interface ParsedEnvelope {
  type?: string;
  kind?: string;
  title?: string;
  name?: string;
  file_type?: string;
  schema_version?: number;
}

export interface EnvelopeImportDialogProps {
  /** The tool whose list page opened this dialog — the file's envelope type
   * must match, and the initiative picker is scoped to this tool's create
   * permission. */
  tool: Tool;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** When set (inside an initiative tab), the target is fixed and the picker
   * is hidden. */
  fixedInitiativeId?: number;
  onImported?: () => void;
}

/** Generic single-envelope import — the file's ``type`` selects the backend
 * importer; this dialog validates it matches ``tool``, previews it, and posts
 * to /imports/envelope. Generalizes the old ProjectImportDialog for every
 * importable tool.
 *
 * An export that travels with its files — a wiki and what is filed in it — is a
 * zip. That is sent as it is to /imports/envelope/archive, which reads it and
 * says whether it belongs to this tool; there is nothing to preview in the
 * browser without unpacking it.
 *
 * Usually one step. The second appears only when the server stages the job
 * instead of applying it, which it does when the file quotes somebody nobody
 * here can be sure of: then this asks who those people are and confirms with
 * the answers. A file that names nobody — or whose every handle matches a
 * member exactly — still imports on one click, because a confirm screen
 * nobody would change is not a step. */
export function EnvelopeImportDialog({
  tool,
  open,
  onOpenChange,
  fixedInitiativeId,
  onImported,
}: EnvelopeImportDialogProps) {
  const { t } = useTranslation(["imports", "common"]);
  const communityId = useActiveCommunityId();
  const { maxUploadBytes } = useAppConfig();
  const initiativesQuery = useInitiatives();

  const [envelope, setEnvelope] = useState<ParsedEnvelope | null>(null);
  // A zipped export, sent as it is rather than read here.
  const [archive, setArchive] = useState<File | null>(null);
  const [parseError, setParseError] = useState<string | null>(null);
  const [initiativeId, setInitiativeId] = useState<string | null>(
    fixedInitiativeId != null ? String(fixedInitiativeId) : null
  );
  const [fileName, setFileName] = useState("");
  // The job the server parked to ask about its people, if it did. Null is the
  // ordinary case: the import already happened.
  const [stagedJob, setStagedJob] = useState<DataJobRead | null>(null);
  // Source handle → the account picked for it, seeded from the plan's exact
  // matches. A handle left out stays unmapped on purpose.
  const [peopleMap, setPeopleMap] = useState<Record<string, number | null>>({});
  // Bumped on each file pick; an async read that finishes after a newer pick
  // started must not stamp its (stale) result onto the input.
  const readGeneration = useRef(0);

  const importMutation = useImportEnvelope();
  const archiveMutation = useImportEnvelopeArchive();
  const confirmMutation = useConfirmImport();
  const cancelMutation = useCancelImportJob();

  const people = useMemo(
    () => ((stagedJob?.plan as { people?: PlanPerson[] } | null)?.people ?? []) as PlanPerson[],
    [stagedJob]
  );

  const creatableInitiatives = useMemo(() => {
    if (fixedInitiativeId != null || !initiativesQuery.data) {
      return [];
    }
    return liveInitiatives(initiativesQuery.data).filter((initiative) =>
      initiative.can.create.includes(tool)
    );
  }, [fixedInitiativeId, initiativesQuery.data, tool]);

  useEffect(() => {
    if (open) {
      setInitiativeId(
        fixedInitiativeId != null
          ? String(fixedInitiativeId)
          : creatableInitiatives.length === 1
            ? String(creatableInitiatives[0].id)
            : null
      );
    } else {
      setEnvelope(null);
      setArchive(null);
      setParseError(null);
      setFileName("");
      setStagedJob(null);
      setPeopleMap({});
    }
  }, [open, fixedInitiativeId, creatableInitiatives]);

  // Seed the mapping from the plan's exact matches, once, when a job is
  // staged. Only the suggestions: a person the server could not place is left
  // blank for somebody to answer.
  useEffect(() => {
    setPeopleMap(
      Object.fromEntries(
        people
          .filter((person) => person.suggested_user_id != null)
          .map((person) => [person.handle, person.suggested_user_id as number])
      )
    );
  }, [people]);

  const handleFileChange = async (e: ChangeEvent<HTMLInputElement>) => {
    const generation = ++readGeneration.current;
    // Only write state if this is still the most recent pick — a slower read
    // of an earlier file must not clobber a newer selection's result.
    const isStale = () => generation !== readGeneration.current;
    setParseError(null);
    setEnvelope(null);
    setArchive(null);
    const file = e.target.files?.[0];
    if (!file) {
      setFileName("");
      return;
    }
    if (isZip(file)) {
      // The server holds the size limit for zips and reads them itself.
      setFileName(file.name);
      setArchive(file);
      return;
    }
    // Guard the fully client-side file.text()/JSON.parse below. The server's
    // cap applies once known; before then the conservative degraded budget
    // holds, and an over-budget file gets the "limits couldn't load" message
    // rather than a misleading "too large".
    const parseLimit = maxUploadBytes ?? DEGRADED_PARSE_BUDGET_BYTES;
    if (file.size > parseLimit) {
      setFileName(file.name);
      setParseError(
        t(
          maxUploadBytes === null
            ? "imports:envelope.limitUnavailable"
            : "imports:envelope.fileTooLarge"
        )
      );
      return;
    }
    setFileName(file.name);
    try {
      const text = await file.text();
      if (isStale()) {
        return;
      }
      const parsed = JSON.parse(text) as ParsedEnvelope;
      const type = parsed.type ?? parsed.kind;
      if (!type) {
        setParseError(t("imports:envelope.parseError"));
        return;
      }
      const fileTool = toolForEnvelopeType(type);
      if (fileTool == null) {
        setParseError(t("imports:envelope.parseError"));
        return;
      }
      if (fileTool !== tool) {
        // Right kind of file, wrong tool page — point the user at the right one.
        setParseError(t("imports:envelope.wrongTool", { type: fileTool }));
        return;
      }
      setEnvelope(parsed);
    } catch {
      if (isStale()) {
        return;
      }
      setParseError(t("imports:envelope.parseError"));
    }
  };

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if ((!envelope && !archive) || !initiativeId) {
      return;
    }
    try {
      const response = (
        archive
          ? await archiveMutation.mutateAsync({
              communityId: communityId,
              data: {
                file: archive,
                initiative_id: Number(initiativeId),
                envelope_type: toolEnvelopeType(tool),
              },
            })
          : await importMutation.mutateAsync({
              communityId: communityId,
              data: {
                envelope: envelope as unknown as Record<string, unknown>,
                initiative_id: Number(initiativeId),
              },
            })
      ) as { result: { entity_title: string; unmatched_handles: string[] } } | DataJobRead;
      // `id` rather than `result`, which a job row also carries (its report):
      // only a job has an id, so that is what tells the two apart.
      if (!("id" in response)) {
        toast.success(t("imports:envelope.success", { name: response.result.entity_title }));
        if (response.result.unmatched_handles.length > 0) {
          toast.warning(
            t("imports:envelope.warningUnmatched", {
              count: response.result.unmatched_handles.length,
              handles: response.result.unmatched_handles.join(", "),
            })
          );
        }
      } else if (response.status === "staged") {
        // Nothing has been imported yet: the server is asking who the file's
        // people are. Hold the dialog open on the second step instead of
        // reporting a success that has not happened.
        setStagedJob(response);
        return;
      } else {
        toast.success(t("imports:envelope.queued"));
      }
      finish();
    } catch (err) {
      toast.error(getErrorMessage(err, "imports:envelope.error"));
    }
  };

  /** Close out a finished (or started) import: refresh the tool's lists and
   * let the page know. */
  const finish = () => {
    void invalidate(q.toolList(tool));
    onOpenChange(false);
    onImported?.();
  };

  const handleConfirm = async () => {
    if (!stagedJob) {
      return;
    }
    // Only the rows somebody actually pointed at an account travel. A blank
    // row is an answer — "nobody here" — and saying nothing is how it is said.
    const mapped = Object.fromEntries(Object.entries(peopleMap).filter(([, id]) => id != null));
    try {
      await confirmMutation.mutateAsync({
        communityId: communityId,
        jobId: stagedJob.id,
        data: Object.keys(mapped).length > 0 ? { people_map: mapped } : {},
      });
      toast.success(t("imports:envelope.queued"));
      finish();
    } catch (err) {
      toast.error(getErrorMessage(err, "imports:envelope.error"));
    }
  };

  /** Back out of the people step. The file is already staged server-side, so
   * the way out is to delete the job rather than to un-ask the question. */
  const handleDiscard = async () => {
    if (stagedJob) {
      try {
        await cancelMutation.mutateAsync({ communityId: communityId, jobId: stagedJob.id });
      } catch {
        // Already expired or started — nothing to cancel, and closing is
        // still the right thing to do.
      }
    }
    onOpenChange(false);
  };

  const isSubmitting = importMutation.isPending || archiveMutation.isPending;
  const canSubmit = (!!envelope || !!archive) && !!initiativeId && !isSubmitting;
  // Every tool's envelope names its entity `name`; file exports taken
  // before the rename spelled it `title`, which the server still accepts.
  const envelopeTitle = envelope?.name ?? envelope?.title ?? "";

  if (stagedJob) {
    return (
      <Dialog
        open={open}
        onOpenChange={(next) => (next ? onOpenChange(true) : void handleDiscard())}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("imports:envelope.title")}</DialogTitle>
            <DialogDescription>{t("imports:wizard.people.prompt")}</DialogDescription>
          </DialogHeader>
          <ImportPeopleStep people={people} value={peopleMap} onChange={setPeopleMap} />
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => void handleDiscard()}
              disabled={confirmMutation.isPending}
            >
              {t("common:cancel")}
            </Button>
            <Button
              type="button"
              onClick={() => void handleConfirm()}
              disabled={confirmMutation.isPending}
            >
              {confirmMutation.isPending
                ? t("imports:envelope.importing")
                : t("imports:envelope.importButton")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    );
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("imports:envelope.title")}</DialogTitle>
          <DialogDescription>{t("imports:envelope.description")}</DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="envelope-import-file">{t("imports:envelope.selectFile")}</Label>
            <input
              id="envelope-import-file"
              type="file"
              accept=".json,.zip,application/json,application/zip"
              onChange={handleFileChange}
              className="block w-full text-sm"
            />
            {fileName && !parseError ? (
              <p className="text-muted-foreground text-xs">{fileName}</p>
            ) : null}
            {parseError ? <p className="text-destructive text-sm">{parseError}</p> : null}
          </div>

          {envelope ? (
            <div className="rounded-md bg-muted p-3 text-sm">
              {t("imports:envelope.preview", {
                title: envelopeTitle,
                type: toolEnvelopeType(tool),
              })}
            </div>
          ) : archive ? (
            <div className="rounded-md bg-muted p-3 text-sm">
              {t("imports:envelope.archivePreview")}
            </div>
          ) : null}

          {fixedInitiativeId == null && (
            <div className="space-y-2">
              <Label htmlFor="envelope-import-initiative">
                {t("imports:envelope.targetInitiative")}
              </Label>
              <Select
                value={initiativeId ?? undefined}
                onValueChange={(value) => setInitiativeId(value)}
              >
                <SelectTrigger id="envelope-import-initiative">
                  <SelectValue placeholder={t("imports:envelope.selectInitiative")} />
                </SelectTrigger>
                <SelectContent>
                  {creatableInitiatives.map((init) => (
                    <SelectItem key={init.id} value={String(init.id)}>
                      {init.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}

          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
              disabled={isSubmitting}
            >
              {t("common:cancel")}
            </Button>
            <Button type="submit" disabled={!canSubmit}>
              {isSubmitting ? t("imports:envelope.importing") : t("imports:envelope.importButton")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
