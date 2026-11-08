import { lazy, type ReactNode, Suspense, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { useFieldControl } from "@/ui/field";
import { fieldClass } from "@/ui/input";
import { cn } from "@/ui/lib/utils";
import { Popover, PopoverContent, PopoverTrigger } from "@/ui/popover";

// The picker's field and sliders load when one first opens.
const ColorPickerPanel = lazy(() =>
  import("@/ui/shadcn-io/color-picker").then((module) => ({ default: module.ColorPickerPanel }))
);

const rgbaToHex = (rgba: number[]) => {
  const clamp = (value: number) => Math.max(0, Math.min(255, Math.round(value)));
  // The picker reports [r, g, b, alpha] where alpha is 0–1.
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
  /** Each colour as the person moves through them, for a live preview. */
  onChange?: (value: string) => void;
  /** The colour they settled on, once, when the picker closes. */
  onChangeComplete?: (value: string) => void;
  disabled?: boolean;
  /** What the control that opens the picker is called. */
  triggerLabel?: string;
  className?: string;
  /** A control of the caller's own that opens the picker, such as a toolbar
   *  button, in place of the swatch and value; it is named by `triggerLabel`. */
  children?: ReactNode;
  /** Told when the picker opens and closes, after the colour is committed. */
  onOpenChange?: (open: boolean) => void;
  /** Keeps the rest of the page inert while the picker is open. */
  modal?: boolean;
  /** Without transparency: every colour is #RRGGBB. */
  opaque?: boolean;
}

/** The app's one colour picker: a swatch, or a control of the caller's own,
 *  opening the full picker. */
export const ColorPickerPopover = ({
  id,
  value,
  onChange,
  onChangeComplete,
  disabled,
  triggerLabel,
  className,
  children,
  onOpenChange,
  modal,
  opaque,
}: ColorPickerPopoverProps) => {
  const { t } = useTranslation("ui");
  const field = useFieldControl({ id });
  const [open, setOpen] = useState(false);
  const [draftColor, setDraftColor] = useState(value);
  // What the picker opened on: the colour a commit is measured against. Not
  // `value` at closing time, because a caller previewing live has moved its
  // own value with every change by then.
  const opened = useRef(value);

  const handleOpenChange = (nextOpen: boolean) => {
    if (nextOpen) {
      opened.current = value;
      setDraftColor(value);
    } else if (draftColor !== opened.current) {
      opened.current = draftColor;
      onChangeComplete?.(draftColor);
    }
    setOpen(nextOpen);
    onOpenChange?.(nextOpen);
  };

  const handleColorChange = (rgba: number[]) => {
    const nextColor = rgbaToHex(rgba);
    setDraftColor(nextColor);
    onChange?.(nextColor);
  };

  // Closed, it shows the caller's colour; open, the one being chosen.
  const shown = open ? draftColor : value;

  return (
    <Popover open={open} onOpenChange={handleOpenChange} modal={modal}>
      <PopoverTrigger asChild aria-label={triggerLabel ?? t("colorPicker.pick")}>
        {children ?? (
          <button
            type="button"
            {...field}
            className={cn(fieldClass, "items-center gap-2 font-mono uppercase", className)}
            disabled={disabled}
          >
            <span
              aria-hidden="true"
              className="h-6 w-6 shrink-0 rounded-md border"
              style={{ backgroundColor: shown }}
            />
            {shown}
          </button>
        )}
      </PopoverTrigger>
      <PopoverContent className="w-80 space-y-3" align="start">
        <Suspense fallback={<div className="h-[280px] w-full" />}>
          <ColorPickerPanel value={draftColor} opaque={opaque} onChange={handleColorChange} />
        </Suspense>
      </PopoverContent>
    </Popover>
  );
};
