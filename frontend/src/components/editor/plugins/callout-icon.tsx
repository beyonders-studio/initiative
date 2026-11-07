import { CircleCheck, Info, Lightbulb, OctagonX, Pencil, TriangleAlert } from "lucide-react";

import type { CalloutVariant } from "@/components/editor/nodes/callout-node";

const ICONS = {
  info: Info,
  note: Pencil,
  tip: Lightbulb,
  success: CircleCheck,
  warning: TriangleAlert,
  error: OctagonX,
} as const;

/** The mark each kind of callout carries — the same one the editor draws
 * inside the callout itself. */
export function CalloutIcon({
  variant,
  className,
}: {
  variant: CalloutVariant;
  className?: string;
}) {
  const Icon = ICONS[variant];
  return <Icon className={className} aria-hidden="true" />;
}
