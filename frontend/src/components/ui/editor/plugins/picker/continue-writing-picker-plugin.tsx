import type { TFunction } from "i18next";
import { Sparkles } from "lucide-react";

import { AIWriteAction } from "@/api/generated/initiativeAPI.schemas";
import { AI_WRITE_COMMAND } from "@/components/ui/editor/plugins/ai-writing-plugin";
import { ComponentPickerOption } from "@/components/ui/editor/plugins/picker/component-picker-option";

export function ContinueWritingPickerPlugin(t: TFunction<"editor">) {
  return new ComponentPickerOption(t("writing.continue"), {
    icon: <Sparkles className="size-4" />,
    keywords: ["ai", "continue", "write", "draft"],
    onSelect: (_, editor) =>
      editor.dispatchCommand(AI_WRITE_COMMAND, { action: AIWriteAction.continue }),
  });
}
