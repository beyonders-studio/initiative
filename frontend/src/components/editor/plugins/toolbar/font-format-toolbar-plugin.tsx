import { $isTableSelection } from "@lexical/table";
import { $isRangeSelection, type BaseSelection, type TextFormatType } from "lexical";
import { useCallback, useState } from "react";

import { useUpdateToolbarHandler } from "@/components/editor/editor-hooks/use-update-toolbar";
import {
  TEXT_FORMAT_IDS,
  useTextFormatActions,
} from "@/components/editor/plugins/toolbar/toolbar-actions";
import { ToggleGroup, ToggleGroupItem } from "@/ui/toggle-group";

export function FontFormatToolbarPlugin() {
  const [activeFormats, setActiveFormats] = useState<string[]>([]);
  const actions = useTextFormatActions(activeFormats);

  const $updateToolbar = useCallback((selection: BaseSelection) => {
    if (!($isRangeSelection(selection) || $isTableSelection(selection))) return;

    const formats = TEXT_FORMAT_IDS.filter((format) =>
      selection.hasFormat(format as TextFormatType)
    );
    setActiveFormats((prev) =>
      prev.length === formats.length && formats.every((f) => prev.includes(f)) ? prev : formats
    );
  }, []);

  useUpdateToolbarHandler($updateToolbar);

  return (
    <ToggleGroup type="multiple" value={activeFormats} variant="outline" size="sm">
      {actions.map((action) => (
        <ToggleGroupItem
          key={action.id}
          value={action.id}
          aria-label={action.label}
          onClick={action.run}
        >
          {action.icon}
        </ToggleGroupItem>
      ))}
    </ToggleGroup>
  );
}
