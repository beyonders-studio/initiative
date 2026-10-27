import { useParams } from "@tanstack/react-router";
import { Plus } from "lucide-react";
import { useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import type { QueueItemCreate, QueueItemRead } from "@/api/generated/initiativeAPI.schemas";
import { Tool, ViewSource } from "@/api/generated/initiativeAPI.schemas";
import { ToolCommentsPanel } from "@/components/comments/ToolCommentsPanel";
import { ToolRelationsPanel } from "@/components/entities/ToolRelationsPanel";
import { ActHeldButton } from "@/components/initiativeTools/queues/ActHeldButton";
import { EditQueueItemDialog } from "@/components/initiativeTools/queues/EditQueueItemDialog";
import { QueueControls } from "@/components/initiativeTools/queues/QueueControls";
import { QueueItemRow } from "@/components/initiativeTools/queues/QueueItemRow";
import { QueueTimeline } from "@/components/initiativeTools/queues/QueueTimeline";
import {
  type QueueView,
  QueueViewToggle,
} from "@/components/initiativeTools/queues/QueueViewToggle";
import { AddItemDialog } from "@/components/layouts/AddItemDialog";
import { useRegisterPrimaryCreateAction } from "@/components/navigation/CreateActionContext";
import {
  DetailPageSkeleton,
  ListSkeleton,
  SkeletonRegion,
} from "@/components/skeletons/PageSkeletons";
import { ToolAccessStatus } from "@/components/ToolAccessStatus";
import { ToolChest, ToolChestSegment } from "@/components/tools/ToolChest";
import { ToolPageHeader } from "@/components/tools/ToolPageHeader";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { useCanonicalInitiativeId } from "@/hooks/useCanonicalInitiativeId";
import { useInitiative } from "@/hooks/useInitiatives";
import { layoutViewSpec, useListView, viewKey } from "@/hooks/useListView";
import { useReadOnOpen } from "@/hooks/useNotifications";
import { useRecordOpen } from "@/hooks/usePersonalItems";
import {
  useAdvanceTurn,
  useCreateQueueItem,
  useHoldCurrent,
  usePreviousTurn,
  useQueue,
  useReleaseHeld,
  useResetQueue,
  useSetActiveItem,
  useStartQueue,
  useStopQueue,
  useUpdateQueue,
} from "@/hooks/useQueues";
import { useToolRealtime } from "@/hooks/useResourceRealtime";
import { instanceTarget } from "@/hooks/useToolLayouts";
import { useCommunityPath } from "@/lib/communityUrl";
import { blankQueueItem, QUEUE_ITEM_DETAIL } from "@/lib/layouts/queueItemLayout";
import { toast } from "@/lib/mascotToast";
import { getItem } from "@/lib/storage";
import { toolListRoute, toolSettingsRoute } from "@/lib/tools";

export function QueueDetailPage() {
  const { t } = useTranslation(["queues", "common"]);
  const { queueId } = useParams({ strict: false }) as { queueId: string };
  const parsedId = Number(queueId);
  const gp = useCommunityPath();

  const queueQuery = useQueue(Number.isFinite(parsedId) ? parsedId : null);
  const queue = queueQuery.data;
  // The path supplies the initiative while this loads, but the entity is the
  // authority once it arrives — a URL naming a different one is corrected
  // rather than left to build links into an initiative it isn't in.
  const initiativeId = useCanonicalInitiativeId(queue?.initiative_id);

  // Track recently viewed queues for the layout header tabs bar.
  const viewedQueueId = queue?.id;
  useReadOnOpen(Tool.queue, viewedQueueId);
  useRecordOpen(Tool.queue, viewedQueueId);

  // List or on-deck, kept in this person's view of the queue. What an older
  // release kept, on the account or before that on this device, carries over.
  const communityId = useActiveCommunityId();
  const viewSpec = useMemo(
    () =>
      layoutViewSpec(
        viewKey(communityId, "queue", parsedId),
        (items) => items[`queue-${parsedId}-view`] ?? getItem(`queues.view.${parsedId}`)
      ),
    [communityId, parsedId]
  );
  const queueView = useListView(viewSpec);
  const view: QueueView = queueView.layout === "list" ? "list" : "on-deck";
  const setView = queueView.rememberLayout as (next: QueueView) => void;

  // Turn controls just fire the mutation. The optimistic cache write happens
  // synchronously in the hook's `onMutate`; the On Deck component watches
  // the resulting queue prop and wraps its own re-render in a View
  // Transition. That way the animation plays for local clicks, the
  // mutation's server response, *and* WebSocket-driven refetches when
  // another user advances the queue.

  // Connect WebSocket for live updates
  useToolRealtime(Tool.queue, Number.isFinite(parsedId) ? parsedId : null);

  const updateQueue = useUpdateQueue(parsedId, {
    onSuccess: () => toast.success(t("queueUpdated")),
  });

  // Turn controls
  const startQueue = useStartQueue(parsedId, {
    onSuccess: () => toast.success(t("queueStarted")),
  });
  const stopQueue = useStopQueue(parsedId, {
    onSuccess: () => toast.success(t("queueStopped")),
  });
  const advanceTurn = useAdvanceTurn(parsedId);
  const previousTurn = usePreviousTurn(parsedId);
  const resetQueue = useResetQueue(parsedId, {
    onSuccess: () => toast.success(t("queueReset")),
  });
  const setActiveItem = useSetActiveItem(parsedId);
  const holdCurrent = useHoldCurrent(parsedId, {
    onSuccess: () => toast.success(t("queueHeld")),
  });
  const releaseHeld = useReleaseHeld(parsedId, {
    onSuccess: () => toast.success(t("queueReleased")),
  });

  const isControlLoading =
    startQueue.isPending ||
    stopQueue.isPending ||
    advanceTurn.isPending ||
    previousTurn.isPending ||
    resetQueue.isPending ||
    holdCurrent.isPending ||
    releaseHeld.isPending;

  // Item dialogs
  const [addItemOpen, setAddItemOpen] = useState(false);
  const createItem = useCreateQueueItem(parsedId);
  const leaving = useRef(false);
  const [editingItem, setEditingItem] = useState<QueueItemRead | null>(null);
  // An item opens in its dialog.
  useRecordOpen("queue_item", editingItem?.id, { source: ViewSource.direct });

  const canEdit = Boolean(queue?.can.edit);
  const initiativeQuery = useInitiative(queue?.initiative_id ?? null);
  const canModerate = Boolean(initiativeQuery.data?.can.moderate);

  // Drive the app-wide bottom-nav add button for this route.
  useRegisterPrimaryCreateAction(
    canEdit ? { run: () => setAddItemOpen(true), label: t("addItem") } : null
  );

  // Sort items by position descending (highest initiative goes first)
  const sortedItems = useMemo(() => {
    if (!queue?.items) return [];
    return [...queue.items].sort((a, b) => b.position - a.position);
  }, [queue?.items]);

  // Error / loading states
  if (queueQuery.isLoading) {
    return (
      <SkeletonRegion label={t("loadingQueue")}>
        <DetailPageSkeleton actions={3}>
          <ListSkeleton rows={5} rowClassName="rounded-lg border bg-card p-3" />
        </DetailPageSkeleton>
      </SkeletonRegion>
    );
  }

  if (queueQuery.isError || !queue) {
    return (
      <ToolAccessStatus
        error={queueQuery.error}
        keys="queues:"
        backTo={gp(toolListRoute(Tool.queue, initiativeId))}
        backLabel={t("backToQueues")}
        entity={{ kind: "queue", id: parsedId }}
      />
    );
  }

  const currentItemId = queue.current_item_id;

  return (
    <div className="space-y-6">
      <ToolPageHeader
        tool={Tool.queue}
        initiativeId={queue.initiative_id}
        starId={queue.id}
        settingsTo={canEdit ? toolSettingsRoute(Tool.queue, initiativeId, queue.id) : undefined}
        title={queue.name}
        onRename={canEdit ? (name) => updateQueue.mutateAsync({ name }) : undefined}
        chest={
          <ToolChest tool={Tool.queue} entity={queue}>
            <QueueControls
              queue={queue}
              onStart={() => startQueue.mutate()}
              onStop={() => stopQueue.mutate()}
              onNext={() => advanceTurn.mutate()}
              onPrevious={() => previousTurn.mutate()}
              onReset={() => resetQueue.mutate()}
              onHold={() => holdCurrent.mutate()}
              isLoading={isControlLoading}
            />
            <ToolChestSegment>
              <QueueViewToggle view={view} onChange={setView} />
              {canEdit && (
                <Button variant="outline" size="sm" onClick={() => setAddItemOpen(true)}>
                  <Plus className="h-4 w-4" />
                  {t("addItem")}
                </Button>
              )}
            </ToolChestSegment>
          </ToolChest>
        }
      >
        {queue.description && <p className="text-muted-foreground text-sm">{queue.description}</p>}
      </ToolPageHeader>

      {/* Items list */}
      <div className="space-y-3">
        {sortedItems.length === 0 ? (
          <Card>
            <CardHeader>
              <CardTitle>{t("noItems")}</CardTitle>
              <CardDescription>{t("noItemsDescription")}</CardDescription>
            </CardHeader>
            <CardContent>
              {canEdit && (
                <Button onClick={() => setAddItemOpen(true)}>
                  <Plus className="h-4 w-4" />
                  {t("addItem")}
                </Button>
              )}
            </CardContent>
          </Card>
        ) : view === "on-deck" ? (
          <QueueTimeline
            queue={queue}
            onEdit={(editItem) => setEditingItem(editItem)}
            onSetActive={(itemId) => {
              if (canEdit && queue.is_active) {
                setActiveItem.mutate(itemId);
              }
            }}
            onAct={(itemId, reposition) => {
              if (canEdit) {
                releaseHeld.mutate({ itemId, reposition });
              }
            }}
          />
        ) : (
          <div className="space-y-2">
            {sortedItems.map((item) => (
              <QueueItemRow
                key={item.id}
                item={item}
                isActive={item.id === currentItemId}
                onEdit={(editItem) => setEditingItem(editItem)}
                onSetActive={(itemId) => {
                  if (canEdit && queue.is_active) {
                    setActiveItem.mutate(itemId);
                  }
                }}
                actionButton={
                  canEdit && item.held_at_round !== null ? (
                    <ActHeldButton
                      itemId={item.id}
                      onAct={(id, reposition) => releaseHeld.mutate({ itemId: id, reposition })}
                    />
                  ) : undefined
                }
              />
            ))}
          </div>
        )}
      </div>

      <ToolRelationsPanel
        tool={Tool.queue}
        entity={queue}
        canEdit={canEdit}
        entityTitle={queue?.name}
      />

      <ToolCommentsPanel tool={Tool.queue} entity={queue} />

      <AddItemDialog
        open={addItemOpen}
        onOpenChange={setAddItemOpen}
        detail={QUEUE_ITEM_DETAIL}
        blank={blankQueueItem(parsedId)}
        context={{
          readOnly: false,
          queueId: parsedId,
          initiativeId: queue.initiative_id,
          leaving,
          actions: null,
        }}
        layouts={() => instanceTarget(Tool.queue, parsedId)}
        title={t("addItem")}
        ready={(item) => item.label.trim() !== ""}
        create={({ item, fields, properties }) =>
          createItem.mutateAsync({
            color: item.color,
            is_visible: item.is_visible,
            ...fields,
            properties,
          } as QueueItemCreate)
        }
        onAdded={() => {
          toast.success(t("itemAdded"));
          setAddItemOpen(false);
        }}
      />

      {/* Edit Item Dialog */}
      {editingItem && (
        <EditQueueItemDialog
          open={editingItem !== null}
          onOpenChange={(open) => {
            if (!open) setEditingItem(null);
          }}
          queueId={parsedId}
          initiativeId={queue.initiative_id}
          item={editingItem}
          readOnly={!canEdit}
          canModerate={canModerate}
        />
      )}
    </div>
  );
}
