import { createEditor, type LexicalEditor } from "lexical";
import { describe, expect, it } from "vitest";

import { SearchEntityType } from "@/api/generated/initiativeAPI.schemas";
import {
  $createEntityMentionNode,
  EntityMentionNode,
  type SerializedEntityMentionNode,
} from "@/components/editor/nodes/entity-mention-node";

/** A node only exists inside an editor, so every case runs in one. */
function inEditor<T>(fn: () => T): T {
  const editor: LexicalEditor = createEditor({
    nodes: [EntityMentionNode],
    onError: (error) => {
      throw error;
    },
  });
  let result!: T;
  editor.update(
    () => {
      result = fn();
    },
    { discrete: true }
  );
  return result;
}

describe("a thing mentioned in a document", () => {
  it("survives being written down and read back", () => {
    // Read inside the editor: a node's own accessors need its state.
    const { serialized, entityType, entityId, text, inline } = inEditor(() => {
      const node = $createEntityMentionNode(SearchEntityType.wiki, 12, "Summer fete");
      const serialized = node.exportJSON() as SerializedEntityMentionNode;
      const restored = EntityMentionNode.importJSON(serialized);
      return {
        serialized,
        entityType: restored.getEntityType(),
        entityId: restored.getEntityId(),
        // The label is kept as text, which is what export and search read.
        text: restored.getTextContent(),
        // It sits in a sentence rather than between paragraphs.
        inline: restored.isInline(),
      };
    });

    expect(serialized).toMatchObject({
      type: "entity-mention",
      entityType: SearchEntityType.wiki,
      entityId: 12,
      text: "Summer fete",
    });
    expect(entityType).toBe(SearchEntityType.wiki);
    expect(entityId).toBe(12);
    expect(text).toBe("Summer fete");
    expect(inline).toBe(true);
  });

  it("names the entity on the element, so a click knows what to open", () => {
    const element = inEditor(
      () =>
        $createEntityMentionNode(SearchEntityType.calendar_event, 9, "Kickoff").exportDOM()
          .element as HTMLElement
    );
    expect(element.getAttribute("data-lexical-entity-mention")).toBe(
      SearchEntityType.calendar_event
    );
    expect(element.getAttribute("data-entity-id")).toBe("9");
    expect(element.textContent).toBe("Kickoff");
  });
});
