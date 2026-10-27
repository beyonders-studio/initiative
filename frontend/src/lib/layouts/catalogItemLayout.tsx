import { ImagePlus, Loader2, Trash2 } from "lucide-react";
import { type ComponentType, type ReactNode, type RefObject, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  type CatalogItemRead,
  type CatalogItemUpdate,
  type CatalogItemVersionRead,
  SearchEntityType,
  Tool,
} from "@/api/generated/initiativeAPI.schemas";
import { LazyImage } from "@/components/shared/LazyImage";
import { UserName } from "@/components/UserHandle";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { DateTimePicker } from "@/components/ui/date-time-picker";
import { ImagePicker } from "@/components/ui/image-picker";
import { RelativeTime } from "@/components/ui/relative-time";
import { ProfileAvatar } from "@/components/user/ProfileAvatar";
import {
  catalogItemSaves,
  useCatalogItemVersions,
  useDeleteCatalogItemVersion,
  useUploadCatalogItemVersion,
} from "@/hooks/useCatalogs";
import { type ItemFieldSave, useItemFieldSave } from "@/hooks/useFieldSave";
import { ACCEPT_ATTRIBUTE, imageLabel, imageSrc, refuseFile } from "@/lib/catalogs";
import { formatBytes } from "@/lib/fileUtils";
import { formatDate } from "@/lib/formatDate";
import { toast } from "@/lib/mascotToast";
import { referenceRef } from "@/lib/smartChips";
import { resolveUploadUrl } from "@/lib/uploadUrl";

import { type CATALOG_ITEM_FIELDS, CATALOG_ITEM_LAYOUT, catalogItemFields } from "./catalogItems";
import { type DetailKind, useItemContext } from "./DetailLayoutView";
import { FieldFrame, ReadField } from "./editing";
import { DescriptionField, TagsField, TitleField } from "./fieldEditors";

/** What a picture's detail shares with its parts, beside the picture itself. */
export interface CatalogItemLayoutContext {
  /** The server says the reader cannot change the picture. */
  readOnly: boolean;
  catalogId: number;
  /** The catalog's initiative; a community's own catalog has none, and so no
   *  properties or links. */
  initiativeId: number | null;
  /** Whether the reader may delete one of its versions. */
  canDeleteVersions: boolean;
  /** Set when the detail is left on purpose, so an open draft does not hold it. */
  leaving: RefObject<boolean>;
  /** Reporting it, and the menu of what else can be done with it. */
  actions: ReactNode;
  /** Drawn in the layout editor, where nothing is changed. */
  preview?: boolean;
}

const useCatalogItemLayout = useItemContext<CatalogItemLayoutContext>;

type EditorProps = { item: CatalogItemRead; label: string };
type Save = ItemFieldSave<CatalogItemRead, CatalogItemUpdate>;

/** A field's save, for the catalog the picture is in. */
const useSave = (image: CatalogItemRead, label: string): Save =>
  useItemFieldSave(catalogItemSaves(useCatalogItemLayout().catalogId), image.id, label);

const TitleEditor = ({ item: image, label }: EditorProps) => {
  const { t } = useTranslation("catalogs");
  return (
    <TitleField
      id="catalog-item-title"
      label={label}
      value={image.title ?? ""}
      save={useSave(image, label)}
      readOnly={useCatalogItemLayout().readOnly}
      placeholder={image.original_filename || t("sheet.titlePlaceholder")}
      optional
      subscribe={{ kind: "catalog_item", id: image.id }}
    />
  );
};

/** The description, as a task's is ({@link DescriptionField}). */
const DescriptionEditor = ({ item: image, label }: EditorProps) => {
  const { t } = useTranslation("catalogs");
  const context = useCatalogItemLayout();
  return (
    <DescriptionField
      kind={catalogItemSaves(context.catalogId)}
      id={image.id}
      options={{}}
      label={label}
      htmlId="catalog-item-description"
      value={image.description ?? null}
      readOnly={context.readOnly}
      initiativeId={context.initiativeId}
      subject={referenceRef(SearchEntityType.catalog_item, image.id)}
      leaving={context.leaving}
      preview={context.preview}
      placeholder={t("sheet.descriptionPlaceholder")}
    />
  );
};

