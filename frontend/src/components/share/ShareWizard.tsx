import { FileUp, Loader2, type LucideIcon, ScrollText, X } from "lucide-react";
import { type FormEvent, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { invalidate, q } from "@/api/query-keys";
import { ProjectPickerStep } from "@/components/tasks/ProjectPickerStep";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { WizardFrame } from "@/components/ui/wizard-dialog";
import { useApiMutation } from "@/hooks/useApiMutation";
import { useCommunityInitiativeSteps } from "@/hooks/useCommunityInitiativeSteps";
import { useServer } from "@/hooks/useServer";
import { fileIcon } from "@/lib/fileIcon";
import { hasReservedSigil } from "@/lib/mentions";
import {
  type LandShareInput,
  landShare,
  type ShareDestination,
  type ShareKind,
  type ShareUpload,
  sharedFileSrc,
  uploadName,
} from "@/lib/share/landShare";
import { isImage, type ReceivedShare, type SharedFile } from "@/lib/share/pendingShare";
import { shareNote, shareTitle } from "@/lib/share/shareContent";
import { getItem, setItem } from "@/lib/storage";
import { TOOL_ICONS } from "@/lib/tools";
import { cn } from "@/lib/utils";

const STORAGE_KEY = "initiative-last-share-destination";

type LastUsed = Partial<Record<ShareKind, ShareDestination>>;

// Kept per server: the app talks to more than one, and a community's id on one
// names something else, or nothing, on the next.
function loadAll(): Record<string, LastUsed> {
  try {
    const raw = getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as Record<string, LastUsed>) : {};
  } catch {
    return {};
  }
}

function loadLastUsed(server: string): LastUsed {
  return loadAll()[server] ?? {};
}

function rememberDestination(server: string, kind: ShareKind, destination: ShareDestination) {
  const all = loadAll();
  setItem(
    STORAGE_KEY,
    JSON.stringify({ ...all, [server]: { ...all[server], [kind]: destination } })
  );
}

const KINDS: { kind: ShareKind; icon: LucideIcon }[] = [
  { kind: "task", icon: TOOL_ICONS[Tool.project] },
  { kind: "file", icon: ScrollText },
  { kind: "upload", icon: FileUp },
  { kind: "post", icon: TOOL_ICONS[Tool.post] },
];

/** The tool a kind is authored as: a task is content of a project, so none. */
const AUTHORS: Record<ShareKind, Tool | null> = {
  task: null,
  file: Tool.file,
  upload: Tool.file,
  post: Tool.post,
};

/** What a share offers to become: an upload needs files, the rest something to say. */
function offeredKinds(share: ReceivedShare): ShareKind[] {
  const hasContent =
    !!share.title || share.texts.length > 0 || share.files.some((file) => isImage(file));
  return KINDS.map(({ kind }) => kind).filter((kind) =>
    kind === "upload" ? share.files.length > 0 : hasContent
  );
}

interface ShareWizardProps {
  share: ReceivedShare;
  /** The share is done with: made into what `path` addresses, or put down. */
  onDone: (path?: string) => void;
}

/**
 * Makes a share into a task, a document, an uploaded file or a post: what it
 * becomes, then where, then a last look at what it will be called before it
 * is made.
 */
