import { ArrowDown, ArrowUp, Eye, ImagePlus, Loader2, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  AnnouncementAudienceAccounts,
  AnnouncementCategory,
  AnnouncementOperatorRead,
  AnnouncementSection,
} from "@/api/generated/initiativeAPI.schemas";
import { AnnouncementDialog } from "@/components/announcements/AnnouncementDialog";
import {
  useCreateAnnouncement,
  useUpdateAnnouncement,
  useUploadAnnouncementImage,
} from "@/hooks/usePlatformAnnouncements";
import { validateTriggerRoute } from "@/lib/announcementPages";
import { getErrorMessage } from "@/lib/errorMessage";
import { fromLocalDateTimeInput, toLocalDateTimeInput } from "@/lib/formatDate";
import { toast } from "@/lib/mascotToast";
import { browserTimezone } from "@/lib/timezones";
import { resolveHeaderlessApiUrl } from "@/lib/uploadUrl";
import { Button } from "@/ui/button";
import { DateTimePicker } from "@/ui/date-time-picker";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/ui/dialog";
import { Field } from "@/ui/field";
import { ImagePicker } from "@/ui/image-picker";
import { Input } from "@/ui/input";
import { Label } from "@/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/ui/select";
import { Switch } from "@/ui/switch";
import { Textarea } from "@/ui/textarea";

const CATEGORIES: AnnouncementCategory[] = [
  "release",
  "feature",
  "breaking",
  "maintenance",
  "security",
  "info",
];

const PLATFORM_ROLES = ["member", "support", "moderator", "operator", "owner"] as const;

//: Measured against the notice's publication date — see the backend enum.
const AUDIENCE_ACCOUNTS: AnnouncementAudienceAccounts[] = ["everyone", "existing", "new"];
type PlatformRole = (typeof PLATFORM_ROLES)[number];

//: Mirrors the server's ceiling in ``app.schemas.platform.announcement``.
const MAX_DISMISSALS_REQUIRED = 10;

const clampDismissals = (raw: string): number => {
  const parsed = Number.parseInt(raw, 10);
  if (!Number.isFinite(parsed)) return 1;
  return Math.min(Math.max(parsed, 1), MAX_DISMISSALS_REQUIRED);
};

interface EditorState {
  title: string;
  category: AnnouncementCategory;
  minPlatformRole: PlatformRole;
  communityAdminsOnly: boolean;
  audienceAccounts: AnnouncementAudienceAccounts;
  publishedAt: string;
  expiresAt: string;
  dismissalsRequired: number;
  triggerRoute: string;
  sections: AnnouncementSection[];
}

const emptySection = (): AnnouncementSection => ({
  heading: "",
  body: "",
  image_url: null,
  image_alt: "",
  starts_page: false,
});

const initialState = (announcement: AnnouncementOperatorRead | null): EditorState => ({
  title: announcement?.title ?? "",
  category: announcement?.category ?? "feature",
  minPlatformRole: (announcement?.min_platform_role ?? "member") as PlatformRole,
  communityAdminsOnly: announcement?.community_admins_only ?? false,
  audienceAccounts: announcement?.audience_accounts ?? "everyone",
  publishedAt: toLocalDateTimeInput(announcement?.published_at),
  expiresAt: toLocalDateTimeInput(announcement?.expires_at),
  dismissalsRequired: announcement?.dismissals_required ?? 1,
  triggerRoute: announcement?.trigger_route ?? "",
  sections:
    announcement?.sections && announcement.sections.length > 0
      ? announcement.sections.map((section) => ({ ...section }))
      : [emptySection()],
});

interface AnnouncementEditorDialogProps {
  open: boolean;
  /** The announcement being edited, or null to write a new one. */
  announcement: AnnouncementOperatorRead | null;
  onOpenChange: (open: boolean) => void;
}

/**
 * Write or edit one announcement.
 *
 * The body is a list of sections rather than a single field because that is
 * what a release note actually is — "here is the thing, here is a picture of
 * it", repeated. Each section carries its own screenshot, uploaded straight
 * from here.
 */
