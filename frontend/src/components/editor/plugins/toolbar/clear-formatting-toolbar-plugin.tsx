import { EraserIcon } from "lucide-react";
import { useTranslation } from "react-i18next";

import { useClearFormatting } from "@/components/editor/plugins/toolbar/toolbar-actions";
import { Button } from "@/ui/button";

export function ClearFormattingToolbarPlugin() {
  const clearFormatting = useClearFormatting();
  const { t } = useTranslation("editor");

  return (
    <Button
      variant="outline"
      size="icon-sm"
      className="size-8!"
      onClick={clearFormatting}
      title={t("clearFormatting")}
      aria-label={t("clearFormatting")}
      type="button"
    >
      <EraserIcon className="size-4" />
    </Button>
  );
}
