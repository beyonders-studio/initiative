import {
  closestCenter,
  DndContext,
  type DragEndEvent,
  PointerSensor,
  useSensor,
  useSensors,
} from "@dnd-kit/core";
import {
  arrayMove,
  SortableContext,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { useNavigate } from "@tanstack/react-router";
import {
  ChevronDown,
  ChevronUp,
  GripVertical,
  ListTree,
  Loader2,
  Sparkles,
  SquareCheck,
  Trash2,
} from "lucide-react";
import {
  type ClipboardEvent,
  type KeyboardEvent,
  type RefObject,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useTranslation } from "react-i18next";

import type { ChecklistItem, ChecklistProgress } from "@/api/generated/initiativeAPI.schemas";
import { TaskChecklistProgress } from "@/components/tasks/TaskChecklistProgress";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { useAIEnabled } from "@/hooks/useAIEnabled";
import {
  useGenerateChecklist,
  usePromoteChecklistItem,
  useToggleChecklistItem,
  useUpdateTask,
} from "@/hooks/useTasks";
import { newChecklistItemId } from "@/lib/checklist";
import { useCommunityPath } from "@/lib/communityUrl";
import { toast } from "@/lib/mascotToast";
import { entityRefRoute } from "@/lib/tools";

/** A checklist as the server holds it, in one comparable string. */
const fingerprint = (items: ChecklistItem[]) =>
  JSON.stringify(items.map((item) => [item.id, item.text, item.done]));

/** A {@link fingerprint} with one item taken out. */
const withoutItem = (stamp: string, id: string) =>
  JSON.stringify(
    (JSON.parse(stamp) as [string, string, boolean][]).filter(([held]) => held !== id)
  );

/** The list as it would be saved: a line still being written is not one yet. */
const payloadOf = (items: ChecklistItem[]) =>
  items
    .filter((item) => item.text.trim())
    .map((item) => ({ id: item.id, text: item.text.trim(), done: item.done }));

const blankItem = (): ChecklistItem => ({ id: newChecklistItemId(), text: "", done: false });

type TaskChecklistProps = {
  taskId: number;
  /** ``task.checklist`` — the whole list, in order. */
  items: ChecklistItem[];
  canEdit: boolean;
  /** For a task being added, which nothing has saved yet: each change of the
   *  list goes here, whole, rather than to the server. Its lines cannot yet
   *  become tasks or be written for it. */
  onDraftChange?: (items: ChecklistItem[]) => void;
};

export const TaskChecklist = ({
  taskId,
  items: serverItems,
  canEdit,
  onDraftChange,
}: TaskChecklistProps) => {
  const { t } = useTranslation(["tasks", "common"]);
  const addInputRef = useRef<HTMLInputElement | null>(null);
  const [newText, setNewText] = useState("");
  const { isEnabled: aiEnabled } = useAIEnabled();
  const [aiDialogOpen, setAiDialogOpen] = useState(false);
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [fromComments, setFromComments] = useState<{ read: number; count: number } | null>(null);
  const [selected, setSelected] = useState<Set<number>>(new Set());

  const [items, setItems] = useState<ChecklistItem[]>(serverItems);
  const itemsRef = useRef(items);
  itemsRef.current = items;
  // What the server was last told. An edit that has not reached it yet is what
  // keeps an incoming refetch from overwriting what somebody is typing.
  const sent = useRef(fingerprint(serverItems));
  // The item to put the cursor in once it has rendered.
  const [focusId, setFocusId] = useState<string | null>(null);

  const updateTask = useUpdateTask(undefined, "tasks:checklist.updateError");
  const toggleItem = useToggleChecklistItem();
  const promoteItem = usePromoteChecklistItem();
  const navigate = useNavigate();
  const gp = useCommunityPath();
  // A line can become a task once the server holds it as it reads here.
  const saved = useMemo(
    () => new Map(serverItems.map((item) => [item.id, item.text])),
    [serverItems]
  );

  useEffect(() => {
    const local = itemsRef.current;
    const unsent =
      fingerprint(payloadOf(local)) !== sent.current || local.some((item) => !item.text.trim());
    if (unsent) {
      return;
    }
    setItems(serverItems);
    sent.current = fingerprint(serverItems);
  }, [serverItems]);

  const progress: ChecklistProgress | null = useMemo(() => {
    const saved = payloadOf(items);
    return saved.length
      ? { completed: saved.filter((item) => item.done).length, total: saved.length }
      : null;
  }, [items]);

  /** Apply a local edit and send the whole list, unless it already says what
   *  the server holds. */
  const save = useCallback(
    (next: ChecklistItem[]) => {
      setItems(next);
      const payload = payloadOf(next);
      const stamp = fingerprint(payload);
      if (stamp === sent.current) {
        return;
      }
      sent.current = stamp;
      if (onDraftChange) onDraftChange(payload);
      else updateTask.mutate({ taskId, data: { checklist: payload } });
    },
    [taskId, updateTask, onDraftChange]
  );

  const generateChecklist = useGenerateChecklist({
    onSuccess: (data) => {
      setSuggestions(data.items);
      setFromComments(
        data.comments_read < data.comments_total
          ? { read: data.comments_read, count: data.comments_total }
          : null
      );
      setSelected(new Set(data.items.map((_, index) => index)));
      setAiDialogOpen(true);
    },
  });

  const handleAddSuggestions = () => {
    const chosen = suggestions.filter((_, index) => selected.has(index));
    setAiDialogOpen(false);
    setSuggestions([]);
    setSelected(new Set());
    if (chosen.length === 0) {
      return;
    }
    save([...items, ...chosen.map((text) => ({ id: newChecklistItemId(), text, done: false }))]);
    toast.success(t("checklist.batchAdded", { count: chosen.length }));
  };

  const toggleSuggestion = (index: number) => {
    setSelected((previous) => {
      const next = new Set(previous);
      if (next.has(index)) {
        next.delete(index);
      } else {
        next.add(index);
      }
      return next;
    });
  };

  const handleAdd = () => {
    const trimmed = newText.trim();
    if (!canEdit || !trimmed) {
      return;
    }
    setNewText("");
    save([...items, { id: newChecklistItemId(), text: trimmed, done: false }]);
    addInputRef.current?.focus();
  };

  /** Pasting a block of lines makes one item per line. */
  const handleAddPaste = (event: ClipboardEvent<HTMLInputElement>) => {
    const lines = event.clipboardData
      .getData("text")
      .split("\n")
      .map((line) => line.replace(/^\s*[-*•]\s*/, "").trim())
      .filter(Boolean);
    if (!canEdit || lines.length < 2) {
      return;
    }
    event.preventDefault();
    setNewText("");
    save([...items, ...lines.map((text) => ({ id: newChecklistItemId(), text, done: false }))]);
  };

  const handleToggle = (item: ChecklistItem, done: boolean) => {
    if (!canEdit) {
      return;
    }
    if (onDraftChange) {
      save(itemsRef.current.map((entry) => (entry.id === item.id ? { ...entry, done } : entry)));
      return;
    }
    setItems((previous) =>
      previous.map((entry) => (entry.id === item.id ? { ...entry, done } : entry))
    );
    // A tick names one item, so it neither carries nor overwrites the rest of
    // the list. What comes back is the list as it now stands.
    toggleItem.mutate(
      { taskId, itemId: item.id, done },
      {
        onSuccess: (updated) => {
          setItems(updated);
          sent.current = fingerprint(updated);
        },
      }
    );
  };

  // The line becomes a task part of this one, and leaves the list here as it
  // does on the server, so the refetch that follows has nothing left to send.
  const handlePromote = (item: ChecklistItem) => {
    promoteItem.mutate(
      { taskId, itemId: item.id },
      {
        onSuccess: (made) => {
          setItems(itemsRef.current.filter((entry) => entry.id !== item.id));
          // What the server holds lost the line and nothing else: another line
          // still being written stays unsent, so the refetch keeps it.
          sent.current = withoutItem(sent.current, item.id);
          toast.success(t("checklist.promoted"), {
            action: {
              label: t("checklist.openPromoted"),
              onClick: () => void navigate({ to: gp(entityRefRoute("task", made.id)) }),
            },
          });
        },
      }
    );
  };

  const handleTextChange = (id: string, text: string) => {
    setItems((previous) => previous.map((entry) => (entry.id === id ? { ...entry, text } : entry)));
  };

  const handleTextBlur = (id: string) => {
    const current = itemsRef.current;
    const item = current.find((entry) => entry.id === id);
    if (!item) {
      return;
    }
    // An item left empty was never a line; drop it rather than saving nothing.
    save(item.text.trim() ? current : current.filter((entry) => entry.id !== id));
  };

  const handleItemKeyDown = (
    event: KeyboardEvent<HTMLInputElement | HTMLTextAreaElement>,
    index: number
  ) => {
    const current = itemsRef.current;
    if (event.key === "Enter") {
      event.preventDefault();
      if (!current[index].text.trim()) {
        return;
      }
      const fresh = blankItem();
      setItems([...current.slice(0, index + 1), fresh, ...current.slice(index + 1)]);
      setFocusId(fresh.id);
      return;
    }
    if (event.key === "Backspace" && !current[index].text && current.length > 1) {
      event.preventDefault();
      setFocusId(current[Math.max(0, index - 1)].id);
      save(current.filter((_, position) => position !== index));
    }
  };

  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 4 } }));

  const handleDragEnd = useCallback(
    (event: DragEndEvent) => {
      if (!canEdit) {
        return;
      }
      const { active, over } = event;
      if (!over || active.id === over.id) {
        return;
      }
      const current = itemsRef.current;
      const from = current.findIndex((item) => item.id === active.id);
      const to = current.findIndex((item) => item.id === over.id);
      if (from === -1 || to === -1) {
        return;
      }
      save(arrayMove(current, from, to));
    },
    [canEdit, save]
  );

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle className="flex items-center gap-2">
            <SquareCheck className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
            {t("checklist.title")}
          </CardTitle>
          {canEdit && aiEnabled && !onDraftChange ? (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => generateChecklist.mutate(taskId)}
              disabled={generateChecklist.isPending}
            >
              {generateChecklist.isPending ? (
                <Loader2 className="h-3 w-3 animate-spin" />
              ) : (
                <Sparkles className="h-3 w-3" />
              )}
              {t("checklist.aiGenerate")}
            </Button>
          ) : null}
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {items.length === 0 ? (
          <p className="text-muted-foreground text-sm">
            {t("checklist.empty")} {canEdit ? t("checklist.emptyCanEdit") : ""}
          </p>
        ) : (
          <div className="space-y-3">
            <TaskChecklistProgress progress={progress} />
            <DndContext
              sensors={sensors}
              collisionDetection={closestCenter}
              onDragEnd={handleDragEnd}
            >
              <SortableContext
                items={items.map((item) => item.id)}
                strategy={verticalListSortingStrategy}
              >
                <ul className="space-y-2">
                  {items.map((item, index) => (
                    <ChecklistItemRow
                      key={item.id}
                      item={item}
                      canEdit={canEdit}
                      shouldFocus={focusId === item.id}
                      onFocused={() => setFocusId(null)}
                      onTextChange={(value) => handleTextChange(item.id, value)}
                      onTextBlur={() => handleTextBlur(item.id)}
                      onKeyDown={(event) => handleItemKeyDown(event, index)}
                      onToggle={(value) => handleToggle(item, value)}
                      onDelete={() =>
                        save(itemsRef.current.filter((entry) => entry.id !== item.id))
                      }
                      onPromote={
                        !onDraftChange &&
                        saved.get(item.id) === item.text.trim() &&
                        !promoteItem.isPending
                          ? () => handlePromote(item)
                          : undefined
                      }
                    />
                  ))}
                </ul>
              </SortableContext>
            </DndContext>
          </div>
        )}

        <div className="flex gap-2">
          <Input
            ref={addInputRef}
            placeholder={
              canEdit ? t("checklist.addPlaceholder") : t("checklist.readOnlyPlaceholder")
            }
            value={newText}
            onChange={(event) => setNewText(event.target.value)}
            onPaste={handleAddPaste}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                handleAdd();
              }
            }}
            disabled={!canEdit}
          />
          <Button type="button" onClick={handleAdd} disabled={!canEdit}>
            {t("checklist.addButton")}
          </Button>
        </div>
      </CardContent>

      <Dialog open={aiDialogOpen} onOpenChange={setAiDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("checklist.aiDialogTitle")}</DialogTitle>
            <DialogDescription>{t("checklist.aiDialogDescription")}</DialogDescription>
          </DialogHeader>
          {fromComments ? (
            <p className="text-muted-foreground text-xs">{t("ai.fromComments", fromComments)}</p>
          ) : null}
          <div className="space-y-2 py-4">
            {suggestions.map((suggestion, index) => (
              <div key={suggestion} className="flex items-center gap-3 rounded-md border p-3">
                <Checkbox
                  id={`checklist-suggestion-${index}`}
                  checked={selected.has(index)}
                  onCheckedChange={() => toggleSuggestion(index)}
                />
                <label
                  htmlFor={`checklist-suggestion-${index}`}
                  className="flex-1 cursor-pointer text-sm"
                >
                  {suggestion}
                </label>
              </div>
            ))}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setAiDialogOpen(false)}>
              {t("common:cancel")}
            </Button>
            <Button onClick={handleAddSuggestions} disabled={selected.size === 0}>
              {t("checklist.addSelected", { count: selected.size })}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  );
};

