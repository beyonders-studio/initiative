"use client";

import * as Slider from "@radix-ui/react-slider";
import Color from "color";
import { PipetteIcon } from "lucide-react";
import {
  type ComponentProps,
  createContext,
  type HTMLAttributes,
  memo,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/ui/button";
import { Input } from "@/ui/input";
import { cn } from "@/ui/lib/utils";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/ui/select";

type ColorInput = Parameters<typeof Color>[0];

interface Hsla {
  hue: number;
  saturation: number;
  lightness: number;
  alpha: number;
}

interface ColorPickerContextValue extends Hsla {
  /** Without transparency: no alpha slider, and every colour is opaque. */
  opaque: boolean;
  mode: string;
  setMode: (mode: string) => void;
  /** Move to a colour the person chose, and tell the picker's caller. */
  update: (next: Partial<Hsla>) => void;
}

const ColorPickerContext = createContext<ColorPickerContextValue | undefined>(undefined);

const useColorPicker = () => {
  const context = useContext(ColorPickerContext);

  if (!context) {
    throw new Error("useColorPicker must be used within a ColorPickerProvider");
  }

  return context;
};

/**
 * The first of these the colour actually has.
 *
 * Zero is a real saturation and a real lightness — black is 0,0,0 and grey is
 * saturation 0 — so a falsy check here reads black as "unset" and opens the
 * picker on red instead, and a caller that previews live then feeds that red
 * straight back in as the value.
 */
const channel = (...values: number[]) => values.find(Number.isFinite) ?? 0;

const hslaOf = (value: ColorInput, fallback: ColorInput = "#000000"): Hsla => {
  const color = Color(value);
  const backup = Color(fallback);
  return {
    hue: channel(color.hue(), backup.hue(), 0),
    saturation: channel(color.saturationl(), backup.saturationl(), 100),
    lightness: channel(color.lightness(), backup.lightness(), 50),
    alpha: channel(color.alpha() * 100, backup.alpha() * 100, 100),
  };
};

const colorOf = ({ hue, saturation, lightness, alpha }: Hsla) =>
  Color.hsl(hue, saturation, lightness).alpha(alpha / 100);

/** Whether a colour handed in is the one on screen: what the picker reported
 *  comes back as its value, and reading it back would round the hue and move
 *  the cursor. */
const showing = (value: ColorInput, hsla: Hsla) => {
  try {
    return Color(value).hexa() === colorOf(hsla).hexa();
  } catch {
    return true;
  }
};

type ColorPickerProps = Omit<HTMLAttributes<HTMLDivElement>, "onChange"> & {
  value?: ColorInput;
  defaultValue?: ColorInput;
  opaque?: boolean;
  /** Each colour the person moves to, as [r, g, b, alpha 0–1]. Only their own
   *  changes: a value handed in is never reported back. */
  onChange?: (value: number[]) => void;
};

const ColorPicker = ({
  value,
  defaultValue = "#000000",
  opaque = false,
  onChange,
  className,
  ...props
}: ColorPickerProps) => {
  const [hsla, setHsla] = useState(() => hslaOf(value ?? defaultValue, defaultValue));
  const [mode, setMode] = useState("hex");

  // A colour handed in from outside replaces the one on screen, unless it is
  // the one on screen.
  const [prevValue, setPrevValue] = useState(value);
  if (prevValue !== value) {
    setPrevValue(value);
    if (value && !showing(value, hsla)) setHsla(hslaOf(value, defaultValue));
  }

  // Several moves can land between renders (a drag reports every pointer
  // event), so each builds on the last one rather than on the last render.
  const latest = useRef(hsla);
  latest.current = hsla;
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;

  const update = useCallback(
    (next: Partial<Hsla>) => {
      const moved = { ...latest.current, ...next, ...(opaque ? { alpha: 100 } : null) };
      latest.current = moved;
      setHsla(moved);
      const [red, green, blue] = colorOf(moved).rgb().array();
      onChangeRef.current?.([red, green, blue, moved.alpha / 100]);
    },
    [opaque]
  );

  return (
    <ColorPickerContext.Provider value={{ ...hsla, opaque, mode, setMode, update }}>
      <div className={cn("flex size-full flex-col gap-4", className)} {...props} />
    </ColorPickerContext.Provider>
  );
};

type ColorPickerSelectionProps = HTMLAttributes<HTMLDivElement>;

const ColorPickerSelection = memo(({ className, ...props }: ColorPickerSelectionProps) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const [isDragging, setIsDragging] = useState(false);
  const { hue, saturation, lightness, update } = useColorPicker();

  // The field paints saturation across and brightness down (HSV), so the
  // cursor is the colour read the same way: it starts on the colour shown.
  const [, fieldSaturation, brightness] = Color.hsl(hue, saturation, lightness).hsv().array();
  const x = fieldSaturation / 100;
  const y = 1 - brightness / 100;

  const handlePointerMove = useCallback(
    (event: PointerEvent) => {
      if (!containerRef.current) {
        return;
      }
      const rect = containerRef.current.getBoundingClientRect();
      const nextX = Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width));
      const nextY = Math.max(0, Math.min(1, (event.clientY - rect.top) / rect.height));
      // The colour painted under the pointer, in the picker's HSL.
      const [, nextSaturation, nextLightness] = Color.hsv(hue, nextX * 100, (1 - nextY) * 100)
        .hsl()
        .array();
      update({ saturation: nextSaturation, lightness: nextLightness });
    },
    [hue, update]
  );

  useEffect(() => {
    const handlePointerUp = () => setIsDragging(false);

    if (isDragging) {
      window.addEventListener("pointermove", handlePointerMove);
      window.addEventListener("pointerup", handlePointerUp);
    }

    return () => {
      window.removeEventListener("pointermove", handlePointerMove);
      window.removeEventListener("pointerup", handlePointerUp);
    };
  }, [isDragging, handlePointerMove]);

  return (
    <div
      className={cn("relative size-full cursor-crosshair rounded", className)}
      onPointerDown={(e) => {
        e.preventDefault();
        setIsDragging(true);
        handlePointerMove(e.nativeEvent);
      }}
      ref={containerRef}
      style={{
        background: `linear-gradient(0deg, rgba(0,0,0,1), rgba(0,0,0,0)),
            linear-gradient(90deg, rgba(255,255,255,1), rgba(255,255,255,0)),
            hsl(${hue}, 100%, 50%)`,
      }}
      {...props}
    >
      <div
        className="pointer-events-none absolute h-4 w-4 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-white"
        style={{
          left: `${x * 100}%`,
          top: `${y * 100}%`,
          boxShadow: "0 0 0 1px rgba(0,0,0,0.5)",
        }}
      />
    </div>
  );
});
ColorPickerSelection.displayName = "ColorPickerSelection";

