import { $isLinkNode } from "@lexical/link";
import { $findMatchingParent } from "@lexical/utils";
import {
  $isElementNode,
  $isRangeSelection,
  type BaseSelection,
  type ElementFormatType,
} from "lexical";
import { ChevronDownIcon } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { useUpdateToolbarHandler } from "@/components/editor/editor-hooks/use-update-toolbar";
import {
  type AlignmentType,
  useAlignmentActions,
  useIndentActions,
} from "@/components/editor/plugins/toolbar/toolbar-actions";
import { getSelectedNode } from "@/components/editor/utils/get-selected-node";
import { Button } from "@/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/ui/dropdown-menu";

/** Which alignment the caret's block carries, defaulting to the left. */
export function useCurrentAlignment(): AlignmentType {
  const [elementFormat, setElementFormat] = useState<ElementFormatType>("left");

  const $updateToolbar = (selection: BaseSelection) => {
    if (!$isRangeSelection(selection)) return;

    const node = getSelectedNode(selection);
    const parent = node.getParent();

    // A link carries no alignment of its own; the paragraph around it does.
    const matchingParent = $isLinkNode(parent)
      ? $findMatchingParent(node, (candidate) => $isElementNode(candidate) && !candidate.isInline())
      : null;

    setElementFormat(
      $isElementNode(matchingParent)
        ? matchingParent.getFormatType()
        : $isElementNode(node)
          ? node.getFormatType()
          : parent?.getFormatType() || "left"
    );
  };

  useUpdateToolbarHandler($updateToolbar);

  return (["left", "center", "right", "justify"] as const).includes(elementFormat as AlignmentType)
    ? (elementFormat as AlignmentType)
    : "left";
}

export function ElementFormatToolbarPlugin() {
  const { t } = useTranslation("editor");
  const current = useCurrentAlignment();
  const alignments = useAlignmentActions(current);
  const indents = useIndentActions();

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="outline" size="sm" className="h-8 gap-1 px-2" aria-label={t("align")}>
          {alignments.find((action) => action.active)?.icon}
          <ChevronDownIcon className="size-3" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start">
        {alignments.map((action) => (
          <DropdownMenuItem
            key={action.id}
            onClick={action.run}
            className={action.active ? "bg-accent" : ""}
          >
            {action.icon}
            <span>{action.label}</span>
          </DropdownMenuItem>
        ))}
        <DropdownMenuSeparator />
        {indents.map((action) => (
          <DropdownMenuItem key={action.id} onClick={action.run}>
            {action.icon}
            <span>{action.label}</span>
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
