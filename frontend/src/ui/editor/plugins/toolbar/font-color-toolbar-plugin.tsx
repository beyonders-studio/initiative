import { $getSelectionStyleValueForProperty, $patchStyleText } from "@lexical/selection";
import {
  $getSelection,
  $isRangeSelection,
  $setSelection,
  type BaseSelection,
  type RangeSelection,
} from "lexical";
import { BaselineIcon } from "lucide-react";
import { useCallback, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/ui/button";
import { ColorPickerPopover } from "@/ui/color-picker-popover";
import { useToolbarContext } from "@/ui/editor/context/toolbar-context";
import { useUpdateToolbarHandler } from "@/ui/editor/editor-hooks/use-update-toolbar";

export function FontColorToolbarPlugin() {
  const { t } = useTranslation("editor");
  const { activeEditor } = useToolbarContext();

  const [fontColor, setFontColor] = useState("#000");
  const savedSelectionRef = useRef<RangeSelection | null>(null);

  const $updateToolbar = (selection: BaseSelection) => {
    if ($isRangeSelection(selection)) {
      setFontColor($getSelectionStyleValueForProperty(selection, "color", "#000") || "#000");
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

  // The colour lands on the text that was selected when the picker opened.
  const applyColor = useCallback(
    (color: string) => {
      if (!savedSelectionRef.current) return;
      activeEditor.update(() => {
        $setSelection(savedSelectionRef.current!.clone());
        const selection = $getSelection();
        if (selection !== null) {
          $patchStyleText(selection, { color });
        }
      });
    },
    [activeEditor]
  );

  const handleOpenChange = useCallback(
    (open: boolean) => {
      if (!open) {
        activeEditor.setEditable(true);
        activeEditor.focus();
      }
    },
    [activeEditor]
  );

  return (
    <ColorPickerPopover
      value={fontColor}
      onChangeComplete={applyColor}
      onOpenChange={handleOpenChange}
      triggerLabel={t("textColor")}
      modal
    >
      <Button variant="outline" size="icon-sm" onMouseDown={handleTriggerMouseDown}>
        <BaselineIcon className="size-4" />
      </Button>
    </ColorPickerPopover>
  );
}
