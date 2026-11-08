import { useLexicalComposerContext } from "@lexical/react/LexicalComposerContext";
import { LexicalExtensionComposer } from "@lexical/react/LexicalExtensionComposer";
import { render } from "@testing-library/react";
import { $createParagraphNode, $createTextNode, $getRoot, type LexicalEditor } from "lexical";
import { describe, expect, it } from "vitest";

import { documentExtension } from "./document-extension";

function Grab({ take }: { take: (editor: LexicalEditor) => void }): null {
  const [editor] = useLexicalComposerContext();
  take(editor);
  return null;
}

/** The types of the nodes a line of text turns into, in a real document. */
function typedIntoADocument(line: string): string[] {
  let editor!: LexicalEditor;
  render(
    <LexicalExtensionComposer
      extension={documentExtension({ collaborative: false, editable: true })}
      contentEditable={null}
    >
      <Grab
        take={(found) => {
          editor = found;
        }}
      />
    </LexicalExtensionComposer>
  );

  editor.update(
    () => {
      const paragraph = $createParagraphNode();
      paragraph.append($createTextNode(line));
      $getRoot().clear().append(paragraph);
    },
    { discrete: true }
  );

  const types: string[] = [];
  editor.getEditorState().read(() => {
    for (const node of $getRoot()
      .getFirstChildOrThrow<ReturnType<typeof $createParagraphNode>>()
      .getChildren()) {
      types.push(node.getType());
    }
  });
  return types;
}

describe("what the document editor makes of what is typed", () => {
  it("leaves a word after # as plain text", () => {
    // The picker reads what is being typed out of ordinary text, so anything
    // that claims `#` for itself takes the trigger away from references.
    expect(typedIntoADocument("see #launch")).toEqual(["text"]);
  });

  it("still leaves prose alone", () => {
    expect(typedIntoADocument("see the launch")).toEqual(["text"]);
  });
});
