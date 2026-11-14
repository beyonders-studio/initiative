import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/ui/select";

export type PresetOption = { slug: string; name: string };

type ToolPresetSelectProps = {
  presets: readonly PresetOption[];
  /** The preset the filters below are still showing, or null once they are
   *  this person's own. */
  activeSlug: string | null;
  onSelect: (slug: string) => void;
  label: string;
  /** Shown while no preset is. */
  placeholder: string;
};

/**
 * The presets a list offers to start from. It leads the filter panel's control
 * row, because picking one sets every field below it; the layout stays.
 *
 * Tool-agnostic: it knows about slugs and names, not about tasks.
 */
export const ToolPresetSelect = ({
  presets,
  activeSlug,
  onSelect,
  label,
  placeholder,
}: ToolPresetSelectProps) => (
  // "" while none is showing, so the placeholder does, and a preset the
  // person moved away from can be picked again.
  <Select value={activeSlug ?? ""} onValueChange={onSelect}>
    <SelectTrigger aria-label={label} className="h-9 w-full sm:w-56">
      <SelectValue placeholder={placeholder} />
    </SelectTrigger>
    <SelectContent>
      {presets.map(({ slug, name }) => (
        <SelectItem key={slug} value={slug}>
          {name}
        </SelectItem>
      ))}
    </SelectContent>
  </Select>
);