/** The day it is about, saved as it is picked. Every item has one, so there
 *  is nothing to clear. */
const DateEditor = ({ item: image, label }: EditorProps) => {
  const { readOnly } = useCatalogItemLayout();
  const save = useSave(image, label);
  if (readOnly) {
    return <ReadField label={label}>{formatDate(image.occurred_on)}</ReadField>;
  }
  return (
    <FieldFrame label={label} save={save}>
      <DateTimePicker
        id="catalog-item-date"
        value={image.occurred_on}
        includeTime={false}
        onChange={(next) => {
          if (next && next !== image.occurred_on) {
            void save.save({ patch: { occurred_on: next }, shows: { occurred_on: next } });
          }
        }}
      />
    </FieldFrame>
  );
};

const TagsEditor = ({ item: image, label }: EditorProps) => {
  const { t } = useTranslation("catalogs");
  return (
    <TagsField
      label={label}
      tags={image.tags}
      save={useSave(image, label)}
      readOnly={useCatalogItemLayout().readOnly}
      placeholder={t("sheet.tags")}
    />
  );
};

/** The picture itself. */
const Picture = ({ image }: { image: CatalogItemRead }) => (
  <LazyImage
    src={imageSrc(image)}
    alt={imageLabel(image)}
    aspectRatio={image.width && image.height ? image.width / image.height : 4 / 3}
    className="w-full rounded-lg"
    imgClassName="object-contain"
  />
);

/** Where it came from: who added it and when, and the file. */
const About = ({ image }: { image: CatalogItemRead }) => {
  const { t } = useTranslation("catalogs");
  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-sm">
      <dt className="text-muted-foreground">{t("sheet.uploadedBy")}</dt>
      <dd className="flex min-w-0 items-center gap-2">
        {image.uploader ? (
          <>
            <ProfileAvatar
              user={image.uploader}
              decorations={image.uploader.profile_decorations}
              presence={image.uploader.presence}
              className="size-5 shrink-0"
            />
            <UserName user={image.uploader} nameClassName="min-w-0 truncate" />
          </>
        ) : (
          "—"
        )}
      </dd>
      <dt className="text-muted-foreground">{t("sheet.added")}</dt>
      <dd>
        <RelativeTime date={image.created_at} />
      </dd>
      {image.width && image.height ? (
        <>
          <dt className="text-muted-foreground">{t("sheet.dimensions")}</dt>
          <dd className="tabular-nums">
            {image.width} × {image.height}
          </dd>
        </>
      ) : null}
      {image.file_size ? (
        <>
          <dt className="text-muted-foreground">{t("sheet.size")}</dt>
          <dd>{formatBytes(image.file_size)}</dd>
        </>
      ) : null}
      {image.original_filename ? (
        <>
          <dt className="text-muted-foreground">{t("sheet.filename")}</dt>
          <dd className="truncate">{image.original_filename}</dd>
        </>
      ) : null}
    </dl>
  );
};

/** Its history: where a design round is replaced rather than added to, the
 *  earlier rounds are the story of how it got there. */
