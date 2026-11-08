import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { Button } from "@/ui/button";
import { cn } from "@/ui/lib/utils";
import { Popover, PopoverContent, PopoverTrigger } from "@/ui/popover";
import {
  ColorPicker,
  ColorPickerAlpha,
  ColorPickerEyeDropper,
  ColorPickerFormat,
  ColorPickerHue,
  ColorPickerOutput,
  ColorPickerSelection,
} from "@/ui/shadcn-io/color-picker";

const rgbaToHex = (rgba: number[]) => {
  const clamp = (value: number) => Math.max(0, Math.min(255, Math.round(value)));
  // The shadcn-io ColorPicker emits [r, g, b, alpha] where alpha is 0–1.
  const [r = 0, g = 0, b = 0, a = 1] = rgba;
  const hexRgb = [clamp(r), clamp(g), clamp(b)]
    .map((channel) => channel.toString(16).padStart(2, "0"))
    .join("")
    .toUpperCase();
  // Keep fully-opaque colors in the shorter #RRGGBB form so existing callers
  // that only handle 7-char hex don't suddenly see 9 chars. Append the alpha
  // byte only when the user has actually used the alpha slider.
  if (a >= 0.999) {
    return `#${hexRgb}`;
  }
  const hexAlpha = clamp(a * 255)
    .toString(16)
    .padStart(2, "0")
    .toUpperCase();
  return `#${hexRgb}${hexAlpha}`;
};

interface ColorPickerPopoverProps {
  id?: string;
  value: string;
  onChange?: (value: string) => void;
  onChangeComplete?: (value: string) => void;
  disabled?: boolean;
  triggerLabel?: string;
  className?: string;
}

export const ColorPickerPopover = ({
  id,
  value,
  onChange,
  onChangeComplete,
  disabled,
  triggerLabel = "Pick color",
  className,
}: ColorPickerPopoverProps) => {
  const [open, setOpen] = useState(false);
  const [draftColor, setDraftColor] = useState(value);

  // Stash the latest callbacks in refs so handleColorChange/handleOpenChange can
  // stay referentially stable regardless of whether callers memoize their props.
  // If handleColorChange churned every render, the shadcn-io ColorPicker's
  // "notify parent" effect would re-fire on every render and infinite-loop any
  // controlled caller whose onChange isn't a stable reference.
  const onChangeRef = useRef(onChange);
  const onChangeCompleteRef = useRef(onChangeComplete);
  useEffect(() => {
    onChangeRef.current = onChange;
    onChangeCompleteRef.current = onChangeComplete;
  });

  // What the picker was last opened on — the colour a commit is measured
  // against. It cannot be `value`: a caller that previews live moves its own
  // state from `onChange`, so by the time the popover closes `value` has
  // already caught up with the draft, and comparing the two would say nothing
  // changed and never commit. While the popover is closed the two are the same
  // thing, so this also follows a colour changed from elsewhere.
  const committedRef = useRef(value);

  useEffect(() => {
    if (!open) {
      setDraftColor(value);
      committedRef.current = value;
    }
  }, [open, value]);

  const handleColorChange = useCallback((rgba: number[]) => {
    const nextColor = rgbaToHex(rgba);
    setDraftColor(nextColor);
    onChangeRef.current?.(nextColor);
  }, []);

  const handleOpenChange = useCallback(
    (nextOpen: boolean) => {
      if (!nextOpen && draftColor !== committedRef.current) {
        committedRef.current = draftColor;
        onChangeCompleteRef.current?.(draftColor);
      }
      setOpen(nextOpen);
    },
    [draftColor]
  );

  const swatchStyle = useMemo(() => ({ backgroundColor: draftColor }), [draftColor]);

  return (
    <Popover open={open} onOpenChange={handleOpenChange}>
      <PopoverTrigger asChild>
        <Button
          id={id}
          type="button"
          variant="outline"
          className={cn(
            "h-11 w-full justify-between gap-3 font-mono text-xs uppercase tracking-wide",
            className
          )}
          disabled={disabled}
          aria-label={triggerLabel}
        >
          <span className="flex items-center gap-2">
            <span aria-hidden="true" className="h-6 w-6 rounded-md border" style={swatchStyle} />
            {draftColor}
          </span>
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-80 space-y-3" align="start">
        <ColorPicker value={draftColor} onChange={handleColorChange}>
          <div className="space-y-3">
            <div className="flex items-center gap-2">
              <div className="flex-1 rounded-md border px-3 py-2 font-mono text-xs">
                {draftColor}
              </div>
              <ColorPickerOutput />
              <ColorPickerEyeDropper />
            </div>
            <ColorPickerSelection className="h-48 w-full rounded-md border" />
            <ColorPickerHue />
            <ColorPickerAlpha />
            <ColorPickerFormat className="w-full" />
          </div>
        </ColorPicker>
      </PopoverContent>
    </Popover>
  );
};
