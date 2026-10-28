import { useContext } from "react";
import { useTranslation } from "react-i18next";

import {
  type CollectionFileSummary,
  type CollectionRead,
  PropertyTarget,
  Tool,
} from "@/api/generated/initiativeAPI.schemas";
import { nonEmptyPropertySummaries } from "@/components/properties/propertyHelpers";
import { collectionMetadataSaves } from "@/hooks/useCollections";
import { propertySaves } from "@/hooks/useProperties";
import type { TranslateFn } from "@/types/i18n";

import { type DetailKind, useItemContext } from "./DetailLayoutView";
import { filledBy, PlacedProperties } from "./detailLayout";
import { ReadField } from "./editing";
import { PlacedPropertyField } from "./fieldEditors";
import { FIELD_RENDERERS, isEmptyValue, type LayoutItem, PROPERTY_FIELD_PREFIX } from "./fields";
import { collectionFileFields, FILE_LAYOUT } from "./files";
import type { LayoutContext } from "./tree";

/** What a file's detail shares with its parts, beside the file itself. */
export interface FileLayoutContext {
  /** The collection it is opened from: its metadata, and whether the reader
   *  may change it. */
  collection: CollectionRead;
}

const useFileLayout = useItemContext<FileLayoutContext>;

/** One of the collection's metadata, saved as the collection's by whoever may
 *  change it; or one of the initiative's properties, which the file holds and
 *  its own page changes. */
const FileProperty = ({
  file,
  propertyId,
}: {
  file: CollectionFileSummary;
  propertyId: number;
}) => {
  const { collection } = useFileLayout();
  const own = collection.metadata.some((each) => each.id === propertyId);
  return own ? (
    <PlacedPropertyField
      kind={collectionMetadataSaves(collection.id)}
      id={file.id}
      properties={file.metadata}
      readOnly={!collection.can.edit}
      initiativeId={collection.initiative_id}
      propertyId={propertyId}
      definitions={collection.metadata}
    />
  ) : (
    <PlacedPropertyField
      kind={propertySaves[PropertyTarget.file]}
      id={file.id}
      properties={file.properties}
      readOnly
      initiativeId={collection.initiative_id}
      canOpen={{ tool: Tool.file, id: file.id }}
      propertyId={propertyId}
    />
  );
};

/** A field by its id: a property, or one of the file's own, which reads as
 *  its lists draw it. */
const FileField = ({
  id,
  file,
  view,
}: {
  id: string;
  file: CollectionFileSummary;
  view: LayoutContext;
}) => {
  const t = useTranslation(["files", "common"]).t as TranslateFn;
  if (id.startsWith(PROPERTY_FIELD_PREFIX)) {
    return <FileProperty file={file} propertyId={Number(id.slice(PROPERTY_FIELD_PREFIX.length))} />;
  }
  const field = view.fields.get(id);
  const item = file as unknown as LayoutItem;
  const value = field?.value(item);
  if (!field || isEmptyValue(value)) return null;
  if (field.kind === "fileName") {
    return <h2 className="min-w-0 break-words font-semibold text-lg">{file.name}</h2>;
  }
  const Renderer = FIELD_RENDERERS[field.kind];
  return (
    <ReadField label={t(field.label)}>
      <Renderer value={value} item={item} field={field} variant="cell" env={view.env} />
    </ReadField>
  );
};

/** The collection's metadata, then the properties the file holds, but for
 *  those the layout places on their own. A reader sees only those that hold a
 *  value. */
const FileProperties = ({ file }: { file: CollectionFileSummary }) => {
  const { collection } = useFileLayout();
  const placed = useContext(PlacedProperties);
  const ids = [
    ...collection.metadata.map((each) => each.id),
    ...nonEmptyPropertySummaries(file.properties).map((each) => each.property_id),
  ].filter((id) => !placed.has(id));
  return ids.map((id) => (
    // Keyed by the file too: moving to the next file starts afresh.
    <FileProperty key={`${file.id}:${id}`} file={file} propertyId={id} />
  ));
};

/** A file opened from a collection: its own fields, the collection's metadata
 *  and the initiative's properties. */
export const FILE_DETAIL: DetailKind<CollectionFileSummary, FileLayoutContext, never> = {
  spec: FILE_LAYOUT,
  fields: (definitions) => collectionFileFields([], definitions),
  namespaces: ["files", "common"],
  // Its own fields are not edited here; the parts draw every field.
  editors: {},
  parts: {
    field: (node, file, view) => (
      <FileField id={String(node.props?.field)} file={file} view={view} />
    ),
    properties: (_node, file) => <FileProperties file={file} />,
  },
  home: (file, { collection }) => ({
    saves: collectionMetadataSaves(collection.id),
    readOnly: !collection.can.edit,
    initiativeId: collection.initiative_id,
    canOpen: { tool: Tool.file, id: file.id },
    links: { entity: file },
  }),
  // A collection requires its own metadata, which the file holds there.
  filled: filledBy<CollectionFileSummary>({}, (file) => file.metadata),
};
