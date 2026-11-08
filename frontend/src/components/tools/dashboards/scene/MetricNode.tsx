import { TrendingDown, TrendingUp } from "lucide-react";

import { formatValue } from "@/lib/widgets/format";
import type { SceneNode } from "@/lib/widgets/sceneSpec";
import { toneTextClass } from "@/lib/widgets/tone";
import { cn } from "@/ui/lib/utils";

type Node = Extract<SceneNode, { kind: "metric" }>;

/** Whether a movement should read as good news. A widget says which direction
 *  it wants treated as positive, because falling cycle time and falling revenue
 *  are the same arrow with opposite meanings. */
const deltaTone = (delta: number, good: Node["deltaGood"]) => {
  if (delta === 0) return toneTextClass("muted");
  const rising = delta > 0;
  const isGood = good === "down" ? !rising : rising;
  return toneTextClass(isGood ? "positive" : "negative");
};

export function MetricNode({ node }: { node: Node }) {
  const Arrow = (node.delta ?? 0) >= 0 ? TrendingUp : TrendingDown;

  return (
    <div className="flex h-full w-full flex-col justify-center gap-1 p-1">
      {node.label && (
        <p className="truncate text-muted-foreground text-xs uppercase tracking-wide">
          {node.label}
        </p>
      )}
      {/* Proportional figures, not tabular: equal-width digits make a number
          like 121 look loose at display size. Tabular belongs in columns. */}
      <p className={cn("truncate font-bold text-3xl", toneTextClass(node.tone))}>
        {formatValue(node.value, node.format)}
      </p>
      <div className="flex items-center gap-2">
        {node.delta !== undefined && (
          <span
            className={cn(
              "flex items-center gap-0.5 font-medium text-xs tabular-nums",
              deltaTone(node.delta, node.deltaGood)
            )}
          >
            <Arrow className="h-3 w-3" aria-hidden />
            {formatValue(Math.abs(node.delta), "percent")}
          </span>
        )}
        {node.caption && (
          <span className="truncate text-muted-foreground text-xs">{node.caption}</span>
        )}
      </div>
    </div>
  );
}
