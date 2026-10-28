import { Minus, Plus } from "lucide-react";
import type { ComponentType, ReactNode, RefObject } from "react";
import { useTranslation } from "react-i18next";

import {
  type CounterRead,
  type CounterUpdate,
  CounterViewMode,
  SearchEntityType,
  Tool,
} from "@/api/generated/initiativeAPI.schemas";
import { CounterView } from "@/components/initiativeTools/counters/views/CounterView";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { counterSaves, type SteppedCount, useCounterGroup, useSetCount } from "@/hooks/useCounters";
import { type ItemFieldSave, useItemFieldSave } from "@/hooks/useFieldSave";
import { isAtMax, isAtMin } from "@/lib/counter-math";

import { type COUNTER_FIELDS, COUNTER_LAYOUT, counterFields } from "./counters";
import { type DetailKind, useItemContext } from "./DetailLayoutView";
import { FieldFrame, ReadField, useFieldDraft } from "./editing";
import { ColorField, TitleField } from "./fieldEditors";

/** What a counter's detail shares with its parts, beside the counter itself. */
export interface CounterLayoutContext {
  /** The server says the reader cannot change the counter. */
  readOnly: boolean;
  groupId: number;
  /** The group's initiative; a community's own group has none, and so no
   *  properties or links. */
  initiativeId: number | null;
  /** Set when the detail is left on purpose. */
  leaving: RefObject<boolean>;
  /** The menu of what else can be done with it. */
  actions: ReactNode;
  /** The page's stepper, which every step of the group's counters goes
   *  through; none in the layout editor, where nothing is changed. */
  stepper?: SteppedCount;
}

const useCounterLayout = useItemContext<CounterLayoutContext>;

type EditorProps = { item: CounterRead; label: string };
type Save = ItemFieldSave<CounterRead, CounterUpdate>;

/** A field's save, for the group the counter is in. */
const useSave = (counter: CounterRead, label: string): Save =>
  useItemFieldSave(counterSaves(useCounterLayout().groupId), counter.id, label);

const NameEditor = ({ item: counter, label }: EditorProps) => {
  const { t } = useTranslation("counterGroups");
  return (
    <TitleField
      id="counter-name"
      field="name"
      label={label}
      value={counter.name}
      save={useSave(counter, label)}
      readOnly={useCounterLayout().readOnly}
      placeholder={t("counterNamePlaceholder")}
      subscribe={{ kind: "counter", id: counter.id }}
    />
  );
};

const ColorEditor = ({ item, label }: EditorProps) => (
  <ColorField
    label={label}
    value={item.color}
    save={useSave(item, label)}
    readOnly={useCounterLayout().readOnly}
  />
);

/** Which of the counter's numbers a field edits, and whether it may be empty. */
const NUMBERS = {
  min: { key: "min", optional: true },
  max: { key: "max", optional: true },
  step: { key: "step", optional: false },
  start: { key: "initial_count", optional: false },
} as const;

/** One of the numbers it counts by: a bound, its step or where it starts. A
 *  bound left empty is no bound. */
const NumberEditor = ({
  item: counter,
  label,
  number,
}: EditorProps & { number: keyof typeof NUMBERS }) => {
  const { readOnly } = useCounterLayout();
  const save = useSave(counter, label);
  const { key, optional } = NUMBERS[number];
  const saved = counter[key] ?? "";
  const draft = useFieldDraft(
    saved,
    (text) => {
      const value = text.trim() === "" ? null : text.trim();
      return save.save({ patch: { [key]: value }, shows: { [key]: value } });
    },
    Object.is,
    (text) => (text.trim() === "" ? optional : Number.isFinite(Number(text)) && text.trim() !== "")
  );
  const id = `counter-${number}`;
  if (readOnly) {
    return saved ? (
      <ReadField label={label}>
        <p className="text-sm tabular-nums">{saved}</p>
      </ReadField>
    ) : null;
  }
  return (
    <FieldFrame label={label} htmlFor={id} save={save} changed={draft.changed} keys={draft.keys}>
      <Input
        id={id}
        type="number"
        inputMode="decimal"
        value={draft.value}
        onChange={(change) => draft.change(change.target.value)}
      />
    </FieldFrame>
  );
};

/** How it is drawn: a number, a bar or a clock. A bar and a clock need both
 *  bounds. */
