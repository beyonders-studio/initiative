import { Link, useNavigate, useParams } from "@tanstack/react-router";
import {
  Bell,
  ChevronLeft,
  ChevronRight,
  Minus,
  MoreVertical,
  Pencil,
  Plus,
  RotateCcw,
  X,
} from "lucide-react";
import { type TouchEvent, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { type CounterRead, Tool } from "@/api/generated/initiativeAPI.schemas";
import { EditCounterDialog } from "@/components/initiativeTools/counters/EditCounterDialog";
import { CounterView } from "@/components/initiativeTools/counters/views/CounterView";
import { CounterFocusSkeleton } from "@/components/skeletons/PageSkeletons";
import { ToolAccessStatus } from "@/components/ToolAccessStatus";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
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
import { getContrastingTextColor } from "@/lib/counter-color";
import { isAtMax, isAtMin } from "@/lib/counter-math";
import { counterRoute, toolDetailRoute, toolListRoute } from "@/lib/tools";
import { cn } from "@/lib/utils";

const SWIPE_THRESHOLD_PX = 60;

export function CounterDetailPage() {
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
  const [touchStartX, setTouchStartX] = useState<number | null>(null);
  const [touchStartY, setTouchStartY] = useState<number | null>(null);

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

  const handleTouchStart = (event: TouchEvent<HTMLDivElement>) => {
    const touch = event.touches[0];
    if (!touch) return;
    setTouchStartX(touch.clientX);
    setTouchStartY(touch.clientY);
  };

  const handleTouchEnd = (event: TouchEvent<HTMLDivElement>) => {
    if (touchStartX === null || touchStartY === null) return;
    const touch = event.changedTouches[0];
    if (!touch) return;
    const dx = touch.clientX - touchStartX;
    const dy = touch.clientY - touchStartY;
    setTouchStartX(null);
    setTouchStartY(null);
    if (Math.abs(dx) < SWIPE_THRESHOLD_PX || Math.abs(dx) <= Math.abs(dy)) return;
    goToCounter(currentIndex + (dx < 0 ? 1 : -1));
  };

  if (groupId === null || counterId === null) return null;

  if (groupQuery.isLoading) {
    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-background">
        <CounterFocusSkeleton label={t("loadingGroup")} />
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

  const bg = counter.color ?? "hsl(var(--background))";
  const fg = getContrastingTextColor(counter.color) ?? "hsl(var(--foreground))";
  const isLight = fg === "#0F172A";

  const stepButtonClass = isLight
    ? "bg-black/15 hover:bg-black/25 active:bg-black/35"
    : "bg-white/15 hover:bg-white/25 active:bg-white/35";

  const chromeButtonClass = isLight
    ? "hover:bg-black/10 focus-visible:bg-black/10"
    : "hover:bg-white/10 focus-visible:bg-white/10";

  return (
    <div className="fixed inset-0 z-50 flex flex-col" style={{ background: bg, color: fg }}>
      <header className="flex items-center justify-between gap-2 px-3 pt-[max(env(safe-area-inset-top),0.75rem)] pb-2">
        <Button
          variant="ghost"
          size="icon"
          asChild
          aria-label={t("focus.exit")}
          className={cn("h-10 w-10", chromeButtonClass)}
          style={{ color: fg }}
        >
          <Link to={gp(toolDetailRoute(Tool.counter_group, initiativeId, groupId))}>
            <X className="h-5 w-5" />
          </Link>
        </Button>
        <h1
          className="min-w-0 flex-1 truncate text-center font-semibold text-lg"
          title={counter.name}
        >
          {counter.name}
        </h1>
        {/* On the counter's own colours: filled when subscribed. */}
        <Button
          variant="ghost"
          size="icon"
          aria-pressed={subscription.subscribed}
          aria-label={
            subscription.subscribed ? t("common:subscribe.remove") : t("common:subscribe.add")
          }
          title={subscription.subscribed ? t("common:subscribe.remove") : t("common:subscribe.add")}
          disabled={!subscription.ready}
          onClick={subscription.toggle}
          className={cn("h-10 w-10", chromeButtonClass)}
          style={{ color: fg }}
        >
          <Bell className="h-5 w-5" fill={subscription.subscribed ? "currentColor" : "none"} />
        </Button>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              variant="ghost"
              size="icon"
              aria-label={t("more")}
              className={cn("h-10 w-10", chromeButtonClass)}
              style={{ color: fg }}
            >
              <MoreVertical className="h-5 w-5" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem
              disabled={!canWrite}
              onSelect={() => {
                stepper.cancel(counter.id);
                resetOne.mutate(counter.id);
              }}
            >
              <RotateCcw className="h-4 w-4" />
              {t("reset")}
            </DropdownMenuItem>
            <DropdownMenuItem disabled={!canWrite} onSelect={() => setEditing(counter)}>
              <Pencil className="h-4 w-4" />
              {t("editCounter")}
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </header>

      {counters.length > 1 && (
        <div className="flex items-center justify-between gap-3 px-3 pb-2">
          <Button
            variant="ghost"
            size="icon"
            onClick={() => goToCounter(currentIndex - 1)}
            aria-label={t("focus.previous")}
            className={cn("h-10 w-10", chromeButtonClass)}
            style={{ color: fg }}
          >
            <ChevronLeft className="h-5 w-5" />
          </Button>
          <span className="font-mono text-sm tabular-nums opacity-70">
            {t("focus.counterPosition", {
              current: currentIndex + 1,
              total: counters.length,
            })}
          </span>
          <Button
            variant="ghost"
            size="icon"
            onClick={() => goToCounter(currentIndex + 1)}
            aria-label={t("focus.next")}
            className={cn("h-10 w-10", chromeButtonClass)}
            style={{ color: fg }}
          >
            <ChevronRight className="h-5 w-5" />
          </Button>
        </div>
      )}

      <div
        className="flex min-h-0 flex-1 items-center justify-center overflow-hidden px-6 py-4"
        onTouchStart={handleTouchStart}
        onTouchEnd={handleTouchEnd}
      >
        <div className="flex w-full max-w-sm items-center justify-center sm:max-w-md">
          <CounterView
            counter={counter}
            disabled={!canWrite}
            textColor={fg}
            onCommit={(value) => {
              stepper.cancel(counter.id);
              setCount.mutate({ counterId: counter.id, data: { count: value } });
            }}
            size="2xl"
          />
        </div>
      </div>

      <div className="grid grid-cols-2 gap-2 px-3 pt-2 pb-[max(env(safe-area-inset-bottom),0.75rem)]">
        <Button
          type="button"
          variant="ghost"
          onClick={() => stepper.decrement(counter)}
          disabled={!canWrite || isAtMin(counter)}
          aria-label={t("decrement")}
          className={cn(
            "h-24 touch-manipulation rounded-2xl text-current shadow-sm sm:h-28",
            stepButtonClass
          )}
          style={{ color: fg }}
        >
          <Minus className="h-10 w-10" />
        </Button>
        <Button
          type="button"
          variant="ghost"
          onClick={() => stepper.increment(counter)}
          disabled={!canWrite || isAtMax(counter)}
          aria-label={t("increment")}
          className={cn(
            "h-24 touch-manipulation rounded-2xl text-current shadow-sm sm:h-28",
            stepButtonClass
          )}
          style={{ color: fg }}
        >
          <Plus className="h-10 w-10" />
        </Button>
      </div>

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
    </div>
  );
}
