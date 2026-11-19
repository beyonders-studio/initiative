import { Link, useNavigate, useParams } from "@tanstack/react-router";
import { Bell, Pencil } from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { type CounterRead, Tool } from "@/api/generated/initiativeAPI.schemas";
import { ToolAccessStatus } from "@/components/tools/ToolAccessStatus";
import { useCanonicalInitiativeId } from "@/hooks/useCanonicalInitiativeId";
import {
  useCounterGroup,
  useResetCounter,
  useSetCount,
  useSteppedCount,
} from "@/hooks/useCounters";
import { useRecordOpen, useSubscription } from "@/hooks/usePersonalItems";
import { useToolRealtime } from "@/hooks/useResourceRealtime";
import { useCommunityPath } from "@/lib/communityUrl";
import { counterShown } from "@/lib/counter-math";
import { counterRoute, toolDetailRoute, toolListRoute } from "@/lib/tools";
import { Button } from "@/ui/button";
import { DropdownMenuItem } from "@/ui/dropdown-menu";
import { getContrastingTextColor } from "@/ui/lib/contrast";
import { CounterFocusSkeleton } from "@/ui/page-skeletons";
import { CounterFocus } from "@/ui/properties/CounterFocus";

import { EditCounterDialog } from "./EditCounterDialog";

export function CounterPage() {
  const { t } = useTranslation(["counterGroups", "common"]);
  const navigate = useNavigate();
  const gp = useCommunityPath();
  const {
    communityId,
    counterGroupId: groupIdParam,
    counterId: counterIdParam,
  } = useParams({
    strict: false,
  }) as {
    communityId?: string;
    counterGroupId?: string;
    counterId?: string;
  };

  const groupId = groupIdParam ? Number(groupIdParam) : null;
  const counterId = counterIdParam ? Number(counterIdParam) : null;

  const groupQuery = useCounterGroup(groupId);
  useToolRealtime(Tool.counter_group, groupId);

  const setCount = useSetCount(groupId ?? 0);
  const stepper = useSteppedCount(groupId ?? 0);
  const resetOne = useResetCounter(groupId ?? 0);

  const [editing, setEditing] = useState<CounterRead | null>(null);

  const group = groupQuery.data;
  // The path supplies the initiative while this loads; the entity is the
  // authority once it arrives, and a URL naming a different one is corrected.
  const initiativeId = useCanonicalInitiativeId(group?.initiative_id);
  const counters = useMemo(() => {
    const list = group?.counters ?? [];
    return [...list].sort((a, b) => Number(a.position) - Number(b.position));
  }, [group?.counters]);

  const currentIndex = useMemo(
    () => counters.findIndex((c) => c.id === counterId),
    [counters, counterId]
  );
  const counter = currentIndex >= 0 ? counters[currentIndex] : null;
  useRecordOpen("counter", counter?.id);
  const subscription = useSubscription("counter", counter?.id ?? 0);

  const canWrite = Boolean(group?.can.edit);

  const goToCounter = (index: number) => {
    if (counters.length === 0 || !communityId || !groupId) return;
    const wrapped = ((index % counters.length) + counters.length) % counters.length;
    const next = counters[wrapped];
    if (!next) return;
    navigate({ to: gp(counterRoute(initiativeId, groupId, next.id)), replace: true });
  };

  if (groupId === null || counterId === null) return null;

  if (groupQuery.isLoading) {
    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-background">
        <CounterFocusSkeleton />
      </div>
    );
  }

  if (groupQuery.isError || !group) {
    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-background px-4">
        <ToolAccessStatus
          error={groupQuery.error}
          keys="counterGroups:"
          backTo={gp(toolListRoute(Tool.counter_group, initiativeId))}
          backLabel={t("backToGroups")}
          entity={groupId === null ? undefined : { kind: "counter_group", id: groupId }}
        />
      </div>
    );
  }

  if (!counter) {
    return (
      <div className="fixed inset-0 z-50 flex flex-col items-center justify-center gap-3 bg-background px-4 text-center">
        <h1 className="font-semibold text-2xl">{t("focus.notFound")}</h1>
        <Button variant="outline" asChild>
          <Link to={gp(toolDetailRoute(Tool.counter_group, initiativeId, groupId))}>
            {t("backToGroup")}
          </Link>
        </Button>
      </div>
    );
  }

  return (
    <>
      <CounterFocus
        counter={counterShown(counter)}
        name={counter.name}
        color={counter.color}
        textColor={getContrastingTextColor(counter.color)}
        disabled={!canWrite}
        onStep={(up) => (up ? stepper.increment(counter) : stepper.decrement(counter))}
        onCommit={(value) => {
          stepper.cancel(counter.id);
          setCount.mutate({ counterId: counter.id, data: { count: value } });
        }}
        onExit={() =>
          navigate({ to: gp(toolDetailRoute(Tool.counter_group, initiativeId, groupId)) })
        }
        onReset={() => {
          stepper.cancel(counter.id);
          resetOne.mutate(counter.id);
        }}
        actions={(buttonClassName) => (
          <Button
            variant="ghost"
            size="icon"
            aria-pressed={subscription.subscribed}
            aria-label={
              subscription.subscribed ? t("common:subscribe.remove") : t("common:subscribe.add")
            }
            title={
              subscription.subscribed ? t("common:subscribe.remove") : t("common:subscribe.add")
            }
            disabled={!subscription.ready}
            onClick={subscription.toggle}
            className={buttonClassName}
          >
            <Bell className="h-5 w-5" fill={subscription.subscribed ? "currentColor" : "none"} />
          </Button>
        )}
        menuItems={
          <DropdownMenuItem disabled={!canWrite} onSelect={() => setEditing(counter)}>
            <Pencil className="h-4 w-4" />
            {t("editCounter")}
          </DropdownMenuItem>
        }
        navigation={{
          index: currentIndex,
          total: counters.length,
          onMove: (by) => goToCounter(currentIndex + by),
        }}
      />
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
    </>
  );
}
