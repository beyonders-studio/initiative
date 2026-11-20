/**
 * A tool plug-in's row on its own page, drawn from the detail layout its table
 * declared: its name and declared fields, each with its kind's editor, the
 * initiative's properties, and the parts every tool's page has.
 */

import type { ComponentType, ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { PluginToolRowUpdate } from "@/api/generated/initiativeAPI.schemas";
import { ToolCommentsPanel } from "@/components/comments/ToolCommentsPanel";
import { TagsField } from "@/components/tags/TagsField";
import { useSearchMembers } from "@/hooks/useUsers";
import { type InitiativeDetail, useInitiativeExtension } from "@/lib/layouts/initiativeExtension";
import {
  fieldChange,
  fieldSummary,
  fieldValue,
  type ToolFieldDecl,
  type ToolRow,
  type ToolTable,
  toolText,
  withChange,
} from "@/lib/toolPlugins";
import { ColorPickerPopover } from "@/ui/color-picker-popover";
import { type ItemHome, useItemContext, useItemHome } from "@/ui/layouts/DetailLayoutView";
import { at, detailLayoutSpec, type Region } from "@/ui/layouts/detailLayout";
import { FieldFrame, ReadField, sameJson, useFieldDraft } from "@/ui/layouts/editing";
import { type ItemSaves, TitleField } from "@/ui/layouts/fieldEditors";
import { type FieldDef, withDisplays } from "@/ui/layouts/fields";
import type { LayoutNode } from "@/ui/layouts/tree";
import { formatDateTime } from "@/ui/lib/formatDate";
import type { CounterFocusHost } from "@/ui/properties/CounterFocus";
import { PropertyInput } from "@/ui/properties/PropertyInput";
import { PropertyValueCell } from "@/ui/properties/PropertyValueCell";
import { type FieldDisplay, isEmptyPropertyValue } from "@/ui/properties/propertyHelpers";

import { toolFields } from "./toolFields";

/** What a row's page shares with its parts. */
export interface ToolRowContext {
  /** The server says the reader cannot change the row. */
  readOnly: boolean;
  initiativeId: number;
  /** How its fields are saved, each on its own. */
  saves: ItemSaves<ToolRow, PluginToolRowUpdate>;
  /** The menu of what else can be done with it. */
  actions: ReactNode;
  /** A counter field's full screen on the row's own page, by the field's
   *  key: whether it is open, and the rows it moves between. Elsewhere it
   *  opens on its own. */
  focus?: (field: string) => CounterFocusHost;
}

type EditorProps = { item: ToolRow; label: string };

const useRowHome = () => useItemHome() as ItemHome<ToolRow, PluginToolRowUpdate>;

const NameEditor = ({ item, label }: EditorProps) => {
  const { t } = useTranslation("plugins");
  const home = useRowHome();
  return (
    <TitleField
      id={`tool-row-name-${item.id}`}
      field="name"
      label={label}
      value={item.name}
      save={home.saves.useSave(label)}
      readOnly={home.readOnly}
      placeholder={t("tool.namePlaceholder")}
    />
  );
};

/** Its tags, picked as any tool's are and saved the moment they are. */
const TagsEditor = ({ item, label }: EditorProps) => {
  const { t } = useTranslation("tags");
  const home = useRowHome();
  return (
    <TagsField
      label={label}
      tags={item.tags}
      save={home.saves.useSave(label)}
      readOnly={home.readOnly}
      placeholder={t("picker.defaultPlaceholder")}
    />
  );
};

/**
 * One declared field, saved on its own: a colour with the colour picker, any
 * other kind with the editor a property of its kind has, a scale or a counter
 * in the look its table's lists draw it in (`look`). Its options are the
 * declaration's, so none is made from what is typed. A counter opens full
 * screen under the row's name, on the colour its `tint` field holds. A reader
 * sees its value, and nothing where it holds none.
 */
const DeclaredFieldEditor = ({
  field,
  look,
  tint,
  item,
  label,
}: EditorProps & {
  field: ToolFieldDecl;
  look: FieldDef<ToolRow> | undefined;
  tint: ToolFieldDecl | undefined;
}) => {
  const { i18n } = useTranslation();
  const home = useRowHome();
  const { focus } = useItemContext<ToolRowContext>();
  const save = home.saves.useSave(label);
  const saved = fieldValue(item, field);
  const display = look?.displayOf?.(item) ?? look?.display;
  const draft = useFieldDraft<unknown>(
    saved,
    (value) => {
      const change = fieldChange(field, value);
      const { fields, people } = withChange(item, change);
      return save.save({ patch: change, shows: { fields, people } });
    },
    sameJson
  );
  const summary = fieldSummary(field, item, i18n.language);
  if (home.readOnly) {
    if (isEmptyPropertyValue(saved)) return null;
    return (
      <ReadField label={label}>
        {field.kind === "color" ? (
          <span
            className="block h-5 w-5 rounded-full border"
            style={{ backgroundColor: String(saved) }}
          >
            <span className="sr-only">{String(saved)}</span>
          </span>
        ) : (
          <PropertyValueCell summary={summary} variant="cell" display={display} />
        )}
      </ReadField>
    );
  }
  return (
    <FieldFrame label={label} save={save} changed={draft.changed} keys={draft.keys}>
      <ToolFieldInput
        field={field}
        row={item}
        label={label}
        value={draft.value}
        onChange={draft.edit}
        initiativeId={home.initiativeId}
        canOpen={home.canOpen}
        display={display}
        focus={
          field.kind === "counter"
            ? {
                name: item.name || label,
                color: tint ? ((fieldValue(item, tint) as string | null) ?? null) : null,
                ...focus?.(field.key),
              }
            : undefined
        }
      />
    </FieldFrame>
  );
};

/** A declared field's editor: the colour picker for a colour, the editor a
 *  property of its kind has for any other, drawn as `display` says. `row`
 *  gives a counter its bounds, and `focus` its full screen. */
export const ToolFieldInput = ({
  field,
  row,
  label,
  value,
  onChange,
  initiativeId,
  canOpen,
  display,
  focus,
}: {
  field: ToolFieldDecl;
  row: ToolRow;
  label: string;
  value: unknown;
  onChange: (value: unknown) => void;
  initiativeId?: number | null;
  canOpen?: { tool: string; id: number };
  display?: FieldDisplay | null;
  focus?: CounterFocusHost;
}) => {
  const { i18n } = useTranslation();
  const searchMembers = useSearchMembers();
  return field.kind === "color" ? (
    <ColorPickerPopover
      value={String(value ?? "")}
      onChangeComplete={onChange}
      triggerLabel={label}
    />
  ) : (
    <PropertyInput
      definition={fieldSummary(field, row, i18n.language)}
      value={value}
      onChange={onChange}
      initiativeId={initiativeId}
      canOpen={canOpen}
      searchMembers={searchMembers}
      display={display}
      focus={focus}
    />
  );
};

/** Who can change it, said where it cannot be. */
const Notice = () => {
  const { t } = useTranslation("plugins");
  const { readOnly } = useItemContext<ToolRowContext>();
  return readOnly ? (
    <p className="rounded-md border border-border bg-muted/50 px-3 py-2 text-muted-foreground text-sm">
      {t("tool.readOnly")}
    </p>
  ) : null;
};

/** When it was added and last changed. */
const Byline = ({ row }: { row: ToolRow }) => {
  const { t } = useTranslation("plugins");
  return (
    <p className="text-muted-foreground text-xs">
      {t("tool.byline", {
        added: formatDateTime(row.created_at),
        changed: formatDateTime(row.updated_at),
      })}
    </p>
  );
};

/** Its comments, the thread every tool's row has. */
const Comments = ({ row, kind }: { row: ToolRow; kind: string }) => (
  <ToolCommentsPanel tool={kind} entity={row} />
);

/** A declared layout's regions, a region it leaves out holding nothing. On
 *  one column the main column's parts come first, then the side's. */
const regionsOf = (table: ToolTable): Record<Region, LayoutNode[]> => {
  const { header, main, side } = table.layouts.detail as Partial<
    Record<Region, LayoutNode[] | null>
  >;
  const columns = [...(main ?? []), ...(side ?? [])].map((node, index) => at(index + 1, node));
  return {
    header: header ?? [],
    main: columns.slice(0, main?.length ?? 0),
    side: columns.slice(main?.length ?? 0),
  };
};

/** How a table's lists draw its scales and counters, the first list that
 *  says so for a field winning: what its rows' page draws them as. */
const listDisplays = (table: ToolTable) =>
  Object.assign({}, ...table.layouts.lists.map((list) => list.displays ?? {}).reverse());

/**
 * One table's rows' detail: the layout it declared, as shipped, with an
 * editor for its name and each field it declares. Its rows' links, its
 * properties and its comments are the ones every tool's rows have.
 */
export const toolDetail = (
  table: ToolTable,
  language: string
): InitiativeDetail<ToolRow, ToolRowContext, PluginToolRowUpdate> => {
  const looks = withDisplays(toolFields(table, language), listDisplays(table));
  const tint = table.fields.find((field) => field.kind === "color");
  return {
    spec: detailLayoutSpec({
      kind: table.kind,
      shipped: regionsOf(table),
      fieldParts: ["field", "properties"],
    }),
    fields: (_definitions, added) =>
      new Map([
        ...toolFields(table, language),
        ...added.map((field) => [field.id, field] as const),
      ]),
    namespaces: ["plugins", "common", "tags"],
    editors: {
      name: NameEditor,
      tags: TagsEditor,
      ...Object.fromEntries(
        table.fields.map((field): [string, ComponentType<EditorProps>] => [
          field.key,
          (props) => (
            <DeclaredFieldEditor {...props} field={field} look={looks.get(field.key)} tint={tint} />
          ),
        ])
      ),
    },
    parts: {
      byline: (_node, row) => <Byline row={row} />,
      notice: () => <Notice />,
      comments: (_node, row) => <Comments row={row} kind={table.kind} />,
      // Its rows hold none of the initiative's properties.
      properties: () => null,
    },
    home: (row, context) => ({
      saves: context.saves,
      readOnly: context.readOnly,
      initiativeId: context.initiativeId,
      canOpen: { tool: table.kind, id: row.id },
      links: {
        entity: { id: row.id, initiative_id: context.initiativeId },
        title: row.name || toolText(table.name, language),
      },
      actions: context.actions,
    }),
    useExtension: useInitiativeExtension,
  };
};
