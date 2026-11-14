import { $createCodeNode } from "@lexical/code";
import { $insertNodeToNearestRoot } from "@lexical/utils";
import type { TFunction } from "i18next";
import { $createTextNode } from "lexical";
import { Workflow } from "lucide-react";

import { MERMAID_LANGUAGE } from "@/ui/editor/plugins/mermaid-preview-plugin";
import { ComponentPickerOption } from "@/ui/editor/plugins/picker/component-picker-option";

/** A diagram written as text: a Mermaid code block with two boxes to start
 * from, drawn as it is typed. */
export function DiagramPickerPlugin(t: TFunction<"editor">) {
  return new ComponentPickerOption(t("diagram"), {
    icon: <Workflow className="size-4" />,
    keywords: ["diagram", "mermaid", "flowchart", "sequence", "chart", "graph"],
    onSelect: (_, editor) =>
      editor.update(() => {
        const code = $createCodeNode(MERMAID_LANGUAGE).append(
          $createTextNode("flowchart LR\n  A[Start] --> B[Finish]")
        );
        $insertNodeToNearestRoot(code);
        code.selectEnd();
      }),
  });
}
