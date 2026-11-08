import { $getSelectionStyleValueForProperty, $patchStyleText } from "@lexical/selection";
import {
  $getSelection,
  $isRangeSelection,
  $setSelection,
  type BaseSelection,
  type RangeSelection,
} from "lexical";
import { PaintBucketIcon } from "lucide-react";
import { lazy, Suspense, useCallback, useRef, useState } from "react";

import { useToolbarContext } from "@/components/editor/context/toolbar-context";
import { useUpdateToolbarHandler } from "@/components/editor/editor-hooks/use-update-toolbar";
import { Button } from "@/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/ui/popover";

const EditorColorPickerContent = lazy(() => import("./editor-color-picker-content"));

const rgbaToHex = (rgba: number[]) => {
  const clamp = (value: number) => Math.max(0, Math.min(255, Math.round(value)));
  const [r = 0, g = 0, b = 0] = rgba;
  return (
    "#" +
    [clamp(r), clamp(g), clamp(b)]
      .map((channel) => channel.toString(16).padStart(2, "0"))
      .join("")
      .toUpperCase()
  );
};

export function FontBackgroundToolbarPlugin() {
  const { activeEditor } = useToolbarContext();

  const [bgColor, setBgColor] = useState("#fff");
  const savedSelectionRef = useRef<RangeSelection | null>(null);
  const draftRef = useRef(bgColor);
  const skipMountRef = useRef(false);
  const hasChangedRef = useRef(false);

  const $updateToolbar = (selection: BaseSelection) => {
    if ($isRangeSelection(selection)) {
      setBgColor(
        $getSelectionStyleValueForProperty(selection, "background-color", "#fff") || "#fff"
      );
    }
  };

  useUpdateToolbarHandler($updateToolbar);

  const handleTriggerMouseDown = useCallback(() => {
    activeEditor.getEditorState().read(() => {
      const sel = $getSelection();
      if ($isRangeSelection(sel)) {
        savedSelectionRef.current = sel.clone();
      }
    });
  }, [activeEditor]);

  const handleColorChange = useCallback((rgba: number[]) => {
    if (skipMountRef.current) {
      skipMountRef.current = false;
      return;
    }
    draftRef.current = rgbaToHex(rgba);
    hasChangedRef.current = true;
  }, []);

  const handleOpenChange = useCallback(
    (open: boolean) => {
      if (open) {
        skipMountRef.current = true;
        draftRef.current = bgColor;
        hasChangedRef.current = false;
      } else {
        if (hasChangedRef.current && savedSelectionRef.current) {
          activeEditor.update(
            () => {
              $setSelection(savedSelectionRef.current!.clone());
              const selection = $getSelection();
              if (selection !== null) {
                $patchStyleText(selection, { "background-color": draftRef.current });
              }
            },
            { tag: "historic" }
          );
        }
        activeEditor.setEditable(true);
        activeEditor.focus();
      }
    },
    [activeEditor, bgColor]
  );

  return (
    <Popover modal onOpenChange={handleOpenChange}>
      <PopoverTrigger asChild>
        <Button variant="outline" size="icon-sm" onMouseDown={handleTriggerMouseDown}>
          <PaintBucketIcon className="size-4" />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-80 space-y-3" align="start">
        <Suspense fallback={<div className="h-[280px] w-full" />}>
          <EditorColorPickerContent defaultValue={bgColor} onChange={handleColorChange} />
        </Suspense>
      </PopoverContent>
    </Popover>
  );
}
