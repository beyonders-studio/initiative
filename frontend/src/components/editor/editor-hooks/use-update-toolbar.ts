import { $getSelection, type BaseSelection } from "lexical";
import { useEffect, useEffectEvent } from "react";

import { useToolbarContext } from "@/components/editor/context/toolbar-context";

/**
 * Calls `callback` with the selection when the toolbar opens on an editor and
 * after each update to it: a moved caret, and a change that leaves the caret
 * where it was, such as a new alignment. Registered once per editor.
 */
export function useUpdateToolbarHandler(callback: (selection: BaseSelection) => void) {
  const { activeEditor } = useToolbarContext();
  const onSelection = useEffectEvent(callback);

  useEffect(() => {
    const read = () =>
      activeEditor.read(() => {
        const selection = $getSelection();
        if (selection) onSelection(selection);
      });
    read();
    return activeEditor.registerUpdateListener(read);
  }, [activeEditor]);
}
