/**
 * Asking for something the reader knows is there and cannot open — or can
 * open and cannot edit.
 *
 * Whoever may share it gets the request and answers it from the thing's
 * Access settings or from the notification. Nothing changes for the reader
 * until they do, so once asked the control says so rather than offering to
 * ask again.
 */

import { Check, Eye, Loader2, Lock, Pencil } from "lucide-react";
import { type FormEvent, type ReactNode, useId, useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  HiddenFiles,
  ResourceAccessLevel,
  SearchEntityType,
  ShareRequestCreate,
  ShareStanding,
} from "@/api/generated/initiativeAPI.schemas";
import { StatusMessage } from "@/components/StatusMessage";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { useCreateShareRequest, useShareStanding } from "@/hooks/useShareRequests";
import { getHttpStatus } from "@/lib/errorMessage";
import { toast } from "@/lib/mascotToast";
import { cn } from "@/lib/utils";
import type { DialogProps } from "@/types/dialog";

/** Mirrors the backend's limit on a request's note, which is the authority. */
const NOTE_MAX_LENGTH = 1000;

/** What a request asks for: one thing, or the files of a collection or a wiki. */
export type RequestTarget = Pick<
  ShareRequestCreate,
  "resource_type" | "resource_id" | "collection_id" | "wiki_id"
>;

/** The levels a request can ask for; an owner is never asked for. */
type AskLevel = Exclude<ResourceAccessLevel, "owner">;

/** What to ask for, as the standing names it: the tool whose sharing decides. */
export const standingTarget = (standing: ShareStanding): RequestTarget => ({
  resource_type: standing.resource_type,
  resource_id: standing.resource_id,
});

interface RequestAccessFormProps {
  target: RequestTarget;
  /** Asks for this level without offering the choice — "Ask to edit". */
  level?: AskLevel;
  onSent?: () => void;
  className?: string;
}

/** The level, the note and the button: what every way of asking shares. */
const RequestAccessForm = ({ target, level, onSent, className }: RequestAccessFormProps) => {
  const { t } = useTranslation("access");
  const id = useId();
  const [chosen, setChosen] = useState<AskLevel>(level ?? "read");
  const [note, setNote] = useState("");
  const create = useCreateShareRequest({
    onSuccess: () => {
      toast.success(t("request.sent"));
      onSent?.();
    },
  });

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    create.mutate({ ...target, level: chosen, message: note.trim() || null });
  };

  return (
    <form className={cn("space-y-4 text-left", className)} onSubmit={submit}>
      {level ? null : (
        <div className="space-y-2">
          <Label id={`${id}-level`}>{t("request.level")}</Label>
          <ToggleGroup
            type="single"
            variant="outline"
            value={chosen}
            onValueChange={(next) => {
              if (next) setChosen(next as AskLevel);
            }}
            aria-labelledby={`${id}-level`}
            className="justify-start"
            disabled={create.isPending}
          >
            <ToggleGroupItem value="read" className="px-3">
              <Eye />
              {t("request.view")}
            </ToggleGroupItem>
            <ToggleGroupItem value="write" className="px-3">
              <Pencil />
              {t("request.edit")}
            </ToggleGroupItem>
          </ToggleGroup>
        </div>
      )}
      <div className="space-y-2">
        <Label htmlFor={`${id}-note`}>{t("request.note")}</Label>
        <Textarea
          id={`${id}-note`}
          value={note}
          onChange={(event) => setNote(event.target.value)}
          placeholder={t("request.notePlaceholder")}
          maxLength={NOTE_MAX_LENGTH}
          rows={3}
          disabled={create.isPending}
        />
      </div>
      <div className="flex justify-end">
        <Button type="submit" disabled={create.isPending}>
          {create.isPending ? <Loader2 className="animate-spin" /> : null}
          {t("request.submit")}
        </Button>
      </div>
    </form>
  );
};

/** "Requested", with the level asked for where there is one, in place of a
 *  way to ask again. */
export const Requested = ({
  level,
  className,
}: {
  level?: ResourceAccessLevel;
  className?: string;
}) => {
  const { t } = useTranslation("access");
  return (
    <p className={cn("flex items-center gap-1.5 text-muted-foreground text-sm", className)}>
      <Check className="size-4 shrink-0" aria-hidden />
      {level === "read"
        ? t("request.requestedRead")
        : level
          ? t("request.requestedWrite")
          : t("request.requested")}
    </p>
  );
};

export interface RequestAccessDialogProps extends DialogProps {
  target: RequestTarget;
  /** Asks for this level without offering the choice. */
  level?: AskLevel;
  title?: string;
  description?: string;
}

/** The same fields, in a dialog — for an embed, a chip, a card. */
export const RequestAccessDialog = ({
  open,
  onOpenChange,
  target,
  level,
  title,
  description,
}: RequestAccessDialogProps) => {
  const { t } = useTranslation("access");
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="bg-card sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{title ?? t("request.submit")}</DialogTitle>
          <DialogDescription>{description ?? t("request.description")}</DialogDescription>
        </DialogHeader>
        <RequestAccessForm target={target} level={level} onSent={() => onOpenChange(false)} />
      </DialogContent>
    </Dialog>
  );
};

/**
 * The compact way to ask: a button that opens the dialog, or "Requested"
 * once asked. For somebody who cannot open the thing at all.
 */
