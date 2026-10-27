import {
  closestCenter,
  DndContext,
  type DragEndEvent,
  MouseSensor,
  TouchSensor,
  useSensor,
  useSensors,
} from "@dnd-kit/core";
import {
  rectSortingStrategy,
  SortableContext,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { useParams } from "@tanstack/react-router";
import { ArrowDownUp, LayoutGrid, List, Plus, RotateCcw } from "lucide-react";
import { useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import type { CounterCreate, CounterRead } from "@/api/generated/initiativeAPI.schemas";
import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { ToolCommentsPanel } from "@/components/comments/ToolCommentsPanel";
import { ToolRelationsPanel } from "@/components/entities/ToolRelationsPanel";
import { type CounterLayout, CounterRow } from "@/components/initiativeTools/counters/CounterRow";
import { EditCounterDialog } from "@/components/initiativeTools/counters/EditCounterDialog";
import { AddItemDialog } from "@/components/layouts/AddItemDialog";
import { useRegisterPrimaryCreateAction } from "@/components/navigation/CreateActionContext";
import { computeMidpoint } from "@/components/projects/taskOrdering";
import {
  CardGridSkeleton,
  DetailPageSkeleton,
  SkeletonRegion,
} from "@/components/skeletons/PageSkeletons";
import { ToolAccessStatus } from "@/components/ToolAccessStatus";
import { ToolChest, ToolChestSegment } from "@/components/tools/ToolChest";
import { ToolPageHeader } from "@/components/tools/ToolPageHeader";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { useCanonicalInitiativeId } from "@/hooks/useCanonicalInitiativeId";
import {
  useAddCounter,
  useCounterGroup,
  useDeleteCounter,
  useDuplicateCounter,
  useResetAllCounters,
  useResetCounter,
  useSetCount,
  useSortCounters,
  useSteppedCount,
  useUpdateCounter,
  useUpdateCounterGroup,
} from "@/hooks/useCounters";
import { layoutViewSpec, useListView, viewKey } from "@/hooks/useListView";
import { useReadOnOpen } from "@/hooks/useNotifications";
import { useRecordOpen } from "@/hooks/usePersonalItems";
import { useToolRealtime } from "@/hooks/useResourceRealtime";
import { instanceTarget } from "@/hooks/useToolLayouts";
import { useCommunityPath } from "@/lib/communityUrl";
import { pickRandomCounterColor } from "@/lib/counter-color";
import { blankCounter, COUNTER_DETAIL, counterReady } from "@/lib/layouts/counterLayout";
import { toast } from "@/lib/mascotToast";
import { counterRoute, toolListRoute, toolSettingsRoute } from "@/lib/tools";

/** Where an older release kept a group's rows or grid. */
const layoutStorageKey = (groupId: number) => `counter-group-${groupId}-layout`;

export function CounterGroupDetailPage() {
  const { t } = useTranslation(["counterGroups", "common"]);
  const gp = useCommunityPath();
  const { counterGroupId: groupIdParam } = useParams({ strict: false }) as {
    counterGroupId?: string;
  };
  const groupId = groupIdParam ? Number(groupIdParam) : null;

  const groupQuery = useCounterGroup(groupId);
  useToolRealtime(Tool.counter_group, groupId);

  const sensors = useSensors(
    useSensor(MouseSensor, { activationConstraint: { distance: 8 } }),
    useSensor(TouchSensor, { activationConstraint: { distance: 8 } })
  );

  const updateCounter = useUpdateCounter(groupId ?? 0);
  const setCount = useSetCount(groupId ?? 0);
  const stepper = useSteppedCount(groupId ?? 0);
  const resetOne = useResetCounter(groupId ?? 0);
  const resetAll = useResetAllCounters(groupId ?? 0);
  const deleteCounter = useDeleteCounter(groupId ?? 0);
  const duplicateCounter = useDuplicateCounter(groupId ?? 0, {
    onSuccess: () => toast.success(t("common:subToolDuplicate.done")),
  });
  const sortCounters = useSortCounters(groupId ?? 0);
  const updateGroup = useUpdateCounterGroup(groupId ?? 0);

  const [addOpen, setAddOpen] = useState(false);
  const addCounter = useAddCounter(groupId ?? 0);
  const leaving = useRef(false);
  const [editing, setEditing] = useState<CounterRead | null>(null);
  const [resetAllOpen, setResetAllOpen] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<CounterRead | null>(null);
  // The scope key encodes groupId, so the hook automatically returns
  // the right value when navigating between groups — no manual re-read.
  // Rows or a grid, kept in this person's view of the group. What an older
  // release kept on the account carries over.
  const communityId = useActiveCommunityId();
  const viewSpec = useMemo(
    () =>
      layoutViewSpec(viewKey(communityId, "counter-group", groupId ?? 0), (items) =>
        groupId !== null ? items[layoutStorageKey(groupId)] : undefined
      ),
    [communityId, groupId]
  );
  const groupView = useListView(viewSpec);
  const persistedLayout = groupView.layout;
  const setPersistedLayout = groupView.rememberLayout;
  const layout: CounterLayout = persistedLayout === "grid" ? "grid" : "row";

  const toggleLayout = () => {
    if (groupId === null) return;
    setPersistedLayout(layout === "row" ? "grid" : "row");
  };

  const group = groupQuery.data;
  // The path supplies the initiative while this loads, but the entity is the
  // authority once it arrives — a URL naming a different one is corrected
  // rather than left to build links into an initiative it isn't in.
  const initiativeId = useCanonicalInitiativeId(group?.initiative_id);
  const counters = useMemo(() => {
    const list = group?.counters ?? [];
    return [...list].sort((a, b) => Number(a.position) - Number(b.position));
  }, [group?.counters]);

  // Track recently viewed counter groups for the layout header tabs bar.
  const viewedGroupId = group?.id;
  useReadOnOpen(Tool.counter_group, viewedGroupId);
  useRecordOpen(Tool.counter_group, viewedGroupId);

  const canWrite = Boolean(group?.can.edit);

  // Drive the app-wide bottom-nav add button for this route.
  useRegisterPrimaryCreateAction(
    canWrite ? { run: () => setAddOpen(true), label: t("addCounter") } : null
  );

  const handleDragEnd = (event: DragEndEvent) => {
    const { active, over } = event;
    if (!over || active.id === over.id || groupId === null) return;
    const activeId = Number(active.id);
    const overId = Number(over.id);
    const oldIndex = counters.findIndex((c) => c.id === activeId);
    const newIndex = counters.findIndex((c) => c.id === overId);
    if (oldIndex === -1 || newIndex === -1) return;

    // Build the list with `active` removed, then compute the midpoint for its new slot.
    const withoutActive = counters
      .filter((c) => c.id !== activeId)
      .map((c) => ({ position: Number(c.position) }));
    const newPosition = computeMidpoint(withoutActive, newIndex).toFixed(10);

    updateCounter.mutate({
      counterId: activeId,
      data: { position: newPosition },
    });
  };

  const nextPosition = useMemo(() => {
    if (counters.length === 0) return "0";
    const max = counters.reduce((acc, c) => Math.max(acc, Number(c.position)), 0);
    return (max + 1).toFixed(10);
  }, [counters]);

  if (groupId === null) return null;

  if (groupQuery.isLoading) {
    return (
      <SkeletonRegion label={t("loadingGroup")}>
        <DetailPageSkeleton actions={4}>
          <CardGridSkeleton count={3} />
        </DetailPageSkeleton>
      </SkeletonRegion>
    );
  }

  if (groupQuery.isError || !group) {
    return (
      <ToolAccessStatus
        error={groupQuery.error}
        keys="counterGroups:"
        backTo={gp(toolListRoute(Tool.counter_group, initiativeId))}
        backLabel={t("backToGroups")}
        entity={groupId === null ? undefined : { kind: "counter_group", id: groupId }}
      />
    );
  }

  return (
    <div className="space-y-6">
      <ToolPageHeader
        tool={Tool.counter_group}
        initiativeId={group.initiative_id}
        starId={group.id}
        settingsTo={
          canWrite ? toolSettingsRoute(Tool.counter_group, initiativeId, group.id) : undefined
        }
        chest={
          <ToolChest tool={Tool.counter_group} entity={group}>
            <ToolChestSegment>
              <div className="flex items-center gap-2">
                <Button
                  variant="outline"
                  size="icon-sm"
                  onClick={toggleLayout}
                  aria-label={layout === "row" ? t("switchToGridView") : t("switchToRowView")}
                  title={layout === "row" ? t("switchToGridView") : t("switchToRowView")}
                >
                  {layout === "row" ? (
                    <LayoutGrid className="h-4 w-4" />
                  ) : (
                    <List className="h-4 w-4" />
                  )}
                </Button>
                {canWrite && (
                  <>
                    <Button variant="outline" size="sm" onClick={() => setAddOpen(true)}>
                      <Plus className="h-4 w-4" />
                      {t("addCounter")}
                    </Button>
                    {counters.length > 1 && (
                      <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                          <Button variant="outline" size="sm" disabled={sortCounters.isPending}>
                            <ArrowDownUp className="h-4 w-4" />
                            {t("sort")}
                          </Button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end">
                          <DropdownMenuItem
                            onSelect={() =>
                              sortCounters.mutate({ field: "name", direction: "asc" })
                            }
                          >
                            {t("sortNameAsc")}
                          </DropdownMenuItem>
                          <DropdownMenuItem
                            onSelect={() =>
                              sortCounters.mutate({ field: "name", direction: "desc" })
                            }
                          >
                            {t("sortNameDesc")}
                          </DropdownMenuItem>
                          <DropdownMenuItem
                            onSelect={() =>
                              sortCounters.mutate({ field: "count", direction: "asc" })
                            }
                          >
                            {t("sortCountAsc")}
                          </DropdownMenuItem>
                          <DropdownMenuItem
                            onSelect={() =>
                              sortCounters.mutate({ field: "count", direction: "desc" })
                            }
                          >
                            {t("sortCountDesc")}
                          </DropdownMenuItem>
                        </DropdownMenuContent>
                      </DropdownMenu>
                    )}
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setResetAllOpen(true)}
                      disabled={counters.length === 0 || resetAll.isPending}
                    >
                      <RotateCcw className="h-4 w-4" />
                      {t("resetAll")}
                    </Button>
                  </>
                )}
              </div>
            </ToolChestSegment>
          </ToolChest>
        }
        title={group.name}
        onRename={canWrite ? (name) => updateGroup.mutateAsync({ name }) : undefined}
      >
        {group.description && (
          <p className="max-w-2xl text-muted-foreground text-sm">{group.description}</p>
        )}
      </ToolPageHeader>

      {counters.length === 0 ? (
        <div className="rounded-lg border border-dashed p-8 text-center">
          <p className="font-medium text-muted-foreground">{t("noCounters")}</p>
          <p className="mt-1 text-muted-foreground text-sm">{t("noCountersDescription")}</p>
          {canWrite && (
            <Button className="mt-4" onClick={() => setAddOpen(true)}>
              <Plus className="h-4 w-4" />
              {t("addCounter")}
            </Button>
          )}
        </div>
      ) : (
        <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
          <SortableContext
            items={counters.map((c) => c.id.toString())}
            strategy={layout === "grid" ? rectSortingStrategy : verticalListSortingStrategy}
          >
            <div className={layout === "grid" ? "grid grid-cols-fill-36/5 gap-3" : "space-y-2"}>
              {counters.map((counter) => (
                <CounterRow
                  key={counter.id}
                  counter={counter}
                  canWrite={canWrite}
                  layout={layout}
                  focusHref={gp(counterRoute(initiativeId, group.id, counter.id))}
                  onSetCount={(value) => {
                    // Direct typed entry wins over any pending stepped flush.
                    stepper.cancel(counter.id);
                    setCount.mutate({ counterId: counter.id, data: { count: value } });
                  }}
                  onIncrement={() => stepper.increment(counter)}
                  onDecrement={() => stepper.decrement(counter)}
                  onReset={() => {
                    stepper.cancel(counter.id);
                    resetOne.mutate(counter.id);
                  }}
                  onEdit={() => setEditing(counter)}
                  onDuplicate={() => duplicateCounter.mutate(counter.id)}
                  onDelete={() => {
                    stepper.cancel(counter.id);
                    setPendingDelete(counter);
                  }}
                />
              ))}
            </div>
          </SortableContext>
        </DndContext>
      )}

      <ToolRelationsPanel
        tool={Tool.counter_group}
        entity={group}
        canEdit={canWrite}
        entityTitle={group?.name}
      />

      <ToolCommentsPanel tool={Tool.counter_group} entity={group} />

      {canWrite && (
        <AddItemDialog
          open={addOpen}
          onOpenChange={setAddOpen}
          detail={COUNTER_DETAIL}
          blank={blankCounter(groupId, pickRandomCounterColor())}
          context={{
            readOnly: false,
            groupId,
            initiativeId: group.initiative_id,
            leaving,
            actions: null,
          }}
          layouts={() =>
            group.initiative_id === null ? null : instanceTarget(Tool.counter_group, groupId)
          }
          title={t("addCounter")}
          ready={counterReady}
          create={({ item, fields, properties }) =>
            addCounter.mutateAsync({
              color: item.color,
              position: nextPosition,
              // It starts at the count it is reset to.
              count: item.initial_count,
              ...fields,
              properties,
            } as CounterCreate)
          }
          onAdded={() => setAddOpen(false)}
        />
      )}

      {canWrite && editing && (
        <EditCounterDialog
          open={!!editing}
          onOpenChange={(open) => {
            if (!open) setEditing(null);
          }}
          groupId={groupId}
          initiativeId={group.initiative_id}
          counter={editing}
          stepper={stepper}
        />
      )}

      <ConfirmDialog
        open={resetAllOpen}
        onOpenChange={setResetAllOpen}
        title={t("resetAll")}
        description={t("resetAllConfirm")}
        confirmLabel={t("resetAll")}
        onConfirm={() => {
          // Drop any in-flight stepped edits so they don't overwrite the reset.
          stepper.cancelAll();
          resetAll.mutate(undefined, {
            onSuccess: () => setResetAllOpen(false),
          });
        }}
      />

      <ConfirmDialog
        open={!!pendingDelete}
        onOpenChange={(open) => {
          if (!open) setPendingDelete(null);
        }}
        title={t("removeCounter")}
        description={t("removeCounterConfirm")}
        confirmLabel={t("removeCounter")}
        destructive
        onConfirm={() => {
          if (!pendingDelete) return;
          deleteCounter.mutate(pendingDelete.id, {
            onSuccess: () => setPendingDelete(null),
          });
        }}
      />
    </div>
  );
}
