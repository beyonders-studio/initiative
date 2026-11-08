/**
 * The box a ticket, a report or a reply is written in, with the files that go
 * with it inside the box: a paperclip to choose them, and the box itself to
 * paste or drop them on. Where the box is in a panel over the page, a camera
 * takes a picture of the page behind it, and any picture attached opens in
 * the picture editor (`PictureEditor`) to hide parts of it or mark them.
 *
 * Choosing is held to what the stream takes — how many, how large, of which
 * kinds — so a refusal is said before anything is sent; the server still reads
 * every file for itself. A stream that takes no files gets the box alone.
 */
import { Camera, FileText, Loader2, Paperclip, X } from "lucide-react";
import {
  type ClipboardEvent,
  type ComponentProps,
  useEffect,
  useId,
  useRef,
  useState,
} from "react";
import { useTranslation } from "react-i18next";

import type { EvidencePolicyRead } from "@/api/generated/initiativeAPI.schemas";
import { isPicture } from "@/components/tickets/Evidence";
import {
  makePicture,
  newSession,
  PictureEditor,
  type PictureSession,
} from "@/components/tickets/PictureEditor";
import { useAuth } from "@/hooks/useAuth";
import {
  blankAvatar,
  findPeople,
  loadedPeople,
  pictureOf,
  pictureThePage,
  showPeople,
} from "@/lib/pagePicture";
import { Button } from "@/ui/button";
import { DropOverlay } from "@/ui/file-drop";
import { formatBytes } from "@/ui/lib/fileUtils";
import { useFileDrop } from "@/ui/lib/useFileDrop";
import { cn } from "@/ui/lib/utils";
import { Textarea } from "@/ui/textarea";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/ui/tooltip";

/**
 * Whether the stream may take ``file``, as far as the browser can tell. An
 * unnamed type is left to the server, which reads the bytes; any text is
 * taken as text, as the server takes it.
 */
const mayTake = (file: File, types: string[]) =>
  !file.type ||
  types.includes(file.type) ||
  (file.type.startsWith("text/") && types.includes("text/plain"));

/** What the file chooser offers: the stream's types, and any text where it takes text. */
const acceptFor = (types: string[]) =>
  (types.includes("text/plain") ? [...types, "text/*"] : types).join(",");

/** One chosen file, told apart from the rest without its place in the list. */
const fileKey = (file: File) => `${file.name}:${file.size}:${file.lastModified}`;

/** The editor's work on each picture it made, so the picture opens again
 *  where it was left. */
const sessions = new WeakMap<File, PictureSession>();

type TicketComposerProps = Omit<ComponentProps<typeof Textarea>, "className"> & {
  /** What the stream takes. No files are offered while it is not known, or
   *  where it takes none. */
  policy: EvidencePolicyRead | null | undefined;
  files: File[];
  onFilesChange: (files: File[]) => void;
  /** Offer a picture of the page behind the panel the box is in, with the
   *  people on it hidden to start with or not. With ``takenOf`` the picture
   *  is taken and attached as the box opens: of that element, drawn whole,
   *  or of the page where it is null. */
  pagePicture?: { hidePeople: boolean; takenOf?: Element | null };
};

