import { EyeClosed } from "lucide-react";
import { type ReactNode, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { MetadataType, type PropertyDefinitionRead } from "@/api/generated/initiativeAPI.schemas";
import { Button } from "@/ui/button";
import { Field } from "@/ui/field";
import { host } from "@/ui/host";
import { Input } from "@/ui/input";
import { Label } from "@/ui/label";
import { LAYOUT_REGIONS } from "@/ui/layouts/detailLayout";
import {
  cardOf,
  type ListLayout,
  MAX_TITLE_LENGTH,
  type NodePath,
  nodeAt,
  removable,
  type Selection,
} from "@/ui/layouts/draft";
import type { FieldDef, LayoutEnv } from "@/ui/layouts/fields";
import type { LayoutNode } from "@/ui/layouts/tree";
import { listFormat } from "@/ui/lib/intl";
import {
  COUNTER_DISPLAYS,
  type FieldDisplay,
  SCALE_DISPLAYS,
} from "@/ui/properties/propertyHelpers";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/ui/select";
import { Switch } from "@/ui/switch";

import type { EditableDetail, LayoutEdits } from "./LayoutEditor";
import { type EditablePresets, LayoutPresets } from "./LayoutPresets";

type Translate = LayoutEnv["t"];

/**
 * The settings of the one thing selected, and only those: the list layout's
 * own (whether the project opens on it, and putting it back as shipped) on the
 * layout, a group's arrangement on a group, and a way to take a part off the
 * card or a column out of the table, where it may go.
 */
export const ListLayoutSettings = ({
  t,
  name,
  layout,
  presets,
  help,
  opensFirst,
  shown,
  stored,
  fields,
  settings,
  selection,
  edits,
  locked,
  metadataHref,
}: {
  /** Reads the words of the kind it lists. */
  t: Translate;
  /** What the list is called. */
  name: string;
  layout: ListLayout;
  /** The presets it offers; a list of files offers none. */
  presets?: EditablePresets;
  /** Its settings of its kind's own, after its presets. */
  settings?: ReactNode;
  /** What the list is, as a key. */
  help: string;
  /** Whether the target opens on it; left out where it has no other list. */
  opensFirst?: boolean;
  /** Whether the target's menu offers it, and whether it may stop: one list
   *  always shows. Left out where a target shows every list it has. */
  shown?: { value: boolean; canHide: boolean };
  /** Whether the project changed it, as against drawing it as shipped. */
  stored: boolean;
  fields: ReadonlyMap<string, FieldDef>;
  selection: Selection;
  edits: LayoutEdits;
  /** A save is under way, and nothing changes until it answers. */
  locked: boolean;
  /** Where the initiative's metadata is edited. */
  metadataHref: string;
}) => {
  // The field selected, as a column or a part of the card.
  const selectedField =
    selection.kind === "column"
      ? selection.field
      : selection.kind === "part"
        ? (() => {
            const node = nodeAt(cardOf(layout.definition, fields, layout.shape), selection.path);
            return node?.type === "field" ? String(node.props?.field) : null;
          })()
        : null;
  // A scale or a counter selected, which the list may draw in more than one way.
  const drawnType = selectedField !== null ? fields.get(selectedField)?.property?.type : undefined;
  const drawn =
    drawnType === MetadataType.scale || drawnType === MetadataType.counter ? drawnType : null;
  return (
    // Disabled as one, so a save under way leaves every control as it was.
    <fieldset disabled={locked} className="min-w-0">
      {selection.kind === "layout" ? (
        <Panel heading={name}>
          <p className="text-muted-foreground text-sm">{t(help)}</p>
          {shown ? (
            <div className="flex items-center justify-between gap-2">
              <Label htmlFor="layout-shown">{t("layouts:shownInMenu")}</Label>
              <Switch
                id="layout-shown"
                checked={shown.value}
                // The last list shown stays shown.
                disabled={shown.value && !shown.canHide}
                onCheckedChange={edits.showList}
              />
            </div>
          ) : null}
          {opensFirst !== undefined && shown?.value !== false ? (
            <div className="flex items-center justify-between gap-2">
              <Label htmlFor="layout-default">{t("layouts:opensFirst")}</Label>
              <Switch
                id="layout-default"
                checked={opensFirst}
                // The project always opens on one list: choosing another is how
                // this one stops being it.
                disabled={opensFirst}
                onCheckedChange={(checked) => {
                  if (checked) edits.makeDefault();
                }}
              />
            </div>
          ) : null}
          {presets ? (
            <LayoutPresets t={t} layout={layout} of={presets} fields={fields} edits={edits} />
          ) : null}
          {settings}
          <Shipped t={t} stored={stored} edits={edits} />
        </Panel>
      ) : selection.kind === "column" ? (
        <ColumnSettings field={selection.field} fields={fields} edits={edits} />
      ) : (
        <PartSettings
          t={t}
          tree={cardOf(layout.definition, fields, layout.shape)}
          path={selection.path}
          fields={fields}
          edits={edits}
        />
      )}
      {selectedField !== null && drawn !== null ? (
        <DisplaySetting
          type={drawn}
          value={layout.definition.displays?.[selectedField] ?? "number"}
          onChange={(display) => edits.changeDisplay(selectedField, display)}
        />
      ) : null}
      {selectedField !== null ? (
        <MetadataFieldNote field={selectedField} fields={fields} href={metadataHref} />
      ) : null}
    </fieldset>
  );
};

/** Where the initiative's metadata a selected field shows is edited: the
 *  initiative's settings, which this links to. The target's own properties
 *  are managed in its properties panel. */
const MetadataFieldNote = ({
  field,
  fields,
  href,
}: {
  field: string;
  fields: ReadonlyMap<string, FieldDef>;
  href: string;
}) => {
  const { t } = useTranslation(["layouts"]);
  const definition = fields.get(field)?.property;
  if (!definition || definition.project_id !== null || definition.collection_id !== null) {
    return null;
  }
  return (
    <Panel heading={t("layouts:fieldProperty.metadata")}>
      <p className="text-muted-foreground text-sm">{t("layouts:fieldProperty.metadataHelp")}</p>
      <Button type="button" variant="outline" size="sm" asChild>
        <host.Link to={href}>{t("layouts:fieldProperty.openSettings")}</host.Link>
      </Button>
    </Panel>
  );
};

/** How the list draws the scale or counter selected: a scale as a number,
 *  five stars or a bar; a counter as a number, a bar or a clock. */
const DisplaySetting = ({
  type,
  value,
  onChange,
}: {
  type: typeof MetadataType.scale | typeof MetadataType.counter;
  value: FieldDisplay;
  onChange: (display: FieldDisplay) => void;
}) => {
  const { t } = useTranslation(["layouts"]);
  const [label, offered] =
    type === MetadataType.scale
      ? [
          t("layouts:scaleDisplay.label"),
          SCALE_DISPLAYS.map((display) => [display, t(`layouts:scaleDisplay.${display}`)]),
        ]
      : [
          t("layouts:counterDisplay.label"),
          COUNTER_DISPLAYS.map((display) => [display, t(`layouts:counterDisplay.${display}`)]),
        ];
  return (
    <Field label={label} className="px-4 pb-4">
      <Select
        value={offered.some(([display]) => display === value) ? value : "number"}
        onValueChange={(next) => onChange(next as FieldDisplay)}
      >
        <SelectTrigger>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {offered.map(([display, name]) => (
            <SelectItem key={display} value={display}>
              {name}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </Field>
  );
};

/** Putting the open layout back as shipped, or saying it already is. */
const Shipped = ({
  t,
  stored,
  edits,
  shipped = "layouts:shipped",
}: {
  t: Translate;
  stored: boolean;
  edits: LayoutEdits;
  /** What says the layout is as shipped. */
  shipped?: string;
}) =>
  stored ? (
    <Button type="button" variant="outline" size="sm" onClick={edits.resetLayout}>
      {t("layouts:useShipped")}
    </Button>
  ) : (
    <p className="text-muted-foreground text-xs">{t(shipped)}</p>
  );

/** The settings of what is selected on a task's detail: the layout's own, or
 *  a part's. */
export const DetailLayoutSettings = ({
  t,
  detail,
  of,
  stored,
  fields,
  selection,
  edits,
  locked,
  metadataHref,
}: {
  /** Reads the words of the kind it lays out. */
  t: Translate;
  /** The detail as one tree: the layout, holding its header, main and side. */
  detail: LayoutNode;
  of: EditableDetail;
  /** Whether the target lays out its own detail, as against the shipped one. */
  stored: boolean;
  fields: ReadonlyMap<string, FieldDef>;
  selection: Selection;
  edits: LayoutEdits;
  locked: boolean;
  /** Where the initiative's metadata is edited. */
  metadataHref: string;
}) => {
  const node = selection.kind === "part" ? nodeAt(detail, selection.path) : undefined;
  return (
    <fieldset disabled={locked} className="min-w-0">
      {selection.kind === "part" ? (
        <>
          <PartSettings
            t={t}
            tree={detail}
            path={selection.path}
            fields={fields}
            edits={edits}
            on={of}
          />
          {node?.type === "field" ? (
            <MetadataFieldNote
              field={String(node.props?.field)}
              fields={fields}
              href={metadataHref}
            />
          ) : null}
        </>
      ) : (
        <Panel heading={t(of.words.name, { name: of.typeName })}>
          <p className="text-muted-foreground text-sm">{t(of.words.help)}</p>
          <Shipped t={t} stored={stored} edits={edits} shipped={of.words.shipped} />
        </Panel>
      )}
    </fieldset>
  );
};

/** The target's own properties, managed beside its layouts: `list` draws
 *  them, each with the layouts that show it, as `shownOn` names them. */
export const LayoutProperties = ({
  list,
  shownOn,
}: {
  list: (placement: (definition: PropertyDefinitionRead) => string) => ReactNode;
  shownOn: (propertyId: number) => string[];
}) => {
  const { t, i18n } = useTranslation(["layouts"]);
  return (
    <Panel heading={t("layouts:properties")}>
      {list((definition) => {
        const names = shownOn(definition.id);
        return names.length > 0
          ? t("layouts:propertiesShownOn", {
              layouts: listFormat(i18n.language).format(names),
            })
          : t("layouts:propertiesNowhere");
      })}
      <p className="text-muted-foreground text-xs">{t("layouts:propertiesPlacementHelp")}</p>
    </Panel>
  );
};

const ColumnSettings = ({
  field,
  fields,
  edits,
}: {
  field: string;
  fields: ReadonlyMap<string, FieldDef>;
  edits: LayoutEdits;
}) => {
  const { t } = useTranslation(["layouts"]);
  const keeps = fields.get(field)?.hideable === false;
  return (
    <Panel heading={t("layouts:column")}>
      <p className="text-muted-foreground text-sm">
        {t(keeps ? "layouts:titleHelp" : "layouts:columnHelp")}
      </p>
      {keeps ? null : (
        <Button type="button" variant="outline" size="sm" onClick={() => edits.removeColumn(field)}>
          <EyeClosed className="h-4 w-4" aria-hidden="true" />
          {t("layouts:hidePart")}
        </Button>
      )}
    </Panel>
  );
};

/** One part of a card or a page: how a group or a section is arranged, what
 *  the part does, and taking it off where it may go. */
const PartSettings = ({
  t,
  tree,
  path,
  fields,
  edits,
  on,
}: {
  t: Translate;
  tree: LayoutNode;
  path: NodePath;
  fields: ReadonlyMap<string, FieldDef>;
  edits: LayoutEdits;
  /** The detail the part is on; none on a card. */
  on?: EditableDetail;
}) => {
  const node = nodeAt(tree, path);
  if (!node) return null;
  if (node.type === "card") {
    return (
      <Panel heading={t("layouts:card")}>
        <p className="text-muted-foreground text-sm">{t("layouts:cardHelp")}</p>
      </Panel>
    );
  }
  if ((LAYOUT_REGIONS as readonly string[]).includes(node.type)) {
    return (
      <Panel heading={t(`layouts:parts.${node.type}`)}>
        <p className="text-muted-foreground text-sm">{t(`layouts:regionHelp.${node.type}`)}</p>
      </Panel>
    );
  }
  const canRemove = removable(node, fields);
  const remove = canRemove ? (
    <Button type="button" variant="outline" size="sm" onClick={() => edits.removePart(path)}>
      <EyeClosed className="h-4 w-4" aria-hidden="true" />
      {t("layouts:hidePart")}
    </Button>
  ) : (
    <p className="text-muted-foreground text-xs">{t("layouts:holdsTitle")}</p>
  );
  const change = (next: LayoutNode) => edits.changePart(path, next);

  if (node.type === "stack") {
    return (
      <GroupSettings node={node} onChange={change}>
        {remove}
      </GroupSettings>
    );
  }
  if (node.type === "section") {
    return (
      <SectionSettings node={node} onChange={change}>
        {remove}
      </SectionSettings>
    );
  }
  const help =
    node.type === "plugin"
      ? "layouts:pluginPartHelp"
      : !canRemove
        ? on
          ? on.words.titleHelp
          : "layouts:titleHelp"
        : on?.spec.editsAField(node)
          ? on.words.hiddenHelp
          : on
            ? `${on.words.parts}partHelp.${node.type}`
            : node.type === "properties"
              ? "layouts:propertiesHelp"
              : "layouts:fieldHelp";
  return (
    <Panel heading={t("layouts:settings")}>
      <p className="text-muted-foreground text-sm">{t(help)}</p>
      {canRemove ? remove : null}
    </Panel>
  );
};

const Panel = ({ heading, children }: { heading: string; children: ReactNode }) => (
  <section className="space-y-4 p-4">
    <h2 className="font-medium text-sm">{heading}</h2>
    {children}
  </section>
);

/** A group's arrangement, as plain choices. Each sets one prop, and the
 *  group's default is the prop left out. */
const GroupSettings = ({
  node,
  onChange,
  children,
}: {
  node: LayoutNode;
  onChange: (next: LayoutNode) => void;
  children: ReactNode;
}) => {
  const { t } = useTranslation(["layouts"]);
  const props = node.props ?? {};
  const set = (key: string, value: unknown) => {
    const { [key]: _left, ...rest } = props;
    onChange({ ...node, props: value === undefined ? rest : { ...rest, [key]: value } });
  };
  const flag = (key: string, on: unknown, label: string) => (
    <div className="flex items-center justify-between gap-2">
      <Label htmlFor={`group-${key}`}>{label}</Label>
      <Switch
        id={`group-${key}`}
        checked={props[key] === on}
        onCheckedChange={(checked) => set(key, checked ? on : undefined)}
      />
    </div>
  );
  return (
    <Panel heading={t("layouts:group")}>
      <Field label={t("layouts:arrange")}>
        <Select
          value={props.direction === "row" ? "row" : "column"}
          onValueChange={(direction) => set("direction", direction === "row" ? "row" : undefined)}
        >
          <SelectTrigger>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="column">{t("layouts:stacked")}</SelectItem>
            <SelectItem value="row">{t("layouts:sideBySide")}</SelectItem>
          </SelectContent>
        </Select>
      </Field>
      <Field label={t("layouts:spacing")}>
        <Select
          value={props.gap === "sm" ? "sm" : "xs"}
          onValueChange={(gap) => set("gap", gap === "sm" ? "sm" : undefined)}
        >
          <SelectTrigger>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="xs">{t("layouts:tight")}</SelectItem>
            <SelectItem value="sm">{t("layouts:roomy")}</SelectItem>
          </SelectContent>
        </Select>
      </Field>
      {props.direction === "row" ? flag("wrap", true, t("layouts:wrap")) : null}
      {flag("align", "start", t("layouts:ownWidth"))}
      {flag("tone", "muted", t("layouts:muted"))}
      {children}
    </Panel>
  );
};

/** A section's title, and whether it starts folded, which only a titled
 *  section can: its title is what unfolds it. */
const SectionSettings = ({
  node,
  onChange,
  children,
}: {
  node: LayoutNode;
  onChange: (next: LayoutNode) => void;
  children: ReactNode;
}) => {
  const { t } = useTranslation(["layouts"]);
  const props = node.props ?? {};
  const title = typeof props.title === "string" ? props.title : "";
  const set = (key: string, value: unknown) => {
    const { [key]: _left, ...rest } = props;
    onChange({ ...node, props: value === undefined ? rest : { ...rest, [key]: value } });
  };
  return (
    // Titled, it is an accordion that opens and closes; untitled, a box.
    <Panel heading={t(title ? "layouts:blocks.accordion" : "layouts:blocks.box")}>
      <p className="text-muted-foreground text-sm">{t("layouts:sectionHelp")}</p>
      <Field label={t("layouts:sectionTitle")}>
        <CommittedInput
          value={title}
          // An accordion just added is named by typing over its title.
          selectOn={title === t("layouts:blocks.accordion") ? node : undefined}
          optional
          onCommit={(next) => {
            const { title: _title, collapsed: _collapsed, ...rest } = props;
            onChange({
              ...node,
              props: next
                ? { ...rest, title: next, ...(props.collapsed ? { collapsed: true } : {}) }
                : rest,
            });
          }}
        />
      </Field>
      <div className="flex items-center justify-between gap-2">
        <Label htmlFor="section-collapsed">{t("layouts:startFolded")}</Label>
        <Switch
          id="section-collapsed"
          checked={props.collapsed === true}
          disabled={!title}
          onCheckedChange={(checked) => set("collapsed", checked ? true : undefined)}
        />
      </div>
      {children}
    </Panel>
  );
};

/** Text kept as typed and given to `onCommit` when the field is left or Enter
 *  is pressed, so one change of it is one change to undo. Left empty, it
 *  puts back what it had, unless it is `optional`. */
export const CommittedInput = ({
  id,
  value,
  optional = false,
  numeric = false,
  normalize,
  selectOn,
  onCommit,
}: {
  id?: string;
  value: string;
  optional?: boolean;
  /** It takes a whole number. */
  numeric?: boolean;
  /** What is typed, as it is kept, or null where it can't be, which puts
   *  back what it had. */
  normalize?: (text: string) => string | null;
  /** Focused with its text selected whenever this changes, while set: the
   *  part it names, so a part newly selected is named by typing. */
  selectOn?: unknown;
  onCommit: (value: string) => void;
}) => {
  const [text, setText] = useState(value);
  useEffect(() => setText(value), [value]);
  const input = useRef<HTMLInputElement>(null);
  const selected = useRef<unknown>(undefined);
  // Once the box shows what it names: a box kept for another part still
  // holds the last one's text for a render.
  useEffect(() => {
    if (selectOn === undefined || selected.current === selectOn || text !== value) return;
    selected.current = selectOn;
    input.current?.focus();
    input.current?.select();
  }, [selectOn, text, value]);

  const commit = () => {
    const kept = normalize ? normalize(text.trim()) : text.trim();
    if (kept === null || kept === value || (!kept && !optional)) setText(value);
    else onCommit(kept);
  };
  return (
    <Input
      id={id}
      value={text}
      ref={input}
      maxLength={MAX_TITLE_LENGTH}
      {...(numeric ? { type: "number", min: 1, inputMode: "numeric" as const } : {})}
      onChange={(event) => setText(event.target.value)}
      onBlur={commit}
      onKeyDown={(event) => {
        if (event.key === "Enter") commit();
      }}
    />
  );
};
