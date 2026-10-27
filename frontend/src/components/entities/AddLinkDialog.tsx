import { Loader2, X } from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  type EndpointRef,
  type FileRead,
  SearchEntityType,
  type SearchSuggestion,
} from "@/api/generated/initiativeAPI.schemas";
import { DEFAULT_GRANTS } from "@/components/access/grants";
import { EntityPicker } from "@/components/entities/EntityPicker";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { FileDropArea } from "@/components/ui/file-drop";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useAppConfig } from "@/hooks/useAppConfig";
import { useUploadFile } from "@/hooks/useFiles";
import { type ToolRef, useRelate } from "@/hooks/useRelationships";
import { fileIcon } from "@/lib/fileIcon";
import { formatBytes, getFileTypeLabel, nameWithoutExtension } from "@/lib/fileUtils";
import { toast } from "@/lib/mascotToast";
import {
  canAssert,
  defaultGroupFor,
  edgeFor,
  groupOrderFor,
  RELATION_GROUPS,
  type RelationGroup,
  type RelationGroupKey,
} from "@/lib/relationships";
import { cn } from "@/lib/utils";

interface AddLinkDialogProps {
  /** The thing being linked from. */
  entity: EndpointRef;
  /** Links made here stay inside one initiative, which the server enforces. */
  initiativeId: number | null;
  anchorTool?: ToolRef | null;
  /** The groups this surface lets somebody add to. */
  assertable: RelationGroup[];
  /** Whether a file may be uploaded here to link. */
  canUpload: boolean;
  /** A file dropped on the section before the dialog opened. */
  initialFile?: File | null;
  onClose: () => void;
}

/**
 * Make one link: find the thing, or upload it, then say how the two relate.
 *
 * Mounted only while open, so every opening starts from nothing — or from the
 * file somebody dropped on the section to open it.
 *
 * An upload is the other way to name the far end. The upload becomes a file
 * in this initiative the moment the link is made, not before: choosing a file
 * and then closing the dialog leaves nothing behind.
 */
