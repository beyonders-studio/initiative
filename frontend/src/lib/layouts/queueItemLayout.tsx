import type { ComponentType, ReactNode, RefObject } from "react";
import { useTranslation } from "react-i18next";

import {
  type QueueItemRead,
  type QueueItemUpdate,
  SearchEntityType,
  Tool,
} from "@/api/generated/initiativeAPI.schemas";
import { MemberSelect } from "@/components/members/MemberSearchSelect";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { type ItemFieldSave, useItemFieldSave } from "@/hooks/useFieldSave";
import { queueItemSaves } from "@/hooks/useQueues";
import { referenceRef } from "@/lib/smartChips";

import { type DetailKind, useItemContext } from "./DetailLayoutView";
import { FieldFrame, ReadField, useFieldDraft } from "./editing";
import { ColorField, DescriptionField, TagsField, TitleField } from "./fieldEditors";
import { type QUEUE_ITEM_FIELDS, QUEUE_ITEM_LAYOUT, queueItemFields } from "./queueItems";

/** What a queue item's detail shares with its parts, beside the item itself. */
export interface QueueItemLayoutContext {
  /** The server says the reader cannot change the item. */
  readOnly: boolean;
  queueId: number;
  initiativeId: number;
  /** Set when the detail is left on purpose, so an open draft does not hold it. */
  leaving: RefObject<boolean>;
  /** Reporting it, and the menu of what else can be done with it. */
  actions: ReactNode;
  /** Drawn in the layout editor, where nothing is changed. */
  preview?: boolean;
}

const useQueueItemLayout = useItemContext<QueueItemLayoutContext>;

type EditorProps = { item: QueueItemRead; label: string };
type Save = ItemFieldSave<QueueItemRead, QueueItemUpdate>;

/** A field's save, for the queue the item is in. */
const useSave = (item: QueueItemRead, label: string): Save =>
  useItemFieldSave(queueItemSaves(useQueueItemLayout().queueId), item.id, label);

const LabelEditor = ({ item, label }: EditorProps) => {
  const { t } = useTranslation("queues");
  return (
    <TitleField
      id="queue-item-label"
      field="label"
      label={label}
      value={item.label}
      save={useSave(item, label)}
      readOnly={useQueueItemLayout().readOnly}
      placeholder={t("labelPlaceholder")}
      subscribe={{ kind: "queue_item", id: item.id }}
    />
  );
};

/** Its notes, written and saved as a task's description is. */
const NotesEditor = ({ item, label }: EditorProps) => {
  const { t } = useTranslation("queues");
  const context = useQueueItemLayout();
  return (
    <DescriptionField
      field="notes"
      kind={queueItemSaves(context.queueId)}
      id={item.id}
      options={{}}
      label={label}
      htmlId="queue-item-notes"
      value={item.notes ?? null}
      readOnly={context.readOnly}
      initiativeId={context.initiativeId}
      subject={referenceRef(SearchEntityType.queue_item, item.id)}
      leaving={context.leaving}
      preview={context.preview}
      placeholder={t("notesPlaceholder")}
    />
  );
};

/** Where it stands in the queue: a higher number goes first. */
const PositionEditor = ({ item, label }: EditorProps) => {
  const { t } = useTranslation("queues");
  const { readOnly } = useQueueItemLayout();
  const save = useSave(item, label);
  const draft = useFieldDraft(
    String(item.position),
    (text) => save.save({ patch: { position: Number(text) }, shows: { position: Number(text) } }),
    Object.is,
    (text) => text.trim() !== "" && Number.isFinite(Number(text))
  );
  if (readOnly) {
    return (
      <ReadField label={label}>
        <p className="text-sm">{item.position}</p>
      </ReadField>
    );
  }
  return (
    <FieldFrame
      label={label}
      htmlFor="queue-item-position"
      save={save}
      changed={draft.changed}
      keys={draft.keys}
    >
      <Input
        id="queue-item-position"
        type="number"
        value={draft.value}
        onChange={(change) => draft.change(change.target.value)}
      />
      <p className="text-muted-foreground text-xs">{t("positionHelp")}</p>
    </FieldFrame>
  );
};

