import { useLexicalComposerContext } from "@lexical/react/LexicalComposerContext";
import { UploadIcon } from "lucide-react";

import { FileType } from "@/api/generated/initiativeAPI.schemas";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

// Export moved to the file header's engine-backed Export menu; the toolbar
// keeps only the import side. Import accepts EVERY file shape the app has ever
// exported: the generic initiative-file envelope (current engine export,
// editor state under `content`, discriminated by `type` — or `kind`, the
// field's name in early exports), the same envelope under its earlier
// initiative-document name, and the legacy @lexical/file .lexical shape
// (editor state under `editorState`).
function extractEditorState(parsed: unknown): unknown | null {
  if (typeof parsed !== "object" || parsed === null) {
    return null;
  }
  const record = parsed as Record<string, unknown>;
  const isEnvelope = (name: string): boolean => record.type === name || record.kind === name;
  const lexical =
    (isEnvelope("initiative-file") && record.file_type === FileType.lexical) ||
    (isEnvelope("initiative-document") && record.document_type === "native");
  if (lexical && typeof record.content === "object" && record.content !== null) {
    return record.content;
  }
  if (typeof record.editorState === "object" && record.editorState !== null) {
    return record.editorState;
  }
  return null;
}

export function ImportExportPlugin() {
  const [editor] = useLexicalComposerContext();

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
        const editorState = extractEditorState(JSON.parse(await file.text()));
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
          title="Import"
          aria-label="Import editor state from JSON"
          size={"sm"}
          className="p-2"
        >
          <UploadIcon className="size-4" />
        </Button>
      </TooltipTrigger>
      <TooltipContent>Import Content</TooltipContent>
    </Tooltip>
  );
}