export const RequestAccessButton = ({
  standing,
  className,
}: {
  standing: ShareStanding;
  className?: string;
}) => {
  const { t } = useTranslation("access");
  const [open, setOpen] = useState(false);

  if (standing.pending) {
    return <Requested level={standing.pending} className={cn("text-xs", className)} />;
  }
  return (
    <>
      <Button
        type="button"
        variant="outline"
        size="sm"
        className={className}
        onClick={() => setOpen(true)}
      >
        <Lock />
        {t("request.submit")}
      </Button>
      <RequestAccessDialog open={open} onOpenChange={setOpen} target={standingTarget(standing)} />
    </>
  );
};

/**
 * In place of an embed or a card that could not be read: "You can't see this"
 * and the way to ask, when the reader knows it is there; otherwise
 * `children`, which say it is unavailable. Read only once the thing has not
 * been, so a page of readable embeds asks nothing.
 */
export const AskWhereUnavailable = ({
  kind,
  entityId,
  children,
}: {
  kind: SearchEntityType;
  entityId: number;
  children: ReactNode;
}) => {
  const { t } = useTranslation("access");
  const { data: standing } = useShareStanding(kind, entityId);

  if (!standing || standing.level != null) return children;
  return (
    <div className="flex flex-wrap items-center gap-2">
      <p className="text-muted-foreground text-sm">{t("request.cantSee")}</p>
      <RequestAccessButton standing={standing} />
    </div>
  );
};

/**
 * The files of a collection or a wiki the reader knows are there and cannot
 * open, counted, with one request for all of them — or "Requested" once
 * they have asked for every one.
 */
export const HiddenFilesRequest = ({
  hidden,
  target,
  className,
}: {
  hidden: HiddenFiles;
  target: Pick<RequestTarget, "collection_id" | "wiki_id">;
  className?: string;
}) => {
  const { t } = useTranslation("access");
  const [open, setOpen] = useState(false);
  const count = hidden.count ?? 0;
  if (count === 0) return null;
  const asked = (hidden.requested ?? 0) >= count;

  return (
    <div
      className={cn(
        "flex flex-wrap items-center gap-x-3 gap-y-2 rounded-lg border border-dashed px-4 py-3",
        className
      )}
    >
      <Lock className="size-4 shrink-0 text-muted-foreground" aria-hidden />
      <p className="min-w-0 flex-1 text-sm">{t("request.hiddenFiles", { count })}</p>
      {asked ? (
        <Requested className="text-xs" />
      ) : (
        <Button type="button" variant="outline" size="sm" onClick={() => setOpen(true)}>
          {t("request.submit")}
        </Button>
      )}
      <RequestAccessDialog
        open={open}
        onOpenChange={setOpen}
        target={{ resource_type: "file", ...target }}
        description={t("request.hiddenFilesDescription", { count })}
      />
    </div>
  );
};

/**
 * What a page shows in place of something it was refused: when the reader
 * knows the thing is there and cannot open it, that they need access and the
 * way to ask — or that they have asked. Otherwise `children`, the page's own
 * refusal. Nothing while the standing is being read, so a request prompt never
 * replaces a "not found" the reader already saw.
 */
export const NeedAccessOr = ({
  error,
  entity,
  backTo,
  backLabel,
  children,
}: {
  error: unknown;
  /** What the page was reading. Without it, the page's own refusal stands. */
  entity?: { kind: SearchEntityType; id: number };
  backTo?: string;
  backLabel?: string;
  children: ReactNode;
}) => {
  const { t } = useTranslation("access");
  const status = getHttpStatus(error);
  const refused = entity !== undefined && (status === 403 || status === 404);
  const { data: standing, isLoading } = useShareStanding(
    entity?.kind ?? "file",
    entity?.id ?? null,
    refused
  );

  if (isLoading) return null;
  if (!refused || !standing || standing.level != null) return children;
  return (
    <StatusMessage
      icon={<Lock />}
      title={t("request.needAccess")}
      description={standing.pending ? undefined : t("request.description")}
      backTo={backTo}
      backLabel={backLabel}
      action={
        standing.pending ? (
          <Requested level={standing.pending} className="justify-center" />
        ) : (
          <RequestAccessForm target={standingTarget(standing)} className="w-full max-w-sm" />
        )
      }
    />
  );
};

/**
 * "Ask to edit", for somebody who can open the thing and not change it; "Edit
 * requested" once they have. Nothing at all for anybody else.
 */
export const AskToEdit = ({ kind, entityId }: { kind: SearchEntityType; entityId: number }) => {
  const { t } = useTranslation("access");
  const [open, setOpen] = useState(false);
  const { data: standing } = useShareStanding(kind, entityId);

  if (standing?.level !== "read") return null;
  if (standing.pending === "write") {
    return (
      <Button variant="outline" size="sm" className="shrink-0" disabled>
        <Check aria-hidden />
        {t("request.editRequested")}
      </Button>
    );
  }
  return (
    <>
      <Button variant="outline" size="sm" className="shrink-0" onClick={() => setOpen(true)}>
        <Pencil aria-hidden />
        {t("request.askToEdit")}
      </Button>
      <RequestAccessDialog
        open={open}
        onOpenChange={setOpen}
        target={standingTarget(standing)}
        level="write"
        title={t("request.askToEdit")}
      />
    </>
  );
};