const ColorEditor = ({ item, label }: EditorProps) => (
  <ColorField
    label={label}
    value={item.color}
    save={useSave(item, label)}
    readOnly={useQueueItemLayout().readOnly}
  />
);

/** Whether the queue shows it in its turns. */
const VisibleEditor = ({ item, label }: EditorProps) => {
  const { t } = useTranslation("queues");
  const { readOnly } = useQueueItemLayout();
  const save = useSave(item, label);
  if (readOnly) {
    return (
      <ReadField label={label}>
        <p className="text-sm">{item.is_visible ? t("visible") : t("hidden")}</p>
      </ReadField>
    );
  }
  return (
    <FieldFrame label={label} save={save}>
      <div className="flex items-center gap-3">
        <Switch
          checked={item.is_visible}
          onCheckedChange={(shown) =>
            void save.save({ patch: { is_visible: shown }, shows: { is_visible: shown } })
          }
          aria-label={label}
        />
        <span className="text-muted-foreground text-sm">
          {item.is_visible ? t("visible") : t("hidden")}
        </span>
      </div>
    </FieldFrame>
  );
};

/** The member whose turn it is, saved as they are picked. */
const PersonEditor = ({ item, label }: EditorProps) => {
  const { t } = useTranslation("queues");
  const { readOnly, queueId } = useQueueItemLayout();
  const save = useSave(item, label);
  if (readOnly) {
    return item.user ? (
      <ReadField label={label}>
        <p className="text-sm">{item.user.display_name}</p>
      </ReadField>
    ) : null;
  }
  return (
    <FieldFrame label={label} save={save}>
      <MemberSelect
        scope={{ type: "canOpen", tool: Tool.queue, id: queueId }}
        value={item.user_id ?? null}
        onChange={(userId) =>
          void save.save(
            { patch: { user_id: userId }, shows: { user_id: userId } },
            userId === null ? { patch: { user_id: item.user_id }, shows: item } : undefined
          )
        }
        selectedUser={item.user}
        placeholder={t("selectUser")}
        emptyMessage={t("noUser")}
        aria-label={label}
      />
    </FieldFrame>
  );
};

const TagsEditor = ({ item, label }: EditorProps) => {
  const { t } = useTranslation("queues");
  return (
    <TagsField
      label={label}
      tags={item.tags}
      save={useSave(item, label)}
      readOnly={useQueueItemLayout().readOnly}
      placeholder={t("tags")}
    />
  );
};

/** A queue item's detail: its fields and where it lives. */
export const QUEUE_ITEM_DETAIL: DetailKind<QueueItemRead, QueueItemLayoutContext, QueueItemUpdate> =
  {
    spec: QUEUE_ITEM_LAYOUT,
    fields: queueItemFields,
    namespaces: ["queues", "common"],
    editors: {
      label: LabelEditor,
      notes: NotesEditor,
      position: PositionEditor,
      color: ColorEditor,
      visible: VisibleEditor,
      person: PersonEditor,
      tags: TagsEditor,
    } satisfies Record<keyof typeof QUEUE_ITEM_FIELDS, ComponentType<EditorProps>>,
    home: (item, context) => ({
      saves: queueItemSaves(context.queueId),
      readOnly: context.readOnly,
      initiativeId: context.initiativeId,
      canOpen: { tool: Tool.queue, id: context.queueId },
      links: {
        entity: { id: context.queueId, initiative_id: context.initiativeId },
        target: { type: SearchEntityType.queue_item, id: item.id },
        title: item.label,
      },
      actions: context.actions,
    }),
  };

/** A queue item not yet added, as its detail draws it while it is. */
export const blankQueueItem = (queueId: number): QueueItemRead => ({
  id: 0,
  queue_id: queueId,
  label: "",
  position: 0,
  notes: null,
  user_id: null,
  user: null,
  tags: [],
  properties: [],
  attachment_count: 0,
  held_at_round: null,
  created_by: null,
  created_at: "",
  color: "#6366F1",
  is_visible: true,
});
