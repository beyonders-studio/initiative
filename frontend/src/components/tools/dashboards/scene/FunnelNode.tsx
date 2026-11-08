import { formatValue } from "@/lib/widgets/format";
import type { SceneNode } from "@/lib/widgets/sceneSpec";
import { toneColor } from "@/lib/widgets/tone";

type Node = Extract<SceneNode, { kind: "funnel" }>;

/**
 * Staged counts as narrowing bars.
 *
 * Drawn with plain divs rather than a chart library: a funnel is a list of
 * proportional widths, and the conversion percentages are the part people
 * actually read.
 *
 * Stages take an *ordered* scale, not categorical colors — one hue deepening
 * along the sequence. Funnel stages are steps of one process, and giving each
 * its own hue would claim they are unrelated identities. A stage that names its
 * own tone still gets it; that is how a widget marks one step as the problem.
 */
export function FunnelNode({ node }: { node: Node }) {
  // Measured against the largest stage rather than the first. A funnel usually
  // narrows, and for one that does these are the same number — but nothing
  // makes the data narrow. A statement grouping by status returns its rows in
  // whatever order it likes, so "the first" is not "the widest", and scaling
  // against it drew every larger stage past the end of the panel.
  const top = node.stages.reduce((widest, stage) => Math.max(widest, stage.value), 0);

  return (
    <div className="flex h-full w-full flex-col justify-center gap-1.5 p-1">
      {node.stages.map((stage, index) => {
        // Floored so the smallest stage is still a mark, capped because a bar
        // is drawn inside a box — the same bounds every other proportional
        // fill on a dashboard is held to.
        const width = top > 0 ? Math.min(1, Math.max(0.04, stage.value / top)) : 1;
        const previous = node.stages[index - 1]?.value;
        const conversion = previous && previous > 0 ? stage.value / previous : undefined;

        return (
          <div
            // biome-ignore lint/suspicious/noArrayIndexKey: stage labels may legally repeat, so position is the only stable identity a stage has
            key={`${stage.label}-${index}`}
            className="flex flex-col gap-0.5"
          >
            <div className="flex items-baseline justify-between gap-2 text-xs">
              <span className="truncate font-medium">{stage.label}</span>
              <span className="shrink-0 text-muted-foreground tabular-nums">
                {formatValue(stage.value, node.format)}
                {conversion !== undefined && (
                  <span className="ml-1.5">{formatValue(conversion, "percent")}</span>
                )}
              </span>
            </div>
            <div
              className="h-4 rounded-sm transition-[width]"
              style={{
                width: `${width * 100}%`,
                backgroundColor: toneColor(stage.tone ?? "accent"),
                // The ramp: each step a little deeper than the one above it,
                // floored so the last stage never fades to nothing.
                opacity: stage.tone
                  ? 1
                  : Math.max(0.45, 1 - index * (0.55 / Math.max(1, node.stages.length - 1))),
              }}
            />
          </div>
        );
      })}
    </div>
  );
}
