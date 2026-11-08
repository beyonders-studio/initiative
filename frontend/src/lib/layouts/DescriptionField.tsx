import { Sparkles } from "lucide-react";
import { type RefObject, useContext, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { MentionComposer } from "@/components/markdown/MentionComposer";
import { TaskDescription } from "@/components/tasks/TaskDescription";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { useAuth } from "@/hooks/useAuth";
import { type FieldSaveKind, type FieldSaveOptions, useItemFieldSave } from "@/hooks/useFieldSave";
import { usePastedImages } from "@/hooks/usePastedImages";
import { getHttpStatus } from "@/lib/errorMessage";
import { currentServerKey } from "@/lib/offlineSession";
import { getItem, removeItem, setItem } from "@/lib/storage";
import { Button } from "@/ui/button";
import { ConfirmDialog } from "@/ui/confirm-dialog";
import { host } from "@/ui/host";
import { FieldFrame, ItemDraftContext } from "@/ui/layouts/editing";

/** A description being written, and the one it was written over. */
interface DescriptionDraft {
  text: string;
  base: string | null;
}

const readDescriptionDraft = (key: string): DescriptionDraft | null => {
  try {
    const stored = JSON.parse(getItem(key) ?? "null") as DescriptionDraft | null;
    return stored && typeof stored.text === "string" ? stored : null;
  } catch {
    return null;
  }
};

/** The preview of a description being edited reads the way the saved one will. */
const renderDescription = (draft: string, onChange?: (draft: string) => void) => (
  <TaskDescription content={draft} onChange={onChange} />
);

/**
 * An item's description, in a composer that opens on its preview, saved only
 * with Save (or Ctrl/Cmd+Enter). What is typed is a draft, kept on the device
 * until it is saved or discarded. The save names the description it was
 * written over, and one written over a description that has since changed is
 * refused, so the reader sees the other version and chooses.
 */
export const DescriptionField = <I, P>({
  field = "description",
  kind,
  id,
  options,
  label,
  htmlId,
  value,
  readOnly,
  preview = false,
  initiativeId,
  subject,
  leaving,
  placeholder,
  suggest,
  maxLength,
}: {
  /** What the item calls it. A save names the text
   *  it was written over as `<field>_base`, which the server refuses once
   *  that has changed. */
  field?: string;
  kind: FieldSaveKind<I, P>;
  id: number;
  /** What the detail adds to its saves. */
  options: FieldSaveOptions<I, P>;
  label: string;
  htmlId: string;
  /** The description as saved. */
  value: string | null;
  readOnly: boolean;
  /** Drawn in the layout editor, where nothing is changed: a draft kept on
   *  the device stays there. */
  preview?: boolean;
  initiativeId: number | null;
  /** The item, as its references name it. */
  subject: string;
  /** Set when the page is left on purpose, so an open draft does not hold it. */
  leaving: RefObject<boolean>;
  placeholder: string;
  /** Writes a description for the reader to start from (AI). */
  suggest?: { label: string; run: () => Promise<string> };
  /** The most characters it may hold, as the server allows. */
  maxLength?: number;
}) => {
  const { t } = useTranslation(["common", "ui"]);
  const communityId = useActiveCommunityId();
  const { user } = useAuth();
  const uploadImage = usePastedImages();
  // Saved by Save or by Retry. What was typed while it saved stays the draft,
  // now written over the description just saved.
  const save = useItemFieldSave(kind, id, label, {
    ...options,
    onSaved: (edit) => {
      options.onSaved?.(edit);
      const now = latest.current;
      const saved = ((edit.shows as Record<string, unknown>)[field] as string | null) ?? null;
      if (now) setDraft(now.text === (saved ?? "") ? null : { ...now, base: saved });
    },
  });
  // Each account on each server keeps its own drafts on a shared device.
  const key = `${kind.name}-${field}-draft:${user?.id}@${currentServerKey()}:${communityId}:${id}`;
  const [draft, setDraftState] = useState(() => readDescriptionDraft(key));
  const [discarding, setDiscarding] = useState(false);
  const [suggesting, setSuggesting] = useState(false);
  // The written description, and the draft it replaced, for Undo suggestion.
  const [suggested, setSuggested] = useState<{
    text: string;
    before: DescriptionDraft | null;
  } | null>(null);
  // Read by the description written for the reader, which lands later.
  const latest = useRef(draft);

  const setDraft = (next: DescriptionDraft | null) => {
    latest.current = next;
    setDraftState(next);
    void (next ? setItem(key, JSON.stringify(next)) : removeItem(key));
    // A refused save belongs to the draft, and goes with it.
    if (!next) save.reset();
  };

  const current = value ?? "";
  // One being added is written straight into it: nothing is saved until Add.
  // It names what it held when it was opened, so a change of an item that
  // exists is refused where somebody wrote over it meanwhile.
  const adding = useContext(ItemDraftContext) !== null;
  const openedOn = useRef(value ?? null);
  const write = (text: string) =>
    void save.save({
      patch: { [field]: text || null, [`${field}_base`]: openedOn.current } as P,
      shows: { [field]: text || null } as Partial<I>,
    });
  // A reader who can no longer edit keeps the draft on the device, but sees
  // the saved description and nothing that would write.
  const open = readOnly || preview || adding ? null : draft;
  const conflict = open !== null && getHttpStatus(save.error) === 409;
  const dirty = open !== null && open.text !== (open.base ?? "");
  const blocker = host.useBlocker(() => dirty && !leaving.current);

  const submit = (base: string | null) => {
    if (!open) return;
    const description = open.text || null;
    void save.save({
      patch: { [field]: description, [`${field}_base`]: base } as P,
      shows: { [field]: description } as Partial<I>,
    });
  };
  const cancel = () => (dirty ? setDiscarding(true) : setDraft(null));
  const startFrom = async () => {
    if (!suggest) return;
    setSuggesting(true);
    try {
      const text = await suggest.run();
      setSuggested({ text, before: latest.current });
      setDraft({ text, base: latest.current?.base ?? value });
    } catch {
      // The request says what went wrong.
    } finally {
      setSuggesting(false);
    }
  };

  return (
    <FieldFrame
      label={label}
      htmlFor={htmlId}
      // The conflict below says what went wrong, and Retry would only repeat it.
      save={conflict ? { ...save, state: "idle" } : save}
      changed={
        open !== null && !conflict && save.state !== "saving" && current !== (open.base ?? "")
      }
    >
      {readOnly ? (
        <>
          {current ? (
            <div className="rounded-md border border-border/70 border-dashed bg-muted/40 px-3 py-2">
              <TaskDescription content={current} />
            </div>
          ) : (
            <p className="text-muted-foreground text-sm italic">{t("descriptionField.none")}</p>
          )}
          {draft !== null ? (
            <p className="text-muted-foreground text-xs">{t("descriptionField.draftKept")}</p>
          ) : null}
        </>
      ) : (
        <div className="space-y-2">
          <MentionComposer
            id={htmlId}
            value={open?.text ?? current}
            onChange={(text) =>
              adding ? write(text) : setDraft({ text, base: open ? open.base : value })
            }
            initiativeId={initiativeId ?? 0}
            subject={subject}
            renderPreview={renderDescription}
            onUploadImage={uploadImage}
            defaultMode="preview"
            placeholder={placeholder}
            maxLength={maxLength}
            onKeyDown={(event) => {
              if (!open) return;
              if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
                event.preventDefault();
                submit(open.base);
              } else if (event.key === "Escape") {
                event.preventDefault();
                cancel();
              }
            }}
            actions={
              suggest ? (
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="h-8 px-2 text-xs"
                  onClick={() => void startFrom()}
                  pending={suggesting}
                >
                  <Sparkles className="h-3 w-3" />
                  {suggest.label}
                </Button>
              ) : null
            }
          />
          {open === null ? null : conflict ? (
            <div
              role="alert"
              className="space-y-2 rounded-md border border-warning/40 bg-warning/5 px-3 py-2"
            >
              <p className="text-sm">{t("ui:fieldSave.changed")}</p>
              <div className="rounded-md border bg-background px-3 py-2">
                <TaskDescription content={current} />
              </div>
              <div className="flex flex-wrap gap-2">
                <Button type="button" size="sm" onClick={() => submit(value)}>
                  {t("fieldSave.overwrite")}
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  onClick={() => {
                    save.reset();
                    setDraft({ ...open, base: value });
                  }}
                >
                  {t("fieldSave.keepEditing")}
                </Button>
              </div>
            </div>
          ) : (
            <div className="flex flex-wrap gap-2">
              <Button
                type="button"
                size="sm"
                disabled={save.state === "saving"}
                onClick={() => submit(open.base)}
              >
                {t("save")}
              </Button>
              <Button type="button" size="sm" variant="outline" onClick={cancel}>
                {t("cancel")}
              </Button>
              {suggested !== null && open.text === suggested.text ? (
                <Button
                  type="button"
                  size="sm"
                  variant="ghost"
                  onClick={() => {
                    setDraft(suggested.before);
                    setSuggested(null);
                  }}
                >
                  {t("descriptionField.undoSuggestion")}
                </Button>
              ) : null}
            </div>
          )}
        </div>
      )}
      <ConfirmDialog
        open={discarding}
        onOpenChange={setDiscarding}
        title={t("descriptionField.unsavedTitle")}
        confirmLabel={t("fieldSave.discard")}
        cancelLabel={t("fieldSave.keepEditing")}
        onConfirm={() => {
          setDiscarding(false);
          setDraft(null);
        }}
        destructive
      />
      <ConfirmDialog
        open={blocker.blocked}
        onOpenChange={(isOpen) => {
          if (!isOpen) blocker.reset();
        }}
        title={t("descriptionField.unsavedTitle")}
        description={t("descriptionField.unsavedBody")}
        confirmLabel={t("descriptionField.leave")}
        cancelLabel={t("descriptionField.stay")}
        onConfirm={() => {
          setDraft(null);
          blocker.proceed();
        }}
        destructive
      />
    </FieldFrame>
  );
};
