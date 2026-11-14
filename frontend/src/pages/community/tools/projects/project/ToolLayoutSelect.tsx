import type { LucideIcon } from "lucide-react";

import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/ui/select";

export type LayoutOption = { slug: string; name: string; icon: LucideIcon };

type ToolLayoutSelectProps = {
  layouts: readonly LayoutOption[];
  /** The layout shown. */
  activeSlug: string | null;
  /** This person narrows the list on screen. */
  modified: boolean;
  onSelect: (slug: string) => void;
  label: string;
  modifiedLabel: string;
};

/**
 * Which of a list's layouts it is showing. The presets a layout offers lead
 * its filter panel instead (`ToolPresetSelect`).
 *
 * Tool-agnostic: it knows about slugs, names and icons, not about tasks.
 */
export const ToolLayoutSelect = ({
  layouts,
  activeSlug,
  modified,
  onSelect,
  label,
  modifiedLabel,
}: ToolLayoutSelectProps) => {
  const active = layouts.find((layout) => layout.slug === activeSlug) ?? null;
  const ActiveIcon = active?.icon;

  return (
    <Select value={activeSlug ?? ""} onValueChange={onSelect}>
      <SelectTrigger aria-label={label} className="h-9 w-auto max-w-64 gap-2">
        {/* The trigger carries the "modified" marker, not the list: each
            entry there is a layout as it is kept. */}
        <SelectValue>
          {active ? (
            <span className="flex min-w-0 items-center gap-2">
              {ActiveIcon ? <ActiveIcon className="h-4 w-4 shrink-0" /> : null}
              <span className="truncate">
                {active.name}
                {modified ? ` · ${modifiedLabel}` : ""}
              </span>
            </span>
          ) : null}
        </SelectValue>
      </SelectTrigger>
      <SelectContent>
        {layouts.map(({ slug, name, icon: Icon }) => (
          <SelectItem key={slug} value={slug}>
            <span className="flex items-center gap-2">
              <Icon className="h-4 w-4 shrink-0" />
              {name}
            </span>
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
};
