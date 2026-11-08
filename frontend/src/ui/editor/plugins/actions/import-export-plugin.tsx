import { useLexicalComposerContext } from "@lexical/react/LexicalComposerContext";
import { UploadIcon } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Button } from "@/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/ui/tooltip";

/** Finds the editor state in a file of the host's own format, or nothing. */
export type ReadImport = (file: Record<string, unknown>) => unknown;

const isObject = (value: unknown): value is object => typeof value === "object" && value !== null;

// A file the host reads, then the `@lexical/file` `.lexical` shape (the editor
// state under `editorState`).
function extractEditorState(parsed: unknown, readImport?: ReadImport): unknown | null {
  if (!isObject(parsed)) {
    return null;
  }
  const record = parsed as Record<string, unknown>;
  const hosted = readImport?.(record);
  if (isObject(hosted)) {
    return hosted;
  }
  return isObject(record.editorState) ? record.editorState : null;
}

export function ImportExportPlugin({ readImport }: { readImport?: ReadImport }) {
  const [editor] = useLexicalComposerContext();
  const { t } = useTranslation("editor");

  const handleImport = () => {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = ".json,.lexical,application/json";
    input.onchange = async () => {
      const file = input.files?.[0];
      if (!file) {
        return;
      }
      try {
        const editorState = extractEditorState(JSON.parse(await file.text()), readImport);
        if (!editorState) {
          return;
        }
        editor.setEditorState(editor.parseEditorState(JSON.stringify(editorState)));
      } catch {
        // Unreadable/JSON-invalid file: leave the editor untouched.
      }
    };
    input.click();
  };

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button
          variant={"ghost"}
          onClick={handleImport}
          title={t("actions.importTitle")}
          aria-label={t("actions.importLabel")}
          size={"sm"}
          className="p-2"
        >
          <UploadIcon className="size-4" />
        </Button>
      </TooltipTrigger>
      <TooltipContent>{t("actions.importTooltip")}</TooltipContent>
    </Tooltip>
  );
}
