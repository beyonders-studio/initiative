import { INSERT_ORDERED_LIST_COMMAND } from "@lexical/list";
import type { TFunction } from "i18next";
import { ListOrderedIcon } from "lucide-react";

import { ComponentPickerOption } from "@/ui/editor/plugins/picker/component-picker-option";

export function NumberedListPickerPlugin(t: TFunction<"editor">) {
  return new ComponentPickerOption(t("picker.numberedList"), {
    icon: <ListOrderedIcon className="size-4" />,
    keywords: ["numbered list", "ordered list", "ol"],
    onSelect: (_, editor) => editor.dispatchCommand(INSERT_ORDERED_LIST_COMMAND, undefined),
  });
}
