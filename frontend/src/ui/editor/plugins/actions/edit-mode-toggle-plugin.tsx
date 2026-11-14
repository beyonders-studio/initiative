import { useLexicalComposerContext } from "@lexical/react/LexicalComposerContext";
import { LockIcon, UnlockIcon } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/ui/tooltip";

interface EditModeTogglePluginProps {
  /** If true, forces read-only mode and prevents toggling to edit mode */
  forceReadOnly?: boolean;
}

export function EditModeTogglePlugin({ forceReadOnly = false }: EditModeTogglePluginProps) {
  const [editor] = useLexicalComposerContext();
  const { t } = useTranslation("editor");
  const [isEditable, setIsEditable] = useState(() => editor.isEditable());

  // Don't render the toggle if forced to read-only - user can't edit anyway
  if (forceReadOnly) {
    return null;
  }

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button
          variant={"ghost"}
          onClick={() => {
            editor.setEditable(!editor.isEditable());
            setIsEditable(editor.isEditable());
          }}
          title={t("actions.readOnlyMode")}
          aria-label={t(isEditable ? "actions.lockReadOnly" : "actions.unlockReadOnly")}
          size={"sm"}
          className="p-2"
        >
          {isEditable ? <LockIcon className="size-4" /> : <UnlockIcon className="size-4" />}
        </Button>
      </TooltipTrigger>
      <TooltipContent>{t(isEditable ? "actions.viewOnlyMode" : "actions.editMode")}</TooltipContent>
    </Tooltip>
  );
}
