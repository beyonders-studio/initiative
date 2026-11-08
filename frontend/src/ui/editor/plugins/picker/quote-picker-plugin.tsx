import { $createQuoteNode } from "@lexical/rich-text";
import { $setBlocksType } from "@lexical/selection";
import type { TFunction } from "i18next";
import { $getSelection, $isRangeSelection } from "lexical";
import { QuoteIcon } from "lucide-react";

import { ComponentPickerOption } from "@/ui/editor/plugins/picker/component-picker-option";

export function QuotePickerPlugin(t: TFunction<"editor">) {
  return new ComponentPickerOption(t("picker.quote"), {
    icon: <QuoteIcon className="size-4" />,
    keywords: ["block quote"],
    onSelect: (_, editor) =>
      editor.update(() => {
        const selection = $getSelection();
        if ($isRangeSelection(selection)) {
          $setBlocksType(selection, () => $createQuoteNode());
        }
      }),
  });
}