export const AddLinkDialog = ({
  entity,
  initiativeId,
  anchorTool,
  assertable,
  canUpload,
  initialFile = null,
  onClose,
}: AddLinkDialogProps) => {
  const { t } = useTranslation(["relations", "files"]);
  const { maxUploadBytes } = useAppConfig();

  /** Set only once somebody overrides what was proposed for what they picked. */
  const [groupKey, setGroupKey] = useState<RelationGroupKey | null>(null);
  const [picked, setPicked] = useState<SearchSuggestion | null>(null);
  const [file, setFile] = useState<File | null>(canUpload ? initialFile : null);
  const [fileName, setFileName] = useState(() =>
    canUpload && initialFile ? nameWithoutExtension(initialFile.name) : ""
  );
  /**
   * The file an earlier attempt already made. If the upload landed and
   * the link did not, trying again links that file rather than uploading
   * the same file twice.
   */
  const [uploaded, setUploaded] = useState<{ file: File; created: FileRead } | null>(null);

  /** The far end's kind: what was picked, or the file an upload will become. */
  const farType = picked?.entity_type ?? (file ? SearchEntityType.file : null);
  /** A file somebody uploads is theirs, so every link to it is theirs to make. */
  const farWritable = file ? true : picked?.can_write !== false;
  const farTitle = picked?.title ?? (file ? fileName.trim() || file.name : null);

  /**
   * The links that can actually be made to what was picked.
   *
   * Reversing groups — "Blocking", "Made up of" — assert their edge from the
   * far end, which the server will only accept from somebody who may change it.
   * Offering them for a thing you can only read is offering a refusal.
   *
   * Ordered for the pair once something is picked: the list is the same list,
   * but what two things of one kind usually say to each other comes first.
   */
  const offered = useMemo(() => {
    const allowed = assertable.filter((group) => canAssert(group, farWritable));
    return farType ? groupOrderFor(entity.type, farType, allowed) : allowed;
  }, [assertable, farWritable, farType, entity.type]);

  /**
   * What the sentence currently says.
   *
   * An explicit choice wins. Otherwise the pair proposes one — never a
   * dependency; see `defaultGroupFor`. Nothing is proposed before something is
   * picked, because there is no pair to propose for and the question has not
   * been asked yet.
   */
  const proposed = farType ? defaultGroupFor(entity.type, farType) : null;
  const chosenGroup =
    (groupKey && offered.some((group) => group.key === groupKey) ? groupKey : null) ??
    (proposed && offered.some((group) => group.key === proposed) ? proposed : null) ??
    offered[0]?.key ??
    null;

  /**
   * Picking a different KIND of thing re-asks what the link says.
   *
   * The proposal is made for the pair, so a pair that changed should get its
   * own — but swapping one task for another after deliberately choosing
   * "blocked by" is correcting the thing, not the claim, and that choice is
   * kept.
   */
  const pick = (next: SearchSuggestion | null) => {
    if (next?.entity_type !== farType) setGroupKey(null);
    setPicked(next);
    setFile(null);
  };

  const chooseFile = (next: File) => {
    if (maxUploadBytes !== null && next.size > maxUploadBytes) {
      toast.error(t("files:create.fileTooLarge"));
      return;
    }
    if (farType !== SearchEntityType.file) setGroupKey(null);
    setPicked(null);
    setFile(next);
    setFileName(nameWithoutExtension(next.name));
  };

  const clearFile = () => {
    setFile(null);
    setFileName("");
  };

  const upload = useUploadFile();
  const relate = useRelate(anchorTool, {
    onSuccess: () => {
      toast.success(file ? t("uploaded") : t("added"));
      onClose();
    },
  });

  const pending = upload.isPending || relate.isPending;
  const ready = Boolean(chosenGroup && (picked || (file && fileName.trim() && initiativeId)));

  const submit = async () => {
    if (!chosenGroup) return;
    let other: EndpointRef;
    if (file) {
      if (initiativeId == null) return;
      let created = uploaded?.file === file ? uploaded.created : null;
      if (!created) {
        try {
          created = await upload.mutateAsync({
            file,
            name: fileName.trim() || file.name,
            initiative_id: initiativeId,
            grants: [...DEFAULT_GRANTS],
          });
        } catch {
          // The upload hook has already said what went wrong.
          return;
        }
        setUploaded({ file, created });
      }
      other = { type: SearchEntityType.file, id: created.id };
    } else if (picked) {
      other = { type: picked.entity_type, id: picked.entity_id };
    } else {
      return;
    }
    relate.mutate(edgeFor(RELATION_GROUPS[chosenGroup], entity, other));
  };

  // How the sentence in the dialog names this end: "This task is blocked by…".
  const anchorName = t(`anchor.${entity.type}` as "anchor.generic", {
    defaultValue: t("anchor.generic"),
  });

  const fileMark = file ? fileIcon({ mime_type: file.type, original_filename: file.name }) : null;

  return (
    <Dialog open onOpenChange={(open) => (open ? null : onClose())}>
      <DialogContent className="w-full rounded-2xl border bg-card shadow-2xl sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{t("dialog.title")}</DialogTitle>
          <DialogDescription>
            {canUpload ? t("dialog.descriptionUpload") : t("dialog.description")}
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          {/* The thing first. Nobody opens this thinking "part_of" — they
              think of the file they mean, and the picker offers what they
              looked at recently before they have typed anything. What the
              link SAYS is asked below, once there are two real names to say
              it about. */}
          <div className="space-y-2">
            <Label>{t("dialog.entity")}</Label>
            {file && fileMark ? (
              <div className="flex items-center justify-between gap-3 rounded-lg border p-3">
                <div className="flex min-w-0 items-center gap-3">
                  <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-muted">
                    <fileMark.Icon className={cn("h-5 w-5", fileMark.colorClass)} />
                  </div>
                  <div className="min-w-0">
                    <p className="truncate font-medium text-sm">{file.name}</p>
                    <p className="text-muted-foreground text-xs">
                      {getFileTypeLabel(file.type, file.name)} • {formatBytes(file.size)}
                    </p>
                  </div>
                </div>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  className="h-8 w-8 shrink-0"
                  onClick={clearFile}
                  disabled={pending}
                  aria-label={t("dialog.upload.remove")}
                >
                  <X className="h-4 w-4" />
                </Button>
              </div>
            ) : (
              <EntityPicker
                subject={entity}
                initiativeId={initiativeId}
                value={picked}
                onChange={pick}
              />
            )}
          </div>

          {file ? (
            <div className="space-y-2">
              <Label htmlFor="relation-upload-name">{t("dialog.upload.name")}</Label>
              <Input
                id="relation-upload-name"
                value={fileName}
                onChange={(event) => setFileName(event.target.value)}
                disabled={pending}
              />
            </div>
          ) : canUpload ? (
            /* The other way to name the far end: something that is not in the
               app yet. */
            <FileDropArea onFile={chooseFile} prompt={t("dialog.upload.prompt")} />
          ) : null}

          {farType && farTitle ? (
            <div className="space-y-2">
              <Label htmlFor="relation-kind">{t("dialog.sentenceLabel")}</Label>
              {/* Read as one sentence, with both ends named: "This task is
                  blocked by Ship the API". Seeing the claim written out is
                  what tells somebody it is the wrong one — and the verb in
                  the middle of it is visibly the part they can change. */}
              <div className="flex flex-wrap items-center gap-2 rounded-lg border bg-muted/40 p-3">
                <span className="font-medium text-sm">{anchorName}</span>
                <Select
                  value={chosenGroup ?? undefined}
                  onValueChange={(value) => setGroupKey(value as RelationGroupKey)}
                >
                  <SelectTrigger id="relation-kind" className="w-auto min-w-44 bg-background">
                    <SelectValue placeholder={t("dialog.relationship")} />
                  </SelectTrigger>
                  <SelectContent>
                    {offered.map((group) => (
                      <SelectItem key={group.key} value={group.key}>
                        {t(`groups.${group.key}.option`)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <span className="min-w-0 truncate font-medium text-sm">{farTitle}</span>
              </div>
              {offered.length < assertable.length ? (
                <p className="text-muted-foreground text-xs">{t("dialog.readOnlyTarget")}</p>
              ) : null}
            </div>
          ) : null}
        </div>
        <DialogFooter>
          <Button type="button" onClick={() => void submit()} disabled={pending || !ready}>
            {pending ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" />
                {upload.isPending ? t("dialog.uploading") : t("dialog.submitting")}
              </>
            ) : file ? (
              t("dialog.submitUpload")
            ) : (
              t("dialog.submit")
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};
