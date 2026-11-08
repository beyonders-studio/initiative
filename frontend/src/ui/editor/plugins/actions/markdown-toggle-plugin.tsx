import { $createCodeNode, $isCodeNode } from "@lexical/code";
import {
  $convertFromMarkdownString,
  $convertToMarkdownString,
  type Transformer,
} from "@lexical/markdown";
import { useLexicalComposerContext } from "@lexical/react/LexicalComposerContext";
import { $createTextNode, $getRoot } from "lexical";
import { FileTextIcon } from "lucide-react";
import { useCallback } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/ui/button";

// Both directions use Lexical's CommonMark default (false). This is the
// only configuration that round-trips:
//   Lexical Para A + Para B  →  "A\n\nB"  →  Lexical Para A + Para B
//   Lexical LineBreakNode    →  "\\\n"     →  Lexical LineBreakNode
// With shouldPreserveNewLines=true on export, paragraphs collapse to a
// single `\n` — indistinguishable from a soft break — and the round trip
// loses paragraph structure. The cost of `false` is that LineBreakNode
// serializes as the CommonMark hard-break (`\\\n`, a literal backslash
// before the newline) rather than a bare `\n`. A bare `\n` for soft
// breaks isn't viable here: on re-import CommonMark treats it as
// whitespace and the break is lost entirely.
const PRESERVE_NEWLINES_ON_IMPORT = false;
const PRESERVE_NEWLINES_ON_EXPORT = false;

export function MarkdownTogglePlugin({ transformers }: { transformers: Array<Transformer> }) {
  const [editor] = useLexicalComposerContext();
  const { t } = useTranslation("editor");

  const handleMarkdownToggle = useCallback(() => {
    editor.update(() => {
      const root = $getRoot();
      const firstChild = root.getFirstChild();
      if ($isCodeNode(firstChild) && firstChild.getLanguage() === "markdown") {
        $convertFromMarkdownString(
          firstChild.getTextContent(),
          transformers,
          undefined, // node
          PRESERVE_NEWLINES_ON_IMPORT
        );
      } else {
        const markdown = $convertToMarkdownString(
          transformers,
          undefined, //node
          PRESERVE_NEWLINES_ON_EXPORT
        );
        const codeNode = $createCodeNode("markdown");
        codeNode.append($createTextNode(markdown));
        root.clear().append(codeNode);
        if (markdown.length === 0) {
          codeNode.select();
        }
      }
    });
    // transformers is intentionally omitted: both call sites pass an
    // inline array literal so a new reference would arrive every parent
    // render, defeating the memoization. The transformer set is
    // effectively constant for the lifetime of the editor instance, so
    // capturing the first value is safe.
  }, [editor, transformers]);

  return (
    <Button
      variant={"ghost"}
      onClick={handleMarkdownToggle}
      title={t("actions.markdownTitle")}
      aria-label={t("actions.markdownLabel")}
      size={"sm"}
      className="p-2"
    >
      <FileTextIcon className="size-4" />
    </Button>
  );
}
