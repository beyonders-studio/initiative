import {
  FileCode,
  FileSpreadsheet,
  FileText,
  ImageIcon,
  Link as LinkIcon,
  Loader2,
  Plus,
  Presentation,
  Upload,
  X,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import type { ResourceGrantSchema } from "@/api/generated/initiativeAPI.schemas";
import { FileType, SearchEntityType } from "@/api/generated/initiativeAPI.schemas";
import { CreateAccessSection } from "@/components/access/CreateAccessSection";
import { DEFAULT_GRANTS } from "@/components/access/grants";
import { AsyncCombobox } from "@/components/ui/async-combobox";
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
import { Progress } from "@/components/ui/progress";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsBar, TabsContent, TabsTrigger } from "@/components/ui/tabs";
import { useCreateFile, useUploadFile } from "@/hooks/useFiles";
import { useInitiative } from "@/hooks/useInitiatives";
import { useCommunityPickerSuggestions } from "@/hooks/useSearch";
import type { EditorFileType } from "@/lib/fileTypes";
import { formatBytes, getFileTypeLabel, nameWithoutExtension } from "@/lib/fileUtils";
import { numberFormat } from "@/lib/intl";
import { toast } from "@/lib/mascotToast";
import { matchSmartLinkProvider, SUPPORTED_PROVIDER_BADGES } from "@/lib/smartLinkProviders";
import type { DialogProps } from "@/types/dialog";

type CreateFileDialogProps = DialogProps & {
  /** The initiative the file is made in. */
  initiativeId: number;
  /** If provided, the created file will be auto-attached to this project */
  projectId?: number;
  /** Called after successful creation/upload */
  onSuccess?: (file: { id: number }) => void;
  /** A file dropped on the page to open this; the dialog opens on Upload holding it. */
  initialFile?: File | null;
};

/** The file types made from scratch here; files come in by upload, and
 *  smart links from their own tab. */
type NewFileType = Exclude<EditorFileType, typeof FileType.url>;

