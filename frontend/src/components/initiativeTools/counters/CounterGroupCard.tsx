import {
  type CounterGroupSummary,
  type CounterPreview,
  Tool,
} from "@/api/generated/initiativeAPI.schemas";
import { ToolCard } from "@/components/tools/ToolCard";
import { getContrastingTextColor } from "@/lib/counter-color";
import { toolDetailRoute } from "@/lib/tools";
import { numberFormat } from "@/ui/lib/intl";

/** The group's first counters and where they stand, as the list sent them,
 *  in the colours they wear on the group's own page. */
const CounterGroupPreview = ({ counters }: { counters: CounterPreview[] }) => (
  <div aria-hidden className="grid min-h-24 grid-cols-2 gap-1.5 border-b bg-muted/40 p-3">
    {counters.map((counter) => (
      <div
        key={counter.id}
        className="flex min-w-0 flex-col justify-between rounded-lg border px-2.5 py-1.5"
        style={{
          backgroundColor: counter.color ?? "hsl(var(--card))",
          color: getContrastingTextColor(counter.color) ?? "hsl(var(--card-foreground))",
        }}
      >
        <span className="truncate text-xs opacity-80">{counter.name}</span>
        <span className="font-semibold text-xl tabular-nums leading-tight">
          {numberFormat().format(Number(counter.count))}
        </span>
      </div>
    ))}
  </div>
);

export const CounterGroupCard = ({ group }: { group: CounterGroupSummary }) => (
  <ToolCard
    to={toolDetailRoute(Tool.counter_group, group.initiative_id, group.id)}
    name={group.name}
    description={group.description}
    tags={group.tags}
    preview={group.preview?.length ? <CounterGroupPreview counters={group.preview} /> : null}
  />
);
