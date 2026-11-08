import { $isCodeNode } from "@lexical/code";
import { CODE_LANGUAGE_MAP, getLanguageFriendlyName } from "@lexical/code-prism";
import { $isListNode } from "@lexical/list";
import { $findMatchingParent } from "@lexical/utils";
import { $isRangeSelection, $isRootOrShadowRoot, type BaseSelection } from "lexical";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { useUpdateToolbarHandler } from "@/ui/editor/editor-hooks/use-update-toolbar";
import { useCodeLanguageActions } from "@/ui/editor/plugins/toolbar/toolbar-actions";
import { Select, SelectContent, SelectItem, SelectTrigger } from "@/ui/select";

/** Which language the code block the caret sits in is written in. */
export function useCurrentCodeLanguage() {
  const [codeLanguage, setCodeLanguage] = useState("");

  const $updateToolbar = (selection: BaseSelection) => {
    if (!$isRangeSelection(selection)) return;

    const anchorNode = selection.anchor.getNode();
    const element =
      anchorNode.getKey() === "root"
        ? anchorNode
        : ($findMatchingParent(anchorNode, (node) => {
            const parent = node.getParent();
            return parent !== null && $isRootOrShadowRoot(parent);
          }) ?? anchorNode.getTopLevelElementOrThrow());

    if (!$isListNode(element) && $isCodeNode(element)) {
      const language = element.getLanguage() as keyof typeof CODE_LANGUAGE_MAP;
      setCodeLanguage(language ? CODE_LANGUAGE_MAP[language] || language : "");
    }
  };

  useUpdateToolbarHandler($updateToolbar);

  return codeLanguage;
}

export function CodeLanguageToolbarPlugin() {
  const { t } = useTranslation("editor");
  const codeLanguage = useCurrentCodeLanguage();
  const actions = useCodeLanguageActions();

  return (
    <Select value={codeLanguage}>
      <SelectTrigger className="h-8! w-min gap-1">
        <span>{getLanguageFriendlyName(codeLanguage) || t("selectLanguage")}</span>
      </SelectTrigger>
      <SelectContent>
        {actions.map((action) => (
          <SelectItem key={action.id} value={action.id} onPointerUp={action.run}>
            {action.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
