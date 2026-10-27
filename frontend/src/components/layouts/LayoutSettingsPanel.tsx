import { EyeClosed } from "lucide-react";
import { type ReactNode, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  PropertyType,
  type TaskStatusRead,
  type TaskTypeRead,
} from "@/api/generated/initiativeAPI.schemas";
import { listLayoutLooks } from "@/components/projects/projectTasksConfig";
import type { RatingDisplay } from "@/components/properties/propertyHelpers";
import { TaskStatusOption } from "@/components/tasks/TaskStatusOption";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { MAX_COLUMN_LIMIT } from "@/hooks/useColumnLimits";
import { LAYOUT_REGIONS } from "@/lib/layouts/detailLayout";
import {
  cardOf,
  type ListLayout,
  MAX_TITLE_LENGTH,
  type NodePath,
  nodeAt,
  removable,
  type Selection,
} from "@/lib/layouts/draft";
import { type FieldDef, LAYOUT_NAMESPACES } from "@/lib/layouts/fields";
import type { LayoutNode } from "@/lib/layouts/tree";
import type { TranslateFn } from "@/types/i18n";

import type { EditableDetail } from "./details";
import type { LayoutEdits } from "./LayoutEditor";
import { LayoutGroupings } from "./LayoutGroupings";
import { type EditablePresets, LayoutPresets } from "./LayoutPresets";

/**
 * The settings of the one thing selected, and only those: the list layout's
 * own (whether the project opens on it, and putting it back as shipped) on the
 * layout, a group's arrangement on a group, and a way to take a part off the
 * card or a column out of the table, where it may go.
 */
export const ListLayoutSettings = ({
  layout,
  presets,
  help,
  opensFirst,
  shown,
  stored,
  fields,
  statuses,
  selection,
  edits,
  locked,
}: {
  layout: ListLayout;
  /** The presets it offers, and the groupings with them; a list of files
   *  offers neither. */
  presets?: EditablePresets;
  /** The project's statuses, whose board columns can be limited. */
  statuses?: TaskStatusRead[];
  /** What the list is, as a key in `projects`. */
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
}) => {
  const { t } = useTranslation(LAYOUT_NAMESPACES);
  const translate = t as TranslateFn;
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
  const rating =
    selectedField !== null && fields.get(selectedField)?.property?.type === PropertyType.rating
      ? selectedField
      : null;
  return (
    // Disabled as one, so a save under way leaves every control as it was.
    <fieldset disabled={locked} className="min-w-0">
      {selection.kind === "layout" ? (
        <Panel heading={translate(listLayoutLooks[layout.kind].labelKey)}>
          <p className="text-muted-foreground text-sm">{translate(help)}</p>
          {shown ? (
            <div className="flex items-center justify-between gap-2">
              <Label htmlFor="layout-shown">{translate("layouts:shownInMenu")}</Label>
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
              <Label htmlFor="layout-default">{translate("layouts:opensFirst")}</Label>
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
            <>
              <LayoutPresets layout={layout} of={presets} fields={fields} edits={edits} />
              {layout.kind !== "calendar" ? (
                <LayoutGroupings layout={layout} fields={fields} edits={edits} />
              ) : null}
            </>
          ) : null}
          {layout.kind === "board" && statuses ? (
            <ColumnLimits layout={layout} statuses={statuses} edits={edits} />
          ) : null}
          <Shipped stored={stored} edits={edits} />
        </Panel>
      ) : selection.kind === "column" ? (
        <ColumnSettings field={selection.field} fields={fields} edits={edits} />
      ) : (
        <PartSettings
          tree={cardOf(layout.definition, fields, layout.shape)}
          path={selection.path}
          fields={fields}
          edits={edits}
        />
      )}
      {rating !== null ? (
        <RatingDisplaySetting
          value={layout.definition.displays?.[rating] ?? "number"}
          onChange={(display) => edits.changeDisplay(rating, display)}
        />
      ) : null}
    </fieldset>
  );
};

const RATING_DISPLAYS: RatingDisplay[] = ["number", "stars", "bar"];

