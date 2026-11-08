import {
  ColorPicker,
  ColorPickerAlpha,
  ColorPickerEyeDropper,
  ColorPickerFormat,
  ColorPickerHue,
  ColorPickerOutput,
  ColorPickerSelection,
} from "@/ui/shadcn-io/color-picker";

interface EditorColorPickerContentProps {
  defaultValue: string;
  onChange: (rgba: number[]) => void;
}

export default function EditorColorPickerContent({
  defaultValue,
  onChange,
}: EditorColorPickerContentProps) {
  return (
    <ColorPicker defaultValue={defaultValue} onChange={onChange}>
      <div className="space-y-3">
        <ColorPickerSelection className="h-48 w-full rounded-md border" />
        <div className="flex items-center gap-2">
          <ColorPickerEyeDropper />
          <div className="flex flex-1 flex-col gap-2">
            <ColorPickerHue />
            <ColorPickerAlpha />
          </div>
        </div>
        <div className="flex items-center gap-2">
          <ColorPickerOutput />
          <ColorPickerFormat className="w-full" />
        </div>
      </div>
    </ColorPicker>
  );
}
