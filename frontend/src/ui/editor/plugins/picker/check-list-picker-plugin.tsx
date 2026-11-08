import { INSERT_CHECK_LIST_COMMAND } from "@lexical/list";
import type { TFunction } from "i18next";
import { ListTodoIcon } from "lucide-react";

import { ComponentPickerOption } from "@/ui/editor/plugins/picker/component-picker-option";

export function CheckListPickerPlugin(t: TFunction<"editor">) {
  return new ComponentPickerOption(t("picker.checkList"), {
    icon: <ListTodoIcon className="size-4" />,
    keywords: ["check list", "todo list"],
    onSelect: (_, editor) => editor.dispatchCommand(INSERT_CHECK_LIST_COMMAND, undefined),
  });
}
