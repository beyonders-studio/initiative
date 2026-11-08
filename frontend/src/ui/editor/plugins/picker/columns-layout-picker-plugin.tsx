import { Columns3Icon } from "lucide-react";
import { useTranslation } from "react-i18next";

import { InsertLayoutDialog } from "@/ui/editor/plugins/layout-plugin";
import { ComponentPickerOption } from "@/ui/editor/plugins/picker/component-picker-option";

export function ColumnsLayoutPickerPlugin() {
  const { t } = useTranslation("editor");
  return new ComponentPickerOption(t("columnsLayout"), {
    icon: <Columns3Icon className="size-4" />,
    keywords: ["columns", "layout", "grid"],
    onSelect: (_, editor, showModal) =>
      showModal(t("insertColumnsLayout"), (onClose) => (
        <InsertLayoutDialog activeEditor={editor} onClose={onClose} />
      )),
  });
}
