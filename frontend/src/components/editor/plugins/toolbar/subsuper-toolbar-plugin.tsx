import { $isTableSelection } from "@lexical/table";
import { $isRangeSelection, type BaseSelection } from "lexical";
import { useState } from "react";

import { useUpdateToolbarHandler } from "@/components/editor/editor-hooks/use-update-toolbar";
import { useSubSuperActions } from "@/components/editor/plugins/toolbar/toolbar-actions";
import { ToggleGroup, ToggleGroupItem } from "@/ui/toggle-group";

export function SubSuperToolbarPlugin() {
  const [active, setActive] = useState("");
  const actions = useSubSuperActions();

  const $updateToolbar = (selection: BaseSelection) => {
    if ($isRangeSelection(selection) || $isTableSelection(selection)) {
      setActive(
        selection.hasFormat("subscript")
          ? "subscript"
          : selection.hasFormat("superscript")
            ? "superscript"
            : ""
      );
    }
  };

  useUpdateToolbarHandler($updateToolbar);

  return (
    <ToggleGroup type="single" value={active}>
      {actions.map((action) => (
        <ToggleGroupItem
          key={action.id}
          value={action.id}
          size="sm"
          variant="outline"
          aria-label={action.label}
          onClick={action.run}
        >
          {action.icon}
        </ToggleGroupItem>
      ))}
    </ToggleGroup>
  );
}