/** Write, and attach files, in one box. */
export const TicketComposer = ({
  policy,
  files,
  onFilesChange,
  pagePicture,
  disabled,
  ...textarea
}: TicketComposerProps) => {
  const { t } = useTranslation("intake");
  const { user } = useAuth();
  const box = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const limitsId = useId();
  const [refusal, setRefusal] = useState<string | null>(null);
  const [picturing, setPicturing] = useState(false);
  const [editing, setEditing] = useState<{ session: PictureSession; target: File | null } | null>(
    null
  );
  const takes = Boolean(policy && policy.max_files > 0);
  const taking = takes && !disabled;

  /** Why the stream would not take ``file`` beside ``held`` others, if it would not. */
  const refusalFor = (file: File, held: number) => {
    if (!policy) return null;
    if (!mayTake(file, policy.types)) return t("evidence.notAllowed", { name: file.name });
    if (file.size > policy.max_bytes) {
      return t("evidence.tooLarge", { name: file.name, size: formatBytes(policy.max_bytes, 0) });
    }
    if (held >= policy.max_files) return t("evidence.tooMany", { count: policy.max_files });
    return null;
  };

  const add = (chosen: File[]) => {
    if (!policy) return;
    const next = [...files];
    let said: string | null = null;
    for (const file of chosen) {
      // Chosen twice: it is sent once.
      if (next.some((held) => fileKey(held) === fileKey(file))) continue;
      const refused = refusalFor(file, next.length);
      if (refused) said = refused;
      else next.push(file);
    }
    setRefusal(said);
    onFilesChange(next);
    // The same file can be chosen again after it is taken back out.
    if (input.current) input.current.value = "";
  };

  /** A picture of ``of``, drawn whole, or of the page behind the panel the
   *  box is in, which is left out. */
  const picture = async (of: Element | null) => {
    const drawn = of?.isConnected
      ? await pictureOf(of)
      : await pictureThePage(box.current?.closest('[role="dialog"]') ?? null);
    const people = findPeople(drawn.svg, loadedPeople(user ? [user] : []), user?.id ?? null, {
      you: t("picture.you"),
      person: (number) => t("picture.person", { number }),
      email: t("picture.emailHidden"),
      phone: t("picture.phoneHidden"),
    });
    return newSession({ kind: "page", picture: drawn, people }, pagePicture?.hidePeople);
  };

  const takePicture = async () => {
    setPicturing(true);
    setRefusal(null);
    try {
      setEditing({ session: await picture(null), target: null });
    } catch {
      setRefusal(t("picture.failed"));
    } finally {
      setPicturing(false);
    }
  };

  // Taken as the box opens: attached as it is, after whatever is attached by
  // then, and only while the stream still takes pictures.
  const latest = useRef({ files, policy });
  latest.current = { files, policy };
  const taken = useRef(false);
  const takenOf = pagePicture?.takenOf;
  const takesPictures = takes && Boolean(policy?.types.includes("image/png"));
  // biome-ignore lint/correctness/useExhaustiveDependencies: taken once, when the stream's policy says it may be
  useEffect(() => {
    if (takenOf === undefined || !takesPictures || taken.current) return;
    taken.current = true;
    setPicturing(true);
    picture(takenOf)
      .then(async (session) => {
        if (session.source.kind !== "page") return;
        const { picture: drawn, people } = session.source;
        showPeople(people, session.peopleHidden, blankAvatar());
        const made = await makePicture(
          session,
          { w: drawn.width, h: drawn.height },
          t("picture.title")
        );
        const now = latest.current;
        if (!now.policy || now.policy.max_files <= 0) return;
        const refused = refusalFor(made, now.files.length);
        if (refused) {
          setRefusal(refused);
          return;
        }
        sessions.set(made, session);
        onFilesChange([...now.files, made]);
      })
      .catch(() => setRefusal(t("picture.failed")))
      .finally(() => setPicturing(false));
  }, [takenOf, takesPictures]);

  /** Attach what the editor made, in place of the picture it was made from;
   *  or say why the stream will not take it, and the editor stays open with
   *  the picture as it was. */
  const edited = (made: File, kept: Pick<PictureSession, "shapes" | "peopleHidden">) => {
    if (!editing) return null;
    const { session, target } = editing;
    const refused = refusalFor(made, target ? files.length - 1 : files.length);
    if (refused) return refused;
    Object.assign(session, kept);
    sessions.set(made, session);
    setEditing(null);
    setRefusal(null);
    onFilesChange(target ? files.map((file) => (file === target ? made : file)) : [...files, made]);
    return null;
  };

  const drop = useFileDrop(taking, add);
  // A pasted screenshot is attached; pasted text is written as usual.
  const onPaste = (event: ClipboardEvent) => {
    const pasted = Array.from(event.clipboardData.files);
    if (!taking || pasted.length === 0) return;
    event.preventDefault();
    add(pasted);
  };
  const limits = policy
    ? t("evidence.limits", { count: policy.max_files, size: formatBytes(policy.max_bytes, 0) })
    : "";

  return (
    <div className="space-y-1.5">
      <div
        ref={box}
        {...drop.handlers}
        onPaste={onPaste}
        className={cn(
          "relative rounded-md border border-input shadow-sm focus-within:ring-1 focus-within:ring-ring",
          disabled && "opacity-50"
        )}
      >
        <Textarea
          {...textarea}
          disabled={disabled}
          className="resize-none rounded-b-none border-0 shadow-none focus-visible:ring-0 disabled:opacity-100"
        />
        {files.length > 0 ? (
          <ul className="flex flex-wrap gap-2.5 px-3 pt-1 pb-0.5">
            {files.map((file, index) => (
              <FileTile
                key={fileKey(file)}
                file={file}
                disabled={disabled}
                onEdit={() =>
                  setEditing({
                    session: sessions.get(file) ?? newSession({ kind: "file", file }),
                    target: file,
                  })
                }
                onRemove={() => {
                  setRefusal(null);
                  onFilesChange(files.filter((_, i) => i !== index));
                }}
              />
            ))}
          </ul>
        ) : null}
        {takes && policy ? (
          <div className="flex items-center gap-0.5 px-1.5 pb-1.5">
            <input
              ref={input}
              type="file"
              multiple
              className="sr-only"
              accept={acceptFor(policy.types)}
              onChange={(event) => add(Array.from(event.target.files ?? []))}
              disabled={disabled}
              data-testid="evidence-input"
              tabIndex={-1}
            />
            {/* Its own provider: there is none at the app root. */}
            <TooltipProvider delayDuration={300}>
              {pagePicture && policy.types.includes("image/png") ? (
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon-sm"
                      className="text-muted-foreground"
                      disabled={disabled || picturing || files.length >= policy.max_files}
                      onClick={takePicture}
                      aria-label={t("picture.take")}
                      aria-busy={picturing}
                    >
                      {picturing ? (
                        <Loader2 className="animate-spin" aria-hidden="true" />
                      ) : (
                        <Camera aria-hidden="true" />
                      )}
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent>{t("picture.take")}</TooltipContent>
                </Tooltip>
              ) : null}
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon-sm"
                    className="text-muted-foreground"
                    disabled={disabled || files.length >= policy.max_files}
                    onClick={() => input.current?.click()}
                    aria-label={t("evidence.attach")}
                    aria-describedby={limitsId}
                  >
                    <Paperclip aria-hidden="true" />
                  </Button>
                </TooltipTrigger>
                <TooltipContent className="max-w-56">
                  <span className="block font-medium">{t("evidence.attach")}</span>
                  <span id={limitsId}>{limits}</span>
                </TooltipContent>
              </Tooltip>
            </TooltipProvider>
          </div>
        ) : null}
        {drop.dragging ? (
          <DropOverlay label={t("evidence.dropHere")} icon={Paperclip} className="rounded-md" />
        ) : null}
      </div>
      {refusal ? (
        <p className="text-destructive text-xs" role="alert">
          {refusal}
        </p>
      ) : null}
      {editing ? (
        <PictureEditor
          session={editing.session}
          attached={editing.target !== null}
          onDone={edited}
          onCancel={() => setEditing(null)}
        />
      ) : null}
    </div>
  );
};