type ColorPickerHueProps = ComponentProps<typeof Slider.Root>;

const ColorPickerHue = ({ className, ...props }: ColorPickerHueProps) => {
  const { hue, update } = useColorPicker();

  return (
    <Slider.Root
      className={cn("relative flex h-4 w-full touch-none", className)}
      max={360}
      onValueChange={([next]) => update({ hue: next })}
      step={1}
      value={[hue]}
      {...props}
    >
      <Slider.Track className="relative my-0.5 h-3 w-full grow rounded-full bg-[linear-gradient(90deg,#FF0000,#FFFF00,#00FF00,#00FFFF,#0000FF,#FF00FF,#FF0000)]">
        <Slider.Range className="absolute h-full" />
      </Slider.Track>
      <Slider.Thumb className="block h-4 w-4 rounded-full border border-primary/50 bg-background shadow transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50" />
    </Slider.Root>
  );
};

type ColorPickerAlphaProps = ComponentProps<typeof Slider.Root>;

const ColorPickerAlpha = ({ className, ...props }: ColorPickerAlphaProps) => {
  const { alpha, update } = useColorPicker();

  return (
    <Slider.Root
      className={cn("relative flex h-4 w-full touch-none", className)}
      max={100}
      onValueChange={([next]) => update({ alpha: next })}
      step={1}
      value={[alpha]}
      {...props}
    >
      <Slider.Track
        className="relative my-0.5 h-3 w-full grow rounded-full"
        style={{
          background:
            'url("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAYAAAAf8/9hAAAAMUlEQVQ4T2NkYGAQYcAP3uCTZhw1gGGYhAGBZIA/nYDCgBDAm9BGDWAAJyRCgLaBCAAgXwixzAS0pgAAAABJRU5ErkJggg==") left center',
        }}
      >
        <div className="absolute inset-0 rounded-full bg-gradient-to-r from-transparent to-black/50" />
        <Slider.Range className="absolute h-full rounded-full bg-transparent" />
      </Slider.Track>
      <Slider.Thumb className="block h-4 w-4 rounded-full border border-primary/50 bg-background shadow transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50" />
    </Slider.Root>
  );
};

