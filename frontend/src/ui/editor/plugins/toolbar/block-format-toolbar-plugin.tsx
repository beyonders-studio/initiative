import { $isListNode, ListNode } from "@lexical/list";
import { $isHeadingNode } from "@lexical/rich-text";
import { $findMatchingParent, $getNearestNodeOfType } from "@lexical/utils";
import { $isRangeSelection, $isRootOrShadowRoot, type BaseSelection } from "lexical";

import { useToolbarContext } from "@/ui/editor/context/toolbar-context";
import { useUpdateToolbarHandler } from "@/ui/editor/editor-hooks/use-update-toolbar";
import { useBlockTypeToBlockName } from "@/ui/editor/plugins/toolbar/block-format/block-format-data";
import {
  BLOCK_FORMAT_ORDER,
  type BlockFormatType,
  useBlockFormatActions,
} from "@/ui/editor/plugins/toolbar/toolbar-actions";
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger } from "@/ui/select";

/** Reports the block type the caret is in, so the toolbar reflects the body. */
export function useTrackBlockType() {
  const blockTypeToBlockName = useBlockTypeToBlockName();
  const { activeEditor, setBlockType } = useToolbarContext();

  function $updateToolbar(selection: BaseSelection) {
    if (!$isRangeSelection(selection)) return;

    const anchorNode = selection.anchor.getNode();
    let element =
      anchorNode.getKey() === "root"
        ? anchorNode
        : $findMatchingParent(anchorNode, (e) => {
            const parent = e.getParent();
            return parent !== null && $isRootOrShadowRoot(parent);
          });

    if (element === null) {
      element = anchorNode.getTopLevelElementOrThrow();
    }

    const elementDOM = activeEditor.getElementByKey(element.getKey());
    if (elementDOM === null) return;

    if ($isListNode(element)) {
      const parentList = $getNearestNodeOfType<ListNode>(anchorNode, ListNode);
      setBlockType(parentList ? parentList.getListType() : element.getListType());
      return;
    }

    const type = $isHeadingNode(element) ? element.getTag() : element.getType();
    if (type in blockTypeToBlockName) setBlockType(type);
  }

  useUpdateToolbarHandler($updateToolbar);
}

/** The block-type picker: what the caret's paragraph, heading or list is. */
export function BlockFormatDropDown({
  types = BLOCK_FORMAT_ORDER,
}: {
  /** Which block types this surface offers, in order. */
  types?: readonly BlockFormatType[];
}) {
  const blockTypeToBlockName = useBlockTypeToBlockName();
  const { blockType } = useToolbarContext();
  const actions = useBlockFormatActions(types);

  useTrackBlockType();

  return (
    <Select value={blockType}>
      <SelectTrigger className="h-8! w-min gap-1">
        {blockTypeToBlockName[blockType]?.icon}
        <span>{blockTypeToBlockName[blockType]?.label}</span>
      </SelectTrigger>
      <SelectContent>
        <SelectGroup>
          {actions.map((action) => (
            <SelectItem key={action.id} value={action.id} onPointerDown={action.run}>
              <div className="flex items-center gap-1 font-normal">
                {action.icon}
                {action.label}
              </div>
            </SelectItem>
          ))}
        </SelectGroup>
      </SelectContent>
    </Select>
  );
}
