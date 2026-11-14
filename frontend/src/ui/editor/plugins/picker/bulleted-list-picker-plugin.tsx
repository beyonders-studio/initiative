import { INSERT_UNORDERED_LIST_COMMAND } from "@lexical/list";
import type { TFunction } from "i18next";
import { ListIcon } from "lucide-react";

import { ComponentPickerOption } from "@/ui/editor/plugins/picker/component-picker-option";

export function BulletedListPickerPlugin(t: TFunction<"editor">) {
  return new ComponentPickerOption(t("picker.bulletedList"), {
    icon: <ListIcon className="size-4" />,
    keywords: ["bulleted list", "unordered list", "ul"],
    onSelect: (_, editor) => editor.dispatchCommand(INSERT_UNORDERED_LIST_COMMAND, undefined),
  });
}