const ViewEditor = ({ item: counter, label }: EditorProps) => {
  const { t } = useTranslation("counterGroups");
  const { readOnly } = useCounterLayout();
  const save = useSave(counter, label);
  const bounded = counter.min != null && counter.max != null;
  const names: Record<CounterViewMode, string> = {
    [CounterViewMode.number]: t("viewModeNumber"),
    [CounterViewMode.progress_bar]: t("viewModeProgressBar"),
    [CounterViewMode.segmented_clock]: t("viewModeSegmentedClock"),
  };
  if (readOnly) {
    return (
      <ReadField label={label}>
        <p className="text-sm">{names[counter.view_mode]}</p>
      </ReadField>
    );
  }
  return (
    <FieldFrame label={label} htmlFor="counter-view-mode" save={save}>
      <Select
        value={counter.view_mode}
        onValueChange={(mode) =>
          void save.save({
            patch: { view_mode: mode as CounterViewMode },
            shows: { view_mode: mode as CounterViewMode },
          })
        }
      >
        <SelectTrigger id="counter-view-mode">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {Object.values(CounterViewMode).map((mode) => (
            <SelectItem
              key={mode}
              value={mode}
              disabled={mode !== CounterViewMode.number && !bounded}
            >
              {names[mode]}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      {bounded ? null : (
        <p className="text-muted-foreground text-xs">{t("viewModeRequiresBounds")}</p>
      )}
    </FieldFrame>
  );
};

/** Its count, stepped or set as on its group's page. Read from the group,
 *  where a step shows at once. */
const Count = ({ counter }: { counter: CounterRead }) => {
  const { t } = useTranslation("counterGroups");
  const { groupId, readOnly, stepper } = useCounterLayout();
  const live =
    useCounterGroup(groupId).data?.counters.find((each) => each.id === counter.id) ?? counter;
  const setCount = useSetCount(groupId);
  const locked = readOnly || !stepper;
  return (
    <div className="flex items-center justify-center gap-4 rounded-lg border bg-card p-4">
      <Button
        type="button"
        variant="outline"
        size="icon"
        onClick={() => stepper?.decrement(live)}
        disabled={locked || isAtMin(live)}
        aria-label={t("decrement")}
      >
        <Minus className="h-4 w-4" />
      </Button>
      <CounterView
        counter={live}
        disabled={locked}
        textColor="currentColor"
        onCommit={(value) => {
          stepper?.cancel(live.id);
          setCount.mutate({ counterId: live.id, data: { count: value } });
        }}
        size="lg"
      />
      <Button
        type="button"
        variant="outline"
        size="icon"
        onClick={() => stepper?.increment(live)}
        disabled={locked || isAtMax(live)}
        aria-label={t("increment")}
      >
        <Plus className="h-4 w-4" />
      </Button>
    </div>
  );
};

/** A counter's detail: its fields, its count and where it lives. */
export const COUNTER_DETAIL: DetailKind<CounterRead, CounterLayoutContext, CounterUpdate> = {
  spec: COUNTER_LAYOUT,
  fields: counterFields,
  namespaces: ["counterGroups", "common"],
  editors: {
    name: NameEditor,
    color: ColorEditor,
    min: (props) => <NumberEditor {...props} number="min" />,
    max: (props) => <NumberEditor {...props} number="max" />,
    step: (props) => <NumberEditor {...props} number="step" />,
    start: (props) => <NumberEditor {...props} number="start" />,
    view: ViewEditor,
  } satisfies Record<keyof typeof COUNTER_FIELDS, ComponentType<EditorProps>>,
  parts: { count: (_node, counter) => <Count counter={counter} /> },
  home: (counter, context) => ({
    saves: counterSaves(context.groupId),
    readOnly: context.readOnly,
    initiativeId: context.initiativeId,
    canOpen: { tool: Tool.counter_group, id: context.groupId },
    links: {
      entity: { id: context.groupId, initiative_id: context.initiativeId },
      target: { type: SearchEntityType.counter, id: counter.id },
      title: counter.name,
    },
    actions: context.actions,
  }),
};

/** A counter not yet added, in `color`, as its detail draws it while it is. */
export const blankCounter = (groupId: number, color: string): CounterRead => ({
  id: 0,
  counter_group_id: groupId,
  community_id: 0,
  name: "",
  color,
  count: "0",
  min: null,
  max: null,
  step: "1",
  initial_count: "0",
  view_mode: CounterViewMode.number,
  position: "0",
  properties: [],
  created_at: "",
  updated_at: "",
});

/** Whether a counter can be added as it stands: named, stepping up by more
 *  than nothing, and bounded where it is drawn as a bar or a clock. */
export const counterReady = (counter: CounterRead) =>
  counter.name.trim() !== "" &&
  Number(counter.step) > 0 &&
  (counter.view_mode === CounterViewMode.number || (counter.min != null && counter.max != null));