export const AnnouncementEditorDialog = ({
  open,
  announcement,
  onOpenChange,
}: AnnouncementEditorDialogProps) => {
  const { t } = useTranslation(["announcements", "common"]);
  const [state, setState] = useState<EditorState>(() => initialState(announcement));
  const [previewOpen, setPreviewOpen] = useState(false);
  // Remount the form when a different announcement is opened in it.
  const [editingKey, setEditingKey] = useState(announcement?.key ?? "new");
  if ((announcement?.key ?? "new") !== editingKey) {
    setEditingKey(announcement?.key ?? "new");
    setState(initialState(announcement));
  }

  // Checked as they type: the server's own rule is "looks like a path", so a
  // wildcard typo would otherwise come back as a 422 with nothing pointing at
  // the field that caused it.
  const triggerProblem = validateTriggerRoute(state.triggerRoute);

  const create = useCreateAnnouncement();
  const update = useUpdateAnnouncement();
  const saving = create.isPending || update.isPending;

  const patchSection = (index: number, patch: Partial<AnnouncementSection>) => {
    setState((previous) => ({
      ...previous,
      sections: previous.sections.map((section, i) =>
        i === index ? { ...section, ...patch } : section
      ),
    }));
  };

  const moveSection = (index: number, delta: number) => {
    setState((previous) => {
      const next = [...previous.sections];
      const target = index + delta;
      if (target < 0 || target >= next.length) return previous;
      [next[index], next[target]] = [next[target], next[index]];
      return { ...previous, sections: next };
    });
  };

  const handleSave = async () => {
    // Every field the section carries has to be named here — this rebuilds the
    // object rather than spreading it, so anything left out is silently
    // dropped on save.
    const sections = state.sections
      .map((section) => ({
        heading: section.heading?.trim() || null,
        body: section.body?.trim() || null,
        image_url: section.image_url || null,
        image_alt: section.image_alt?.trim() || null,
        starts_page: section.starts_page ?? false,
      }))
      .filter((section) => section.heading || section.body || section.image_url);

    if (!state.title.trim() || sections.length === 0) {
      toast.error(t("operator.needsTitleAndSection"));
      return;
    }
    if (triggerProblem) {
      toast.error(t(`operator.triggerErrors.${triggerProblem}`));
      return;
    }

    const body = {
      title: state.title.trim(),
      category: state.category,
      sections,
      min_platform_role: state.minPlatformRole,
      community_admins_only: state.communityAdminsOnly,
      audience_accounts: state.audienceAccounts,
      published_at: fromLocalDateTimeInput(state.publishedAt),
      expires_at: fromLocalDateTimeInput(state.expiresAt),
      dismissals_required: state.dismissalsRequired,
      trigger_route: state.triggerRoute.trim() || null,
    };

    try {
      if (announcement?.id) {
        await update.mutateAsync({
          id: announcement.id,
          data: {
            ...body,
            clear_published_at: !state.publishedAt,
            clear_expires_at: !state.expiresAt,
            clear_trigger_route: !state.triggerRoute.trim(),
          },
        });
      } else {
        await create.mutateAsync(body);
      }
      toast.success(t("operator.saved"));
      onOpenChange(false);
    } catch (error) {
      toast.error(getErrorMessage(error, "announcements:operator.saveFailed"));
    }
  };

  return (
    <>
      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent className="flex max-h-[90vh] flex-col gap-0 sm:max-w-3xl">
          <DialogHeader className="shrink-0">
            <DialogTitle>
              {announcement ? t("operator.editTitle") : t("operator.newTitle")}
            </DialogTitle>
            <DialogDescription>{t("operator.editorSubtitle")}</DialogDescription>
          </DialogHeader>

          {/* Plain overflow rather than ScrollArea — see AnnouncementDialog:
              a max-height dialog gives Radix's viewport no height to fill. */}
          <div className="-mr-2 min-h-0 flex-1 overflow-y-auto pr-2">
            <div className="space-y-6 py-4">
              <Field label={t("operator.fields.title")}>
                <Input
                  value={state.title}
                  maxLength={200}
                  placeholder={t("operator.fields.titlePlaceholder")}
                  onChange={(event) =>
                    setState((previous) => ({ ...previous, title: event.target.value }))
                  }
                />
              </Field>

              <div className="grid grid-cols-pair gap-4">
                <Field label={t("operator.fields.category")}>
                  <Select
                    value={state.category}
                    onValueChange={(value) =>
                      setState((previous) => ({
                        ...previous,
                        category: value as AnnouncementCategory,
                      }))
                    }
                  >
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {CATEGORIES.map((category) => (
                        <SelectItem key={category} value={category}>
                          {t(`category.${category}`)}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </Field>

                <Field label={t("operator.fields.minRole")} hint={t("operator.fields.minRoleHint")}>
                  <Select
                    value={state.minPlatformRole}
                    onValueChange={(value) =>
                      setState((previous) => ({
                        ...previous,
                        minPlatformRole: value as PlatformRole,
                      }))
                    }
                  >
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {PLATFORM_ROLES.map((role) => (
                        <SelectItem key={role} value={role}>
                          {t(`operator.roles.${role}`)}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </Field>

                <Field
                  label={t("operator.fields.audienceAccounts")}
                  hint={t(`operator.accountsHint.${state.audienceAccounts}`)}
                  className="col-span-full"
                >
                  <Select
                    value={state.audienceAccounts}
                    onValueChange={(value) =>
                      setState((previous) => ({
                        ...previous,
                        audienceAccounts: value as AnnouncementAudienceAccounts,
                      }))
                    }
                  >
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {AUDIENCE_ACCOUNTS.map((audience) => (
                        <SelectItem key={audience} value={audience}>
                          {t(`operator.accounts.${audience}`)}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </Field>
              </div>

              <div className="flex items-center justify-between rounded-md border p-3">
                <div className="space-y-0.5">
                  <Label htmlFor="announcement-admins-only">
                    {t("operator.fields.communityAdminsOnly")}
                  </Label>
                  <p className="text-muted-foreground text-xs">
                    {t("operator.fields.communityAdminsOnlyHint")}
                  </p>
                </div>
                <Switch
                  id="announcement-admins-only"
                  checked={state.communityAdminsOnly}
                  onCheckedChange={(checked) =>
                    setState((previous) => ({ ...previous, communityAdminsOnly: checked }))
                  }
                />
              </div>

              <div className="grid grid-cols-pair gap-4">
                <Field
                  label={t("operator.fields.dismissalsRequired")}
                  hint={t("operator.fields.dismissalsRequiredHint")}
                >
                  <Input
                    type="number"
                    min={1}
                    max={MAX_DISMISSALS_REQUIRED}
                    value={state.dismissalsRequired}
                    onChange={(event) =>
                      setState((previous) => ({
                        ...previous,
                        dismissalsRequired: clampDismissals(event.target.value),
                      }))
                    }
                  />
                </Field>

                <Field
                  label={t("operator.fields.triggerRoute")}
                  hint={!triggerProblem && t("operator.fields.triggerRouteHint")}
                  error={triggerProblem && t(`operator.triggerErrors.${triggerProblem}`)}
                >
                  <Input
                    value={state.triggerRoute}
                    maxLength={200}
                    placeholder="/c/*/i/*/projects/**"
                    onChange={(event) =>
                      setState((previous) => ({ ...previous, triggerRoute: event.target.value }))
                    }
                  />
                </Field>
              </div>

              <div className="grid grid-cols-pair gap-4">
                <div className="col-span-full space-y-2">
                  {/* Both times are entered and shown in whatever timezone this
                      browser is in, and stored as an instant (UTC) — so a
                      notice published "at 9am" appears at the author's 9am, not
                      at each reader's. Naming the zone is the only way that is
                      obvious. */}
                  <p className="text-muted-foreground text-xs">
                    {t("operator.fields.timezoneHint", { zone: browserTimezone() })}
                  </p>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="announcement-published">{t("operator.fields.publishedAt")}</Label>
                  <DateTimePicker
                    id="announcement-published"
                    includeTime
                    value={state.publishedAt}
                    placeholder={t("operator.fields.draftPlaceholder")}
                    onChange={(value) =>
                      setState((previous) => ({ ...previous, publishedAt: value }))
                    }
                  />
                  <div className="flex gap-2">
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      onClick={() =>
                        setState((previous) => ({
                          ...previous,
                          publishedAt: toLocalDateTimeInput(new Date().toISOString()),
                        }))
                      }
                    >
                      {t("operator.publishNow")}
                    </Button>
                    {state.publishedAt ? (
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        onClick={() => setState((previous) => ({ ...previous, publishedAt: "" }))}
                      >
                        {t("operator.makeDraft")}
                      </Button>
                    ) : null}
                  </div>
                </div>

                <Field
                  label={t("operator.fields.expiresAt")}
                  hint={t("operator.fields.expiresHint")}
                >
                  <DateTimePicker
                    includeTime
                    value={state.expiresAt}
                    placeholder={t("common:optional")}
                    onChange={(value) =>
                      setState((previous) => ({ ...previous, expiresAt: value }))
                    }
                  />
                </Field>
              </div>

              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <Label>{t("operator.fields.sections")}</Label>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() =>
                      setState((previous) => ({
                        ...previous,
                        sections: [...previous.sections, emptySection()],
                      }))
                    }
                  >
                    <Plus className="h-4 w-4" />
                    {t("operator.addSection")}
                  </Button>
                </div>

                {state.sections.map((section, index) => (
                  <SectionEditor
                    // Sections are a positional list with no identity of their own.
                    // biome-ignore lint/suspicious/noArrayIndexKey: positional by nature
                    key={index}
                    section={section}
                    index={index}
                    total={state.sections.length}
                    onChange={(patch) => patchSection(index, patch)}
                    onMove={(delta) => moveSection(index, delta)}
                    onRemove={() =>
                      setState((previous) => ({
                        ...previous,
                        sections: previous.sections.filter((_, i) => i !== index),
                      }))
                    }
                  />
                ))}
              </div>
            </div>
          </div>

          <DialogFooter
            className="shrink-0 border-t pt-4"
            submitLabel={t("common:save")}
            pending={saving}
            disabled={triggerProblem !== null}
            onSubmit={() => void handleSave()}
          >
            <Button type="button" variant="ghost" onClick={() => setPreviewOpen(true)}>
              <Eye className="h-4 w-4" />
              {t("operator.preview")}
            </Button>
            <div className="flex-1" />
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <AnnouncementDialog
        open={previewOpen}
        title={state.title || t("operator.untitled")}
        category={state.category}
        sections={state.sections}
        onOpenChange={setPreviewOpen}
        footer={<Button onClick={() => setPreviewOpen(false)}>{t("dialog.gotIt")}</Button>}
      />
    </>
  );
};

interface SectionEditorProps {
  section: AnnouncementSection;
  index: number;
  total: number;
  onChange: (patch: Partial<AnnouncementSection>) => void;
  onMove: (delta: number) => void;
  onRemove: () => void;
}

const SectionEditor = ({
  section,
  index,
  total,
  onChange,
  onMove,
  onRemove,
}: SectionEditorProps) => {
  const { t } = useTranslation("announcements");
  const upload = useUploadAnnouncementImage();

  const handleFile = async (file: File) => {
    try {
      const result = await upload.mutateAsync(file);
      onChange({ image_url: result.url });
    } catch (error) {
      toast.error(getErrorMessage(error, "announcements:operator.uploadFailed"));
    }
  };

  const previewSrc = section.image_url?.startsWith("/api/")
    ? resolveHeaderlessApiUrl(section.image_url)
    : section.image_url;

  return (
    <div className="space-y-3 rounded-md border p-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className="font-medium text-muted-foreground text-xs">
            {t("operator.sectionNumber", { number: index + 1 })}
          </span>
          {/* The first section always opens page one, so only the others can
              break. Breaking here is what makes the notice a wizard. */}
          {index > 0 ? (
            <div className="flex items-center gap-1.5">
              <Switch
                id={`announcement-section-${index}-page`}
                checked={section.starts_page ?? false}
                onCheckedChange={(checked) => onChange({ starts_page: checked })}
              />
              <Label
                htmlFor={`announcement-section-${index}-page`}
                className="text-muted-foreground text-xs"
              >
                {t("operator.startsPage")}
              </Label>
            </div>
          ) : null}
        </div>
        <div className="flex items-center gap-1">
          <Button
            type="button"
            variant="ghost"
            size="icon"
            disabled={index === 0}
            aria-label={t("operator.moveUp")}
            onClick={() => onMove(-1)}
          >
            <ArrowUp className="h-4 w-4" />
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            disabled={index === total - 1}
            aria-label={t("operator.moveDown")}
            onClick={() => onMove(1)}
          >
            <ArrowDown className="h-4 w-4" />
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            aria-label={t("operator.removeSection")}
            onClick={onRemove}
          >
            <Trash2 className="h-4 w-4" />
          </Button>
        </div>
      </div>

      <Input
        value={section.heading ?? ""}
        maxLength={160}
        placeholder={t("operator.fields.headingPlaceholder")}
        onChange={(event) => onChange({ heading: event.target.value })}
      />
      <Textarea
        value={section.body ?? ""}
        rows={4}
        maxLength={4000}
        placeholder={t("operator.fields.bodyPlaceholder")}
        onChange={(event) => onChange({ body: event.target.value })}
      />

      <div className="space-y-2">
        <div className="flex items-center gap-2">
          <ImagePicker
            variant="button"
            buttonSize="sm"
            accept="image/png,image/jpeg,image/webp,image/gif"
            disabled={upload.isPending}
            onSelect={handleFile}
          >
            {upload.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <ImagePlus className="h-4 w-4" />
            )}
            {section.image_url ? t("operator.replaceImage") : t("operator.addImage")}
          </ImagePicker>
          {section.image_url ? (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => onChange({ image_url: null })}
            >
              {t("operator.removeImage")}
            </Button>
          ) : null}
        </div>

        {previewSrc ? (
          <>
            <img
              src={previewSrc}
              alt={section.image_alt ?? ""}
              className="max-h-48 w-full rounded border object-contain"
            />
            <Input
              value={section.image_alt ?? ""}
              maxLength={200}
              placeholder={t("operator.fields.altPlaceholder")}
              onChange={(event) => onChange({ image_alt: event.target.value })}
            />
          </>
        ) : null}
      </div>
    </div>
  );
};