type ChecklistItemRowProps = {
  item: ChecklistItem;
  canEdit: boolean;
  shouldFocus: boolean;
  onFocused: () => void;
  onTextChange: (value: string) => void;
  onTextBlur: () => void;
  onKeyDown: (event: KeyboardEvent<HTMLInputElement | HTMLTextAreaElement>) => void;
  onToggle: (done: boolean) => void;
  onDelete: () => void;
  /** Make the line a task of its own; left out while it cannot be one yet. */
  onPromote?: () => void;
};

const ChecklistItemRow = ({
  item,
  canEdit,
  shouldFocus,
  onFocused,
  onTextChange,
  onTextBlur,
  onKeyDown,
  onToggle,
  onDelete,
  onPromote,
}: ChecklistItemRowProps) => {
  const { t } = useTranslation("tasks");
  const inputRef = useRef<HTMLInputElement | HTMLTextAreaElement | null>(null);
  // A line too long to fit is the only one worth offering to open, so the
  // control appears from the text rather than sitting on every row.
  const [expanded, setExpanded] = useState(false);
  const [clipped, setClipped] = useState(false);
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: item.id,
    disabled: !canEdit,
  });

  useEffect(() => {
    if (shouldFocus) {
      inputRef.current?.focus();
      onFocused();
    }
  }, [shouldFocus, onFocused]);

  // Whether the text runs past the end of the field — remeasured as it is
  // typed and as the row's width changes, so the control comes and goes with
  // the thing it is about.
  useEffect(() => {
    const field = inputRef.current;
    if (!field || expanded) return;
    const measure = () => setClipped(field.scrollWidth > field.clientWidth + 1);
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(field);
    return () => observer.disconnect();
  }, [item.text, expanded]);

  // An opened line is as tall as what it holds, up to the point where it is
  // better to scroll than to push the rest of the list off the screen.
  useEffect(() => {
    const field = inputRef.current;
    if (!expanded || !field) return;
    field.style.height = "auto";
    field.style.height = `${field.scrollHeight}px`;
  }, [expanded, item.text]);

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
  };

  return (
    <li
      ref={setNodeRef}
      style={style}
      className={`flex flex-col gap-2 rounded-md border bg-muted/30 px-3 py-2 text-sm sm:flex-row sm:items-center sm:gap-3 ${
        isDragging ? "opacity-80 shadow-sm" : ""
      }`}
    >
      <div className={`flex flex-1 gap-2 ${expanded ? "items-start" : "items-center"}`}>
        {canEdit ? (
          <button
            type="button"
            className="mt-1 text-muted-foreground"
            aria-label={t("checklist.reorderItem")}
            {...attributes}
            {...listeners}
          >
            <GripVertical className="-mt-1 h-4 w-4" />
          </button>
        ) : null}
        <Checkbox
          checked={item.done}
          onCheckedChange={(value) => onToggle(Boolean(value))}
          disabled={!canEdit}
          aria-label={item.done ? t("checklist.markIncomplete") : t("checklist.markComplete")}
        />
        {expanded ? (
          <Textarea
            ref={inputRef as RefObject<HTMLTextAreaElement>}
            value={item.text}
            placeholder={t("checklist.itemPlaceholder")}
            onChange={(event) => onTextChange(event.target.value)}
            onBlur={onTextBlur}
            onKeyDown={onKeyDown}
            disabled={!canEdit}
            rows={1}
            className="max-h-48 min-h-0 resize-none"
          />
        ) : (
          <Input
            ref={inputRef as RefObject<HTMLInputElement>}
            value={item.text}
            placeholder={t("checklist.itemPlaceholder")}
            onChange={(event) => onTextChange(event.target.value)}
            onBlur={onTextBlur}
            onKeyDown={onKeyDown}
            disabled={!canEdit}
          />
        )}
        {clipped || expanded ? (
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="shrink-0 self-start text-muted-foreground"
            aria-label={expanded ? t("checklist.collapseItem") : t("checklist.expandItem")}
            aria-expanded={expanded}
            onClick={() => setExpanded((open) => !open)}
          >
            {expanded ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
          </Button>
        ) : null}
      </div>
      {canEdit ? (
        <div className="flex items-center gap-1 self-end sm:self-auto">
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="text-muted-foreground"
            aria-label={t("checklist.promoteLabel")}
            title={t("checklist.promote")}
            disabled={!onPromote}
            onClick={onPromote}
          >
            <ListTree className="h-4 w-4" />
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="text-destructive hover:text-destructive"
            aria-label={t("checklist.deleteItem")}
            onClick={onDelete}
          >
            <Trash2 className="h-4 w-4" />
          </Button>
        </div>
      ) : null}
    </li>
  );
};
