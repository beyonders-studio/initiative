/**
 * The trusted renderer.
 *
 * This is the only code that turns widget output into DOM, and it accepts
 * exactly one input shape: a `SceneNode` that has already been through
 * `validateScene`. Everything it draws is a value mapped onto a prop — no node
 * carries markup, a URL, or a handler, so there is nothing here that could
 * execute what a widget sent. Strings arrive as React children and are escaped
 * on the way out.
 *
 * The dispatch below is deliberately total: every node kind in the vocabulary
 * has a component, and the default arm renders nothing rather than guessing.
 */

import { memo } from "react";

import type { SceneNode } from "@/lib/widgets/sceneSpec";
import { toneTextClass } from "@/lib/widgets/tone";
import { cn } from "@/ui/lib/utils";

import { BoardNode } from "./BoardNode";
import { FunnelNode } from "./FunnelNode";
import { MatrixNode } from "./MatrixNode";
import { MetricNode } from "./MetricNode";
import { ProgressNode } from "./ProgressNode";
import { SeriesNode } from "./SeriesNode";
import { TableNode } from "./TableNode";
import { TimelineNode } from "./TimelineNode";

export interface SceneNodeProps<T extends SceneNode = SceneNode> {
  node: T;
}

const GAP_CLASSES = { none: "gap-0", sm: "gap-2", md: "gap-4" } as const;

function StackNode({ node }: SceneNodeProps<Extract<SceneNode, { kind: "stack" }>>) {
  return (
    <div
      className={cn(
        "flex h-full w-full min-w-0",
        node.direction === "row" ? "flex-row" : "flex-col",
        GAP_CLASSES[node.gap ?? "md"]
      )}
    >
      {node.children.map((child, index) => (
        <div
          // biome-ignore lint/suspicious/noArrayIndexKey: scene nodes carry no identity of their own and a stack's children are positional, so the index is the identity rather than a stand-in for one
          key={index}
          className="min-h-0 min-w-0"
          style={{ flex: node.weights?.[index] ?? 1 }}
        >
          <SceneRenderer node={child} />
        </div>
      ))}
    </div>
  );
}

const TEXT_CLASSES = {
  heading: "font-semibold text-lg",
  body: "text-sm",
  caption: "text-muted-foreground text-xs",
} as const;

function TextNode({ node }: SceneNodeProps<Extract<SceneNode, { kind: "text" }>>) {
  return (
    <p className={cn(TEXT_CLASSES[node.variant ?? "body"], toneTextClass(node.tone))}>
      {node.text}
    </p>
  );
}

function EmptyNode({ node }: SceneNodeProps<Extract<SceneNode, { kind: "empty" }>>) {
  return (
    <div className="flex h-full w-full items-center justify-center p-4 text-center">
      <p className="text-muted-foreground text-sm">{node.message}</p>
    </div>
  );
}

export const SceneRenderer = memo(function SceneRenderer({ node }: SceneNodeProps) {
  switch (node.kind) {
    case "metric":
      return <MetricNode node={node} />;
    case "series":
      return <SeriesNode node={node} />;
    case "timeline":
      return <TimelineNode node={node} />;
    case "funnel":
      return <FunnelNode node={node} />;
    case "progress":
      return <ProgressNode node={node} />;
    case "matrix":
      return <MatrixNode node={node} />;
    case "table":
      return <TableNode node={node} />;
    case "board":
      return <BoardNode node={node} />;
    case "text":
      return <TextNode node={node} />;
    case "empty":
      return <EmptyNode node={node} />;
    case "stack":
      return <StackNode node={node} />;
    default:
      return null;
  }
});
