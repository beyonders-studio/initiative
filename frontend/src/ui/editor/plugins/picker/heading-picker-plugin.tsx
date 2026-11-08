import { $createHeadingNode } from "@lexical/rich-text";
import { $setBlocksType } from "@lexical/selection";
import type { TFunction } from "i18next";
import { $getSelection, $isRangeSelection } from "lexical";
import { Heading1Icon, Heading2Icon, Heading3Icon } from "lucide-react";

import { ComponentPickerOption } from "@/ui/editor/plugins/picker/component-picker-option";

export function HeadingPickerPlugin({ n, t }: { n: 1 | 2 | 3; t: TFunction<"editor"> }) {
  return new ComponentPickerOption(t(`blockH${n}`), {
    icon: <HeadingIcons n={n} />,
    keywords: ["heading", "header", `h${n}`],
    onSelect: (_, editor) =>
      editor.update(() => {
        const selection = $getSelection();
        if ($isRangeSelection(selection)) {
          $setBlocksType(selection, () => $createHeadingNode(`h${n}`));
        }
      }),
  });
}

function HeadingIcons({ n }: { n: number }) {
  switch (n) {
    case 1:
      return <Heading1Icon className="size-4" />;
    case 2:
      return <Heading2Icon className="size-4" />;
    case 3:
      return <Heading3Icon className="size-4" />;
  }
}
