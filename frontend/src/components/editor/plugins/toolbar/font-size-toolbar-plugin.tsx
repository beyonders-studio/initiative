import { $getSelectionStyleValueForProperty } from "@lexical/selection";
import { $isRangeSelection, type BaseSelection } from "lexical";
import { Minus, Plus } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { useUpdateToolbarHandler } from "@/components/editor/editor-hooks/use-update-toolbar";
import {
  DEFAULT_FONT_SIZE,
  MAX_FONT_SIZE,
  MIN_FONT_SIZE,
  useApplyFontSize,
} from "@/components/editor/plugins/toolbar/toolbar-actions";
import { Button } from "@/ui/button";
import { ButtonGroup } from "@/ui/button-group";
import { Input } from "@/ui/input";

export function FontSizeToolbarPlugin() {
  const [fontSize, setFontSize] = useState(DEFAULT_FONT_SIZE);
  const applyFontSize = useApplyFontSize();
  const { t } = useTranslation("editor");

  const $updateToolbar = (selection: BaseSelection) => {
    if ($isRangeSelection(selection)) {
      const value = $getSelectionStyleValueForProperty(
        selection,
        "font-size",
        `${DEFAULT_FONT_SIZE}px`
      );
      setFontSize(parseInt(value, 10) || DEFAULT_FONT_SIZE);
    }
  };

  useUpdateToolbarHandler($updateToolbar);

  const update = (size: number) => setFontSize(applyFontSize(size));

  return (
    <ButtonGroup>
      <Button
        variant="outline"
        size="icon-sm"
        className="size-8!"
        type="button"
        onClick={() => update(fontSize - 1)}
        disabled={fontSize <= MIN_FONT_SIZE}
      >
        <Minus className="size-3" />
      </Button>
      <Input
        value={fontSize}
        aria-label={t("fontSize")}
        onChange={(e) => update(parseInt(e.target.value, 10) || DEFAULT_FONT_SIZE)}
        className="h-8! w-12 text-center"
        min={MIN_FONT_SIZE}
        max={MAX_FONT_SIZE}
      />
      <Button
        variant="outline"
        size="icon-sm"
        className="size-8!"
        type="button"
        onClick={() => update(fontSize + 1)}
        disabled={fontSize >= MAX_FONT_SIZE}
      >
        <Plus className="size-3" />
      </Button>
    </ButtonGroup>
  );
}