export function ShareWizard({ share, onDone }: ShareWizardProps) {
  const { t } = useTranslation(["share", "errors"]);

  const [kind, setKind] = useState<ShareKind | null>(null);
  const [destination, setDestination] = useState<ShareDestination | null>(null);
  const initialTitle = useMemo(
    () =>
      shareTitle(share, share.files.every(isImage) ? t("fallbackTitle") : t("fallbackFileTitle")),
    [share, t]
  );
  const [title, setTitle] = useState(initialTitle);
  const [note, setNote] = useState(() => shareNote(share, initialTitle));
  const [files, setFiles] = useState(share.files);
  const [names, setNames] = useState<Record<string, string>>(() =>
    Object.fromEntries(share.files.map((file) => [file.uri, uploadName(file)]))
  );
  const images = files.filter(isImage);
  const leftOut = files.length - images.length;
  const kinds = useMemo(() => offeredKinds(share), [share]);
  const removeFile = (file: SharedFile) =>
    setFiles((current) => current.filter((other) => other !== file));
  const { serverUrl, getServerOrigin } = useServer();
  const server = serverUrl ?? getServerOrigin() ?? "";
  const lastUsed = useMemo(() => (kind ? loadLastUsed(server)[kind] : undefined), [kind, server]);

  const steps = useCommunityInitiativeSteps<"select-project">({
    ns: "share",
    open: kind !== null,
    authors: kind ? AUTHORS[kind] : null,
    shortcut: lastUsed
      ? {
          title: lastUsed.projectName ?? lastUsed.initiativeName,
          subtitle: lastUsed.projectName
            ? `${lastUsed.communityName} > ${lastUsed.initiativeName}`
            : lastUsed.communityName,
          onClick: () => setDestination(lastUsed),
        }
      : null,
    onInitiative: (community, initiative) => {
      if (kind === "task") return;
      setDestination({
        communityId: community.id,
        communityName: community.name,
        initiativeId: initiative.id,
        initiativeName: initiative.name,
      });
    },
    next:
      kind === "task"
        ? { step: "select-project", description: t("createWizard.selectProject") }
        : undefined,
  });
  const { community, initiative } = steps;

  const land = useApiMutation<string, LandShareInput>(
    {
      mutationFn: landShare,
      invalidate: (_path, input) =>
        invalidate(
          input.kind === "task"
            ? q.allTasks()
            : q.toolList(input.kind === "post" ? Tool.post : Tool.file)
        ),
      errorKey: "share:createError",
    },
    {
      onSuccess: (path, input) => {
        rememberDestination(server, input.kind, input.destination);
        onDone(path);
      },
    }
  );

  // A task, a document or a post: something written around the share.
  const writes = kind === "upload" ? null : kind;
  const trimmedTitle = title.trim();
  const titleHasSigil = hasReservedSigil(trimmedTitle);
  const uploads: ShareUpload[] = files.map((file) => ({
    file,
    name: (names[file.uri] ?? "").trim(),
  }));
  const canSubmit =
    kind === "upload"
      ? uploads.length > 0 && uploads.every((upload) => upload.name)
      : !!trimmedTitle && !titleHasSigil;

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!kind || !destination || !canSubmit) return;
    if (kind === "upload") {
      // A file that landed before a later one failed is taken off the list,
      // so trying again uploads only what is left.
      land.mutate({ kind, destination, uploads, onUploaded: ({ file }) => removeFile(file) });
    } else {
      land.mutate({ kind, destination, title: trimmedTitle, note, images });
    }
  };

  const frame = destination
    ? {
        title: t("title"),
        description: [
          destination.communityName,
          destination.initiativeName,
          destination.projectName,
        ]
          .filter(Boolean)
          .join(" > "),
        onBack: land.isPending ? undefined : () => setDestination(null),
        backLabel: t("createWizard.back"),
      }
    : kind
      ? { ...steps.dialog, onBack: steps.dialog.onBack ?? (() => setKind(null)) }
      : { title: t("title"), description: t("chooseKind") };

  return (
    <div className="mx-auto flex w-full max-w-md flex-col gap-4 p-4">
      <WizardFrame {...frame}>
        {!kind ? (
          <div className="space-y-4">
            <SharePreview title={initialTitle} note={note} files={files} />
            <div className="space-y-2">
              {KINDS.filter(({ kind: option }) => kinds.includes(option)).map(
                ({ kind: option, icon: Icon }) => (
                  <button
                    key={option}
                    type="button"
                    className="flex w-full items-center gap-3 rounded-lg border p-3 text-left transition-colors hover:bg-accent"
                    onClick={() => setKind(option)}
                  >
                    <Icon className="h-5 w-5 shrink-0 text-muted-foreground" />
                    <div className="min-w-0 flex-1">
                      <p className="font-medium text-sm">{t(`kinds.${option}.label`)}</p>
                      <p className="text-muted-foreground text-xs">
                        {t(`kinds.${option}.description`)}
                      </p>
                    </div>
                  </button>
                )
              )}
            </div>
          </div>
        ) : destination && kind === "upload" ? (
          <form className="space-y-4" onSubmit={submit}>
            <ul className="space-y-3">
              {files.map((file) => (
                <li key={file.uri} className="flex items-center gap-3">
                  <SharedFileThumb file={file} className="h-12 w-12" />
                  <Input
                    value={names[file.uri] ?? ""}
                    onChange={(event) =>
                      setNames((current) => ({ ...current, [file.uri]: event.target.value }))
                    }
                    aria-label={t("compose.fileName", { name: file.name })}
                    maxLength={255}
                    className="min-w-0 flex-1"
                    disabled={land.isPending}
                  />
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    aria-label={t("compose.remove", { name: file.name })}
                    onClick={() => removeFile(file)}
                    disabled={land.isPending}
                  >
                    <X className="h-4 w-4" />
                  </Button>
                </li>
              ))}
            </ul>
            <Button type="submit" className="w-full" disabled={!canSubmit || land.isPending}>
              {land.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
              {land.isPending
                ? t("compose.creating")
                : t("compose.upload", { count: files.length })}
            </Button>
          </form>
        ) : destination && writes ? (
          <form className="space-y-4" onSubmit={submit}>
            <div className="space-y-2">
              <Label htmlFor="share-title">{t("compose.title")}</Label>
              <Input
                id="share-title"
                value={title}
                onChange={(event) => setTitle(event.target.value)}
                maxLength={255}
                aria-invalid={titleHasSigil || undefined}
                autoFocus
              />
              {titleHasSigil && (
                <p className="text-destructive text-sm">{t("errors:RESERVED_SIGIL_IN_NAME")}</p>
              )}
            </div>
            <div className="space-y-2">
              <Label htmlFor="share-note">{t("compose.note")}</Label>
              <Textarea
                id="share-note"
                value={note}
                onChange={(event) => setNote(event.target.value)}
                placeholder={t("compose.notePlaceholder")}
                rows={5}
              />
            </div>
            {images.length > 0 && (
              <div className="grid grid-cols-fill-24/4 gap-2">
                {images.map((image) => (
                  <div key={image.uri} className="relative">
                    <SharedFileThumb file={image} className="aspect-square w-full" />
                    <Button
                      type="button"
                      variant="secondary"
                      size="icon"
                      className="absolute top-1 right-1 h-7 w-7"
                      aria-label={t("compose.remove", { name: image.name })}
                      onClick={() => removeFile(image)}
                      disabled={land.isPending}
                    >
                      <X className="h-4 w-4" />
                    </Button>
                  </div>
                ))}
              </div>
            )}
            {leftOut > 0 && (
              <p className="text-muted-foreground text-sm">
                {t("compose.filesLeftOut", { count: leftOut })}
              </p>
            )}
            <Button type="submit" className="w-full" disabled={!canSubmit || land.isPending}>
              {land.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
              {land.isPending ? t("compose.creating") : t(`compose.create.${writes}`)}
            </Button>
          </form>
        ) : (
          <>
            {steps.body}
            {steps.step === "select-project" && community && initiative && (
              <ProjectPickerStep
                communityId={community.id}
                initiativeId={initiative.id}
                onPick={(project) =>
                  setDestination({
                    communityId: community.id,
                    communityName: community.name,
                    initiativeId: initiative.id,
                    initiativeName: initiative.name,
                    projectId: project.id,
                    projectName: project.name,
                  })
                }
              />
            )}
          </>
        )}
      </WizardFrame>
      <Button variant="ghost" onClick={() => onDone()} disabled={land.isPending}>
        {t("cancel")}
      </Button>
    </div>
  );
}

/** A shared picture as itself, any other file as the icon the files tool gives it. */
function SharedFileThumb({ file, className }: { file: SharedFile; className?: string }) {
  if (isImage(file)) {
    return (
      <img
        src={sharedFileSrc(file)}
        alt={file.name}
        className={cn("shrink-0 rounded-md border object-cover", className)}
      />
    );
  }
  const { Icon, colorClass } = fileIcon({ mime_type: file.mimeType, original_filename: file.name });
  return (
    <div
      className={cn(
        "flex shrink-0 items-center justify-center rounded-md border bg-muted",
        className
      )}
    >
      <Icon className={cn("h-6 w-6", colorClass)} />
    </div>
  );
}

function SharePreview({
  title,
  note,
  files,
}: {
  title: string;
  note: string;
  files: SharedFile[];
}) {
  const { t } = useTranslation("share");
  return (
    <div className="space-y-2 rounded-lg border bg-muted/40 p-3">
      <p className="font-medium text-sm">{title}</p>
      {note && (
        <p className="line-clamp-3 whitespace-pre-line text-muted-foreground text-sm">{note}</p>
      )}
      {files.length > 0 && (
        <div className="flex items-center gap-2">
          {files.slice(0, 4).map((file) => (
            <SharedFileThumb key={file.uri} file={file} className="h-12 w-12" />
          ))}
          <span className="text-muted-foreground text-xs">
            {files.every(isImage)
              ? t("pictures", { count: files.length })
              : t("files", { count: files.length })}
          </span>
        </div>
      )}
    </div>
  );
}