const Versions = ({ image }: { image: CatalogItemRead }) => {
  const { t } = useTranslation(["catalogs", "common"]);
  const { catalogId, readOnly, canDeleteVersions, preview } = useCatalogItemLayout();
  const versions = useCatalogItemVersions(catalogId, image.id).data ?? [];
  const upload = useUploadCatalogItemVersion(catalogId, {
    onSuccess: () => toast.success(t("sheet.versionUploaded")),
  });
  const [pendingDelete, setPendingDelete] = useState<CatalogItemVersionRead | null>(null);
  const remove = useDeleteCatalogItemVersion(catalogId, {
    onSuccess: () => {
      setPendingDelete(null);
      toast.success(t("sheet.versionDeleted"));
    },
  });
  return (
    <section className="space-y-2">
      <div className="flex items-center justify-between gap-2">
        <h3 className="font-medium text-sm">{t("sheet.versions")}</h3>
        {readOnly || preview ? null : (
          <ImagePicker
            variant="button"
            buttonSize="sm"
            accept={ACCEPT_ATTRIBUTE}
            disabled={upload.isPending}
            onSelect={(file) => {
              if (refuseFile(file)) {
                toast.error(t("upload.refusedType"));
                return;
              }
              upload.mutate({ itemId: image.id, file });
            }}
          >
            {upload.isPending ? (
              <Loader2 className="size-4 animate-spin" />
            ) : (
              <ImagePlus className="size-4" />
            )}
            {t("sheet.uploadVersion")}
          </ImagePicker>
        )}
      </div>
      <ul className="divide-y rounded-md border">
        {versions.map((version) => (
          <li key={version.id} className="flex items-center gap-3 p-2 text-sm">
            <LazyImage
              src={resolveUploadUrl(version.thumbnail_url ?? version.file_url)}
              alt=""
              className="size-12 shrink-0 rounded"
            />
            <div className="min-w-0 flex-1">
              <p className="truncate">
                {t("sheet.versionLabel", { number: version.version_number })}
                {version.is_current && (
                  <span className="ml-2 text-muted-foreground text-xs">{t("sheet.current")}</span>
                )}
              </p>
              <p className="text-muted-foreground text-xs">
                <RelativeTime date={version.created_at} />
                {version.file_size ? ` · ${formatBytes(version.file_size)}` : ""}
              </p>
            </div>
            {canDeleteVersions && versions.length > 1 && !preview && (
              <Button
                variant="ghost"
                size="icon"
                className="size-8 text-muted-foreground hover:text-destructive"
                aria-label={t("sheet.deleteVersion")}
                onClick={() => setPendingDelete(version)}
              >
                <Trash2 className="size-4" />
              </Button>
            )}
          </li>
        ))}
      </ul>
      <ConfirmDialog
        open={pendingDelete !== null}
        onOpenChange={(next) => !next && setPendingDelete(null)}
        title={t("sheet.deleteVersionTitle")}
        description={t("sheet.deleteVersionDescription", {
          number: pendingDelete?.version_number ?? 0,
        })}
        confirmLabel={t("common:delete")}
        cancelLabel={t("common:cancel")}
        isLoading={remove.isPending}
        destructive
        onConfirm={() => {
          if (pendingDelete) remove.mutate({ itemId: image.id, versionId: pendingDelete.id });
        }}
      />
    </section>
  );
};

/** A picture's detail: its fields, its own parts and where it lives. */
export const CATALOG_ITEM_DETAIL: DetailKind<
  CatalogItemRead,
  CatalogItemLayoutContext,
  CatalogItemUpdate
> = {
  spec: CATALOG_ITEM_LAYOUT,
  fields: catalogItemFields,
  namespaces: ["catalogs", "common"],
  editors: {
    title: TitleEditor,
    description: DescriptionEditor,
    date: DateEditor,
    tags: TagsEditor,
  } satisfies Record<keyof typeof CATALOG_ITEM_FIELDS, ComponentType<EditorProps>>,
  parts: {
    picture: (_node, image) => <Picture image={image} />,
    about: (_node, image) => <About image={image} />,
    versions: (_node, image) => <Versions image={image} />,
  },
  home: (image, context) => ({
    saves: catalogItemSaves(context.catalogId),
    readOnly: context.readOnly,
    initiativeId: context.initiativeId,
    canOpen: { tool: Tool.catalog, id: context.catalogId },
    links: {
      entity: { id: context.catalogId, initiative_id: context.initiativeId },
      target: { type: SearchEntityType.catalog_item, id: image.id },
      title: image.title ?? undefined,
    },
    actions: context.actions,
  }),
};
