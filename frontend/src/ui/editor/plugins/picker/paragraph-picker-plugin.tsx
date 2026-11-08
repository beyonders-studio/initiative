import { $setBlocksType } from "@lexical/selection";
import type { TFunction } from "i18next";
import { $createParagraphNode, $getSelection, $isRangeSelection } from "lexical";
import { TextIcon } from "lucide-react";

import { ComponentPickerOption } from "@/ui/editor/plugins/picker/component-picker-option";

export function ParagraphPickerPlugin(t: TFunction<"editor">) {
  return new ComponentPickerOption(t("blockNormal"), {
    icon: <TextIcon className="size-4" />,
    keywords: ["normal", "paragraph", "p", "text"],
    onSelect: (_, editor) =>
      editor.update(() => {
        const selection = $getSelection();
        if ($isRangeSelection(selection)) {
          $setBlocksType(selection, () => $createParagraphNode());
        }
      }),
  });
}