type ColorPickerEyeDropperProps = ComponentProps<typeof Button>;

const ColorPickerEyeDropper = ({ className, ...props }: ColorPickerEyeDropperProps) => {
  const { update } = useColorPicker();

  const handleEyeDropper = async () => {
    try {
      // @ts-expect-error - EyeDropper API is experimental
      const eyeDropper = new EyeDropper();
      const result = await eyeDropper.open();
      update({ ...hslaOf(result.sRGBHex), alpha: 100 });
    } catch (error) {
      console.error("EyeDropper failed:", error);
    }
  };

  return (
    <Button
      className={cn("shrink-0 text-muted-foreground", className)}
      onClick={handleEyeDropper}
      size="icon"
      variant="outline"
      type="button"
      {...props}
    >
      <PipetteIcon size={16} />
    </Button>
  );
};

type ColorPickerOutputProps = ComponentProps<typeof SelectTrigger>;

const formats = ["hex", "rgb", "css", "hsl"];

const ColorPickerOutput = ({ className, ...props }: ColorPickerOutputProps) => {
  const { t } = useTranslation("ui");
  const { mode, setMode } = useColorPicker();

  return (
    <Select onValueChange={setMode} value={mode}>
      <SelectTrigger className={cn("h-8 w-20 shrink-0 text-xs", className)} {...props}>
        <SelectValue placeholder={t("colorPicker.mode")} />
      </SelectTrigger>
      <SelectContent>
        {formats.map((format) => (
          <SelectItem className="text-xs" key={format} value={format}>
            {format.toUpperCase()}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
};

type PercentageInputProps = ComponentProps<typeof Input>;

const PercentageInput = ({ className, ...props }: PercentageInputProps) => {
  return (
    <div className="relative">
      <Input
        readOnly
        type="text"
        {...props}
        className={cn(
          "h-8 w-[3.25rem] rounded-l-none bg-secondary px-2 text-xs shadow-none",
          className
        )}
      />
      <span className="absolute top-1/2 right-2 -translate-y-1/2 text-muted-foreground text-xs">
        %
      </span>
    </div>
  );
};

type ColorPickerFormatProps = HTMLAttributes<HTMLDivElement>;

const normalizeHex = (value: string) => {
  const trimmed = value.trim().replace(/^#/, "");
  if (trimmed.length !== 6 || /[^0-9a-f]/i.test(trimmed)) {
    return null;
  }
  return `#${trimmed.toUpperCase()}`;
};

const ColorPickerFormat = ({ className, ...props }: ColorPickerFormatProps) => {
  const { hue, saturation, lightness, alpha, opaque, mode, update } = useColorPicker();
  const color = colorOf({ hue, saturation, lightness, alpha });
  const hexValue = color.hex();
  const [hexInput, setHexInput] = useState(hexValue);
  const [prevHexValue, setPrevHexValue] = useState(hexValue);
  if (prevHexValue !== hexValue) {
    setPrevHexValue(hexValue);
    setHexInput(hexValue);
  }
  // The share of the colour that shows, beside its channels; nothing to say
  // for a picker without transparency.
  const shown = opaque ? null : <PercentageInput value={alpha} />;

  if (mode === "hex") {
    return (
      <div
        className={cn(
          "relative flex w-full items-center -space-x-px rounded-md shadow-sm",
          className
        )}
        {...props}
      >
        <Input
          className={cn("h-8 bg-secondary px-2 text-xs shadow-none", !opaque && "rounded-r-none")}
          type="text"
          value={hexInput}
          onChange={(event) => setHexInput(event.target.value)}
          onBlur={() => {
            const normalized = normalizeHex(hexInput);
            if (normalized) {
              update(hslaOf(normalized));
            } else {
              setHexInput(color.hex());
            }
          }}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.currentTarget.blur();
            }
            if (event.key === "Escape") {
              setHexInput(color.hex());
              event.currentTarget.blur();
            }
          }}
        />
        {shown}
      </div>
    );
  }

  if (mode === "rgb") {
    const rgb = color
      .rgb()
      .array()
      .map((value) => Math.round(value));

    return (
      <div
        className={cn("flex items-center -space-x-px rounded-md shadow-sm", className)}
        {...props}
      >
        {rgb.map((value, index) => (
          <Input
            className={cn(
              "h-8 rounded-r-none bg-secondary px-2 text-xs shadow-none",
              index && "rounded-l-none",
              className
            )}
            key={index}
            readOnly
            type="text"
            value={value}
          />
        ))}
        {shown}
      </div>
    );
  }

  if (mode === "css") {
    const rgb = color
      .rgb()
      .array()
      .map((value) => Math.round(value));

    return (
      <div className={cn("w-full rounded-md shadow-sm", className)} {...props}>
        <Input
          className="h-8 w-full bg-secondary px-2 text-xs shadow-none"
          readOnly
          type="text"
          value={opaque ? `rgb(${rgb.join(", ")})` : `rgba(${rgb.join(", ")}, ${alpha}%)`}
          {...props}
        />
      </div>
    );
  }

  if (mode === "hsl") {
    const hsl = color
      .hsl()
      .array()
      .map((value) => Math.round(value));

    return (
      <div
        className={cn("flex items-center -space-x-px rounded-md shadow-sm", className)}
        {...props}
      >
        {hsl.map((value, index) => (
          <Input
            className={cn(
              "h-8 rounded-r-none bg-secondary px-2 text-xs shadow-none",
              index && "rounded-l-none",
              className
            )}
            key={index}
            readOnly
            type="text"
            value={value}
          />
        ))}
        {shown}
      </div>
    );
  }

  return null;
};

/**
 * The whole picker: the colour's value, the field, hue (and transparency,
 * unless it is opaque), the eyedropper and the value in each format.
 * `ColorPickerPopover` loads it when it first opens.
 */
export const ColorPickerPanel = ({
  value,
  opaque,
  onChange,
}: {
  value: string;
  opaque?: boolean;
  onChange: (rgba: number[]) => void;
}) => (
  <ColorPicker value={value} opaque={opaque} onChange={onChange}>
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <div className="flex-1 rounded-md border px-3 py-2 font-mono text-xs">{value}</div>
        <ColorPickerOutput />
        <ColorPickerEyeDropper />
      </div>
      <ColorPickerSelection className="h-48 w-full rounded-md border" />
      <ColorPickerHue />
      {opaque ? null : <ColorPickerAlpha />}
      <ColorPickerFormat className="w-full" />
    </div>
  </ColorPicker>
);
