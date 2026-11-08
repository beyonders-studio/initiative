/**
 * Cards a reader drags into an order of their own, for a tool whose index entry
 * keeps one (`ToolIndexEntry.reorder`).
 *
 * Where the handle goes is the card's decision, not the page's: a card draws
 * {@link ToolIndexDragHandle} among its own controls, and the handle shows only
 * while its card sits in a list that can be dragged.
 */

import { closestCenter, DndContext, type DragEndEvent } from "@dnd-kit/core";
import { arrayMove, rectSortingStrategy, SortableContext, useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { GripVertical } from "lucide-react";
import {
  createContext,
  type HTMLAttributes,
  type MouseEvent,
  type ReactNode,
  type Ref,
  useContext,
} from "react";

import { useDragSensors } from "@/ui/lib/useDragSensors";

type DragHandleProps = HTMLAttributes<HTMLButtonElement> & { ref: Ref<HTMLButtonElement> };

const DragHandleContext = createContext<DragHandleProps | null>(null);

/** The grip a card is dragged by. Nothing outside a list that can be dragged. */
export const ToolIndexDragHandle = ({ label }: { label: string }) => {
  const handle = useContext(DragHandleContext);
  if (!handle) return null;
  return (
    <button
      type="button"
      className="inline-flex h-9 w-9 cursor-grab items-center justify-center rounded-md text-muted-foreground transition hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      {...handle}
      aria-label={label}
    >
      <GripVertical className="h-4 w-4" />
    </button>
  );
};

const SortableCard = ({ id, children }: { id: number; children: ReactNode }) => {
  const {
    attributes,
    listeners,
    setNodeRef,
    setActivatorNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: String(id) });
  const handle: DragHandleProps = {
    ...attributes,
    ...listeners,
    ref: setActivatorNodeRef,
    // The grip may sit inside the card's link; a press on it is not a visit.
    onClick: (event: MouseEvent<HTMLButtonElement>) => {
      event.preventDefault();
      event.stopPropagation();
    },
  };
  return (
    <div
      ref={setNodeRef}
      style={{ transform: CSS.Transform.toString(transform), transition }}
      className={isDragging ? "relative z-20 opacity-70" : undefined}
    >
      <DragHandleContext.Provider value={handle}>{children}</DragHandleContext.Provider>
    </div>
  );
};

type SortableCardsProps = {
  /** The cards, in the order they are shown. */
  items: { id: number; card: ReactNode }[];
  /** Called with every id, in the order the drop left them. */
  onReorder: (orderedIds: number[]) => void;
  className: string;
};

export const SortableCards = ({ items, onReorder, className }: SortableCardsProps) => {
  const sensors = useDragSensors({ keyboard: true });
  const ids = items.map((item) => item.id);

  const handleDragEnd = ({ active, over }: DragEndEvent) => {
    if (!over || active.id === over.id) return;
    const from = ids.indexOf(Number(active.id));
    const to = ids.indexOf(Number(over.id));
    if (from === -1 || to === -1) return;
    onReorder(arrayMove(ids, from, to));
  };

  return (
    <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
      <SortableContext items={ids.map(String)} strategy={rectSortingStrategy}>
        <div className={className}>
          {items.map((item) => (
            <SortableCard key={item.id} id={item.id}>
              {item.card}
            </SortableCard>
          ))}
        </div>
      </SortableContext>
    </DndContext>
  );
};