/** One attached file: a picture as itself, which opens in the editor, and
 *  anything else by its name. */
const FileTile = ({
  file,
  disabled,
  onEdit,
  onRemove,
}: {
  file: File;
  disabled?: boolean;
  onEdit: () => void;
  onRemove: () => void;
}) => {
  const { t } = useTranslation("intake");
  const picture = isPicture(file.type);
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    if (!picture) return;
    const made = URL.createObjectURL(file);
    setUrl(made);
    return () => URL.revokeObjectURL(made);
  }, [file, picture]);

  return (
    <li className="relative" title={file.name}>
      {picture ? (
        <button
          type="button"
          className="block rounded border bg-muted"
          disabled={disabled}
          onClick={onEdit}
          aria-label={t("picture.edit", { name: file.name })}
        >
          <img
            src={url ?? undefined}
            alt={file.name}
            className="h-12 w-auto max-w-24 rounded object-cover"
          />
        </button>
      ) : (
        <span className="flex h-12 max-w-40 items-center gap-1.5 rounded border bg-muted/40 px-2 text-xs">
          <FileText className="size-4 shrink-0" aria-hidden="true" />
          <span className="truncate">{file.name}</span>
        </span>
      )}
      <Button
        type="button"
        variant="secondary"
        size="icon"
        className="absolute -top-2 -right-2 size-5 rounded-full border shadow-sm"
        disabled={disabled}
        aria-label={t("evidence.remove", { name: file.name })}
        onClick={onRemove}
      >
        <X className="size-3" aria-hidden="true" />
      </Button>
    </li>
  );
};
