import { INSERT_HORIZONTAL_RULE_COMMAND } from "@lexical/extension";
import type { TFunction } from "i18next";
import { MinusIcon } from "lucide-react";

import { ComponentPickerOption } from "@/ui/editor/plugins/picker/component-picker-option";

export function DividerPickerPlugin(t: TFunction<"editor">) {
  return new ComponentPickerOption(t("picker.divider"), {
    icon: <MinusIcon className="size-4" />,
    keywords: ["horizontal rule", "divider", "hr"],
    onSelect: (_, editor) => editor.dispatchCommand(INSERT_HORIZONTAL_RULE_COMMAND, undefined),
  });
}