export const CreateFileDialog = ({
  open,
  onOpenChange,
  initiativeId,
  projectId,
  onSuccess,
  initialFile = null,
}: CreateFileDialogProps) => {
  const { t, i18n } = useTranslation(["files", "common"]);
  const percent = numberFormat(i18n.resolvedLanguage ?? i18n.language, {
    style: "percent",
    maximumFractionDigits: 0,
  });

  const [createDialogTab, setCreateDialogTab] = useState<"new" | "upload" | "smartLink">("new");
  const [newTitle, setNewTitle] = useState("");
  const [selectedTemplateId, setSelectedTemplateId] = useState("");
  // Server search only returns matches for the live query, so the picker can't
  // look the selected template's title up from the current page — remember it.
  const [selectedTemplateLabel, setSelectedTemplateLabel] = useState<string | null>(null);
  const [templateSearch, setTemplateSearch] = useState("");
  const [isTemplateFile, setIsTemplateFile] = useState(false);
  const [newFileType, setNewFileType] = useState<NewFileType>(FileType.lexical);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [smartLinkUrl, setSmartLinkUrl] = useState("");
  const [grants, setGrants] = useState<ResourceGrantSchema[]>([...DEFAULT_GRANTS]);
  // How much of the file being uploaded has arrived, and how to stop it.
  const [sent, setSent] = useState(0);
  const sending = useRef<AbortController | null>(null);

  const initiative = useInitiative(open ? initiativeId : null).data;

  // Template picker — the shared lookup, asked for blueprints, only while the
  // dialog is open. It opens on the templates most recently worked on, which is
  // the only way it can say that this community has any.
  const templates = useCommunityPickerSuggestions(templateSearch, {
    types: [SearchEntityType.file],
    is_template: true,
    enabled: open && !isTemplateFile,
  });

  const templateItems = useMemo(
    () =>
      templates.items.map((doc) => ({
        value: String(doc.entity_id),
        label: doc.title,
      })),
    [templates.items]
  );

  const clearTemplate = useCallback(() => {
    setSelectedTemplateId("");
    setSelectedTemplateLabel(null);
  }, []);

  // Reset form when dialog closes
  useEffect(() => {
    if (open) {
      // Opened by a drop: the file is the whole of what was asked for.
      if (initialFile) {
        setCreateDialogTab("upload");
        setSelectedFile(initialFile);
        setNewTitle(nameWithoutExtension(initialFile.name));
      }
    } else {
      // Closing the dialog stops an upload still under way.
      sending.current?.abort();
      sending.current = null;
      setSent(0);
      setNewTitle("");
      clearTemplate();
      setIsTemplateFile(false);
      setNewFileType(FileType.lexical);
      setSelectedFile(null);
      setSmartLinkUrl("");
      setCreateDialogTab("new");
      setGrants([...DEFAULT_GRANTS]);
    }
  }, [open, initialFile, clearTemplate]);

  // Clear template when "save as template" is toggled on
  useEffect(() => {
    if (isTemplateFile && selectedTemplateId) {
      clearTemplate();
    }
  }, [isTemplateFile, selectedTemplateId, clearTemplate]);

  // Clear template when the file type changes so we don't accidentally
  // copy a text template into a whiteboard (or vice versa).
  useEffect(() => {
    clearTemplate();
  }, [newFileType, clearTemplate]);

  const createFile = useCreateFile({
    onSuccess: (file) => {
      toast.success(projectId ? t("create.createdAttached") : t("create.created"));
      onOpenChange(false);
      onSuccess?.(file);
    },
  });

  const uploadFile = useUploadFile({
    onSuccess: (file) => {
      toast.success(projectId ? t("create.uploadedAttached") : t("create.uploaded"));
      onOpenChange(false);
      onSuccess?.(file);
    },
  });

  const handleFileSelect = (file: File) => {
    setSelectedFile(file);
    if (!newTitle.trim()) {
      setNewTitle(nameWithoutExtension(file.name));
    }
  };

  const isCreating = createFile.isPending || uploadFile.isPending;
  const canSubmitNew = newTitle.trim() && !isCreating;
  const canSubmitUpload = newTitle.trim() && selectedFile && !isCreating;
  const trimmedSmartLinkUrl = smartLinkUrl.trim();
  const smartLinkProviderMatch = useMemo(
    () => (trimmedSmartLinkUrl ? matchSmartLinkProvider(trimmedSmartLinkUrl) : null),
    [trimmedSmartLinkUrl]
  );
  const smartLinkUrlIsHttp = /^https?:\/\//.test(trimmedSmartLinkUrl);
  const canSubmitSmartLink = Boolean(newTitle.trim() && smartLinkUrlIsHttp && !isCreating);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="w-full rounded-2xl border bg-card shadow-2xl sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{t("create.title")}</DialogTitle>
          <DialogDescription>
            {projectId ? t("create.descriptionAttach") : t("create.descriptionStandalone")}
          </DialogDescription>
        </DialogHeader>

        <Tabs
          value={createDialogTab}
          onValueChange={(value) => setCreateDialogTab(value as "new" | "upload" | "smartLink")}
        >
          <TabsBar>
            <TabsTrigger value="new" className="flex items-center gap-2">
              <Plus className="h-4 w-4" />
              {t("create.tabNew")}
            </TabsTrigger>
            <TabsTrigger value="upload" className="flex items-center gap-2">
              <Upload className="h-4 w-4" />
              {t("create.tabUpload")}
            </TabsTrigger>
            <TabsTrigger value="smartLink" className="flex items-center gap-2">
              <LinkIcon className="h-4 w-4" />
              {t("create.tabSmartLink")}
            </TabsTrigger>
          </TabsBar>

          {/* Shared fields: Title and Initiative */}
          <div className="mt-4 space-y-4">
            <div className="space-y-2">
              <Label htmlFor="create-doc-title">{t("create.titleLabel")}</Label>
              <Input
                id="create-doc-title"
                value={newTitle}
                onChange={(e) => setNewTitle(e.target.value)}
                placeholder={
                  createDialogTab === "upload"
                    ? t("create.titlePlaceholderStandalone")
                    : t("create.titlePlaceholderAttach")
                }
              />
            </div>
            <div className="space-y-2">
              <Label>{t("create.initiativeLabel")}</Label>
              <div className="rounded-md border px-3 py-2 text-sm">
                {initiative?.name ?? t("common:loading")}
              </div>
            </div>
          </div>

          {/* New file tab content */}
          <TabsContent value="new" className="mt-4 space-y-4">
            <div className="space-y-2">
              <Label htmlFor="create-doc-type">{t("create.fileTypeLabel")}</Label>
              <Select
                value={newFileType}
                onValueChange={(value) => setNewFileType(value as NewFileType)}
              >
                <SelectTrigger id="create-doc-type">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={FileType.lexical}>{t("create.fileTypeText")}</SelectItem>
                  <SelectItem value={FileType.excalidraw}>
                    {t("create.fileTypeWhiteboard")}
                  </SelectItem>
                  <SelectItem value={FileType.sheet}>{t("create.fileTypeSpreadsheet")}</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <Label>{t("create.templateLabel")}</Label>
                {selectedTemplateId && (
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className="h-auto px-2 py-1 text-xs"
                    onClick={clearTemplate}
                  >
                    <X className="h-3 w-3" />
                    {t("create.clear")}
                  </Button>
                )}
              </div>
              <AsyncCombobox
                items={templateItems}
                value={selectedTemplateId || null}
                selectedLabel={selectedTemplateLabel}
                onValueChange={(value) => {
                  setSelectedTemplateId(value);
                  setSelectedTemplateLabel(
                    templateItems.find((item) => item.value === value)?.label ?? null
                  );
                }}
                onSearchChange={setTemplateSearch}
                loading={templates.isFetching}
                disabled={isTemplateFile}
                placeholder={t("create.selectTemplate")}
                searchPlaceholder={t("create.searchTemplates")}
                emptyMessage={t("create.noTemplates")}
                aria-label={t("create.templateLabel")}
              />
            </div>
            <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border bg-muted/40 p-3">
              <div>
                <p className="font-medium text-sm">{t("create.saveAsTemplate")}</p>
                <p className="text-muted-foreground text-xs">{t("create.templateDescription")}</p>
              </div>
              <Switch
                id="create-doc-is-template"
                checked={isTemplateFile}
                onCheckedChange={setIsTemplateFile}
                aria-label={t("create.templateToggle")}
              />
            </div>
          </TabsContent>

          {/* Upload file tab content */}
          <TabsContent value="upload" className="mt-4 space-y-4">
            <div className="space-y-2">
              <Label>{t("create.fileLabel")}</Label>
              {selectedFile ? (
                <div className="flex items-center justify-between rounded-lg border p-3">
                  <div className="flex items-center gap-3">
                    <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-muted">
                      {getFileTypeLabel(selectedFile.type, selectedFile.name) === "Image" ? (
                        <ImageIcon className="h-5 w-5 text-emerald-500" />
                      ) : getFileTypeLabel(selectedFile.type, selectedFile.name) === "Markdown" ? (
                        <FileCode className="h-5 w-5 text-indigo-500" />
                      ) : getFileTypeLabel(selectedFile.type, selectedFile.name) === "Excel" ? (
                        <FileSpreadsheet className="h-5 w-5 text-green-600" />
                      ) : getFileTypeLabel(selectedFile.type, selectedFile.name) ===
                        "PowerPoint" ? (
                        <Presentation className="h-5 w-5 text-orange-600" />
                      ) : (
                        <FileText className="h-5 w-5 text-blue-600" />
                      )}
                    </div>
                    <div>
                      <p className="max-w-[200px] truncate font-medium text-sm">
                        {selectedFile.name}
                      </p>
                      <p className="text-muted-foreground text-xs">
                        {getFileTypeLabel(selectedFile.type, selectedFile.name)} •{" "}
                        {formatBytes(selectedFile.size)}
                      </p>
                    </div>
                  </div>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={() => setSelectedFile(null)}
                  >
                    <X className="h-4 w-4" />
                  </Button>
                </div>
              ) : (
                <FileDropArea onFile={handleFileSelect} prompt={t("create.dropPrompt")} />
              )}
              <p className="whitespace-pre-line text-muted-foreground text-xs">
                {t("create.fileHelp")}
              </p>
            </div>
          </TabsContent>

          {/* Smart link tab content */}
          <TabsContent value="smartLink" className="mt-4 space-y-4">
            <div className="space-y-2">
              <Label htmlFor="create-doc-smart-link-url">{t("create.smartLinkUrlLabel")}</Label>
              <Input
                id="create-doc-smart-link-url"
                type="url"
                value={smartLinkUrl}
                onChange={(e) => setSmartLinkUrl(e.target.value)}
                placeholder={t("create.smartLinkUrlPlaceholder")}
                autoComplete="off"
              />
              <div className="flex items-center gap-2">
                <span className="text-muted-foreground text-xs">
                  {t("create.smartLinkSupportedProviders")}
                </span>
                <div className="flex flex-wrap items-center gap-2 text-muted-foreground">
                  {SUPPORTED_PROVIDER_BADGES.map((p) => (
                    <span
                      key={p.id}
                      title={p.label}
                      aria-label={p.label}
                      className="inline-flex"
                      role="img"
                    >
                      <p.icon className="h-4 w-4" aria-hidden="true" />
                    </span>
                  ))}
                </div>
              </div>
              {smartLinkProviderMatch ? (
                <div className="flex items-start gap-2 text-muted-foreground text-xs">
                  <smartLinkProviderMatch.icon className="mt-0.5 h-4 w-4 shrink-0" />
                  {smartLinkProviderMatch.canEmbed ? (
                    <span>
                      {t("create.smartLinkProviderDetected", {
                        provider: smartLinkProviderMatch.label,
                      })}
                    </span>
                  ) : smartLinkProviderMatch.embedHintKey ? (
                    <span>
                      <span className="font-medium">
                        {t("create.smartLinkNeedsEmbedUrl", {
                          provider: smartLinkProviderMatch.label,
                        })}
                      </span>{" "}
                      {t(smartLinkProviderMatch.embedHintKey)}
                    </span>
                  ) : (
                    <span>{t("create.smartLinkGenericNote")}</span>
                  )}
                </div>
              ) : null}
              <p className="text-muted-foreground text-xs">{t("create.smartLinkDisclaimer")}</p>
            </div>
          </TabsContent>
        </Tabs>

        <CreateAccessSection
          initiativeId={initiativeId}
          grants={grants}
          onChange={setGrants}
          defaultOpen={false}
        />

        {uploadFile.isPending ? (
          <Progress value={sent * 100} aria-label={t("create.uploadingFile")} />
        ) : null}

        <DialogFooter>
          {createDialogTab === "new" ? (
            <Button
              type="button"
              onClick={() => {
                const trimmedTitle = newTitle.trim();
                if (!trimmedTitle) return;
                createFile.mutate({
                  name: trimmedTitle,
                  initiative_id: initiativeId,
                  is_template: isTemplateFile,
                  template_id: selectedTemplateId ? Number(selectedTemplateId) : undefined,
                  project_id: projectId,
                  file_type: newFileType,
                  grants,
                });
              }}
              disabled={!canSubmitNew}
            >
              {createFile.isPending ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  {t("create.creating")}
                </>
              ) : (
                t("create.createFile")
              )}
            </Button>
          ) : createDialogTab === "upload" ? (
            <Button
              type="button"
              onClick={() => {
                const trimmedTitle = newTitle.trim();
                if (!selectedFile || !trimmedTitle) return;
                sending.current = new AbortController();
                setSent(0);
                uploadFile.mutate({
                  file: selectedFile,
                  name: trimmedTitle,
                  initiative_id: initiativeId,
                  project_id: projectId,
                  grants,
                  signal: sending.current.signal,
                  onProgress: (arrived, total) => setSent(total ? arrived / total : 1),
                });
              }}
              disabled={!canSubmitUpload}
            >
              {uploadFile.isPending ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  {t("create.uploadingProgress", { percent: percent.format(sent) })}
                </>
              ) : (
                t("create.uploadFile")
              )}
            </Button>
          ) : (
            <Button
              type="button"
              onClick={() => {
                const trimmedTitle = newTitle.trim();
                if (!trimmedTitle || !smartLinkUrlIsHttp) return;
                createFile.mutate({
                  name: trimmedTitle,
                  initiative_id: initiativeId,
                  project_id: projectId,
                  file_type: FileType.url,
                  content: { url: trimmedSmartLinkUrl },
                  grants,
                });
              }}
              disabled={!canSubmitSmartLink}
            >
              {createFile.isPending ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  {t("create.creating")}
                </>
              ) : (
                t("create.createSmartLink")
              )}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};