/** How the list draws the rating selected: a number, five stars, or a bar. */
const RatingDisplaySetting = ({
  value,
  onChange,
}: {
  value: RatingDisplay;
  onChange: (display: RatingDisplay) => void;
}) => {
  const { t } = useTranslation(["layouts"]);
  return (
    <div className="space-y-2 px-4 pb-4">
      <Label htmlFor="rating-display">{t("layouts:ratingDisplay.label")}</Label>
      <Select value={value} onValueChange={(next) => onChange(next as RatingDisplay)}>
        <SelectTrigger id="rating-display">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {RATING_DISPLAYS.map((display) => (
            <SelectItem key={display} value={display}>
              {t(`layouts:ratingDisplay.${display}`)}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
};

/** A limit as typed, as the layout keeps it: a whole number the server takes,
 *  or nothing for no limit; null for anything else, which puts back the
 *  stored one. */
const limitText = (text: string): string | null => {
  if (text === "") return "";
  const limit = Number(text);
  return Number.isInteger(limit) && limit >= 1 && limit <= MAX_COLUMN_LIMIT ? String(limit) : null;
};

/** How many open tasks each of a board's columns takes from a person; one
 *  left empty takes any number. Saved with the layout. */
const ColumnLimits = ({
  layout,
  statuses,
  edits,
}: {
  layout: ListLayout;
  statuses: TaskStatusRead[];
  edits: LayoutEdits;
}) => {
  const { t } = useTranslation(LAYOUT_NAMESPACES);
  const translate = t as TranslateFn;
  const limits = new Map(
    (layout.definition.limits ?? []).map((each) => [each.status_id, each.limit])
  );
  const change = (statusId: number, text: string) => {
    const next = new Map(limits);
    if (text === "") next.delete(statusId);
    else next.set(statusId, Number(text));
    edits.changeLimits(
      statuses.flatMap((status) => {
        const kept = next.get(status.id);
        return kept === undefined ? [] : [{ status_id: status.id, limit: kept }];
      })
    );
  };
  return (
    <div className="space-y-3">
      <div className="space-y-1">
        <h3 className="font-medium text-sm">{translate("layouts:limits.heading")}</h3>
        <p className="text-muted-foreground text-xs">{translate("layouts:limits.help")}</p>
      </div>
      <ul className="space-y-2">
        {statuses.map((status) => (
          <li key={status.id} className="flex items-center gap-2">
            <Label htmlFor={`column-limit-${status.id}`} className="min-w-0 flex-1">
              <TaskStatusOption status={status} />
            </Label>
            <div className="w-20">
              <CommittedInput
                id={`column-limit-${status.id}`}
                value={String(limits.get(status.id) ?? "")}
                optional
                numeric
                normalize={limitText}
                onCommit={(text) => change(status.id, text)}
              />
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
};

/** Putting the open layout back as shipped, or saying it already is. */
const Shipped = ({
  stored,
  edits,
  shipped = "layouts:shipped",
}: {
  stored: boolean;
  edits: LayoutEdits;
  /** What says the layout is as shipped. */
  shipped?: string;
}) => {
  const { t } = useTranslation(LAYOUT_NAMESPACES);
  const translate = t as TranslateFn;
  return stored ? (
    <Button type="button" variant="outline" size="sm" onClick={edits.resetLayout}>
      {translate("layouts:useShipped")}
    </Button>
  ) : (
    <p className="text-muted-foreground text-xs">{translate(shipped)}</p>
  );
};

/** The project whose layouts are open: whose statuses its preview draws. */
export type LayoutProject = {
  id: number;
  initiativeId: number;
  statuses: TaskStatusRead[];
  /** Its task types, each with a page of its own. */
  types: TaskTypeRead[];
};

/** The settings of what is selected on a task's detail: the layout's own, or
 *  a part's. */
export const DetailLayoutSettings = ({
  detail,
  of,
  stored,
  fields,
  selection,
  edits,
  locked,
}: {
  /** The detail as one tree: the layout, holding its header, main and side. */
  detail: LayoutNode;
  of: EditableDetail;
  /** Whether the target lays out its own detail, as against the shipped one. */
  stored: boolean;
  fields: ReadonlyMap<string, FieldDef>;
  selection: Selection;
  edits: LayoutEdits;
  locked: boolean;
}) => {
  const { t } = useTranslation(LAYOUT_NAMESPACES);
  const translate = t as TranslateFn;
  return (
    <fieldset disabled={locked} className="min-w-0">
      {selection.kind === "part" ? (
        <PartSettings tree={detail} path={selection.path} fields={fields} edits={edits} on={of} />
      ) : (
        <Panel heading={translate(of.words.name)}>
          <p className="text-muted-foreground text-sm">{translate(of.words.help)}</p>
          <Shipped stored={stored} edits={edits} shipped={of.words.shipped} />
        </Panel>
      )}
    </fieldset>
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
  const { t } = useTranslation(["projects", "layouts"]);
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
  tree,
  path,
  fields,
  edits,
  on,
}: {
  tree: LayoutNode;
  path: NodePath;
  fields: ReadonlyMap<string, FieldDef>;
  edits: LayoutEdits;
  /** The detail the part is on; none on a card. */
  on?: EditableDetail;
}) => {
  const { t } = useTranslation(LAYOUT_NAMESPACES);
  const translate = t as TranslateFn;
  const node = nodeAt(tree, path);
  if (!node) return null;
  if (node.type === "card") {
    return (
      <Panel heading={translate("layouts:card")}>
        <p className="text-muted-foreground text-sm">{translate("layouts:cardHelp")}</p>
      </Panel>
    );
  }
  if ((LAYOUT_REGIONS as readonly string[]).includes(node.type)) {
    return (
      <Panel heading={translate(`layouts:parts.${node.type}`)}>
        <p className="text-muted-foreground text-sm">
          {translate(`layouts:regionHelp.${node.type}`)}
        </p>
      </Panel>
    );
  }
  const canRemove = removable(node, fields);
  const remove = canRemove ? (
    <Button type="button" variant="outline" size="sm" onClick={() => edits.removePart(path)}>
      <EyeClosed className="h-4 w-4" aria-hidden="true" />
      {translate("layouts:hidePart")}
    </Button>
  ) : (
    <p className="text-muted-foreground text-xs">{translate("layouts:holdsTitle")}</p>
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
    <Panel heading={translate("layouts:settings")}>
      <p className="text-muted-foreground text-sm">{translate(help)}</p>
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
  const { t } = useTranslation(["projects", "layouts"]);
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
      <div className="space-y-2">
        <Label htmlFor="group-direction">{t("layouts:arrange")}</Label>
        <Select
          value={props.direction === "row" ? "row" : "column"}
          onValueChange={(direction) => set("direction", direction === "row" ? "row" : undefined)}
        >
          <SelectTrigger id="group-direction">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="column">{t("layouts:stacked")}</SelectItem>
            <SelectItem value="row">{t("layouts:sideBySide")}</SelectItem>
          </SelectContent>
        </Select>
      </div>
      <div className="space-y-2">
        <Label htmlFor="group-gap">{t("layouts:spacing")}</Label>
        <Select
          value={props.gap === "sm" ? "sm" : "xs"}
          onValueChange={(gap) => set("gap", gap === "sm" ? "sm" : undefined)}
        >
          <SelectTrigger id="group-gap">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="xs">{t("layouts:tight")}</SelectItem>
            <SelectItem value="sm">{t("layouts:roomy")}</SelectItem>
          </SelectContent>
        </Select>
      </div>
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
  const { t } = useTranslation(["projects", "layouts"]);
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
      <div className="space-y-2">
        <Label htmlFor="section-title">{t("layouts:sectionTitle")}</Label>
        <CommittedInput
          id="section-title"
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
      </div>
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
const CommittedInput = ({
  id,
  value,
  optional = false,
  numeric = false,
  normalize,
  selectOn,
  onCommit,
}: {
  id: string;
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
