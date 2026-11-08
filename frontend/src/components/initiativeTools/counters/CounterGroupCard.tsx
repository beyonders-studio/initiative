import { Link } from "@tanstack/react-router";

import {
  type CounterGroupSummary,
  type CounterPreview,
  Tool,
} from "@/api/generated/initiativeAPI.schemas";
import { TagBadgeList } from "@/components/tags/TagBadge";
import { useCommunityPath } from "@/lib/communityUrl";
import { getContrastingTextColor } from "@/lib/counter-color";
import { toolDetailRoute } from "@/lib/tools";
import { Card, CardContent, CardHeader, CardTitle } from "@/ui/card";
import { numberFormat } from "@/ui/lib/intl";
import { cn } from "@/ui/lib/utils";

interface CounterGroupCardProps {
  group: CounterGroupSummary;
  className?: string;
}

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

export const CounterGroupCard = ({ group, className }: CounterGroupCardProps) => {
  const gp = useCommunityPath();

  return (
    <Link
      to={gp(toolDetailRoute(Tool.counter_group, group.initiative_id, group.id))}
      className={cn(
        "group block w-full overflow-hidden rounded-2xl border bg-card text-card-foreground shadow-sm transition hover:-translate-y-0.5 hover:border-primary/50 hover:shadow-lg",
        className
      )}
    >
      {group.preview?.length ? <CounterGroupPreview counters={group.preview} /> : null}
      <Card className="border-0 shadow-none">
        {/* With nothing above it, the header stops short of the bookmark the list
            puts on the card's corner. */}
        <CardHeader className={cn("pb-2", !group.preview?.length && "pr-14")}>
          <div className="flex items-start justify-between gap-2">
            <CardTitle className="line-clamp-1 text-lg leading-tight">{group.name}</CardTitle>
          </div>
          {group.description && (
            <p className="line-clamp-2 text-muted-foreground text-sm">{group.description}</p>
          )}
        </CardHeader>
        <CardContent className="space-y-2 pt-0">
          <TagBadgeList tags={group.tags} tagHref={(tag) => gp(`/tags/${tag.id}`)} nested />
        </CardContent>
      </Card>
    </Link>
  );
};
