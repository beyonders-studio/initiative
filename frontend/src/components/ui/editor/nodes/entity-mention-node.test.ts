import { createEditor, type LexicalEditor } from "lexical";
import { describe, expect, it } from "vitest";

import { SearchEntityType } from "@/api/generated/initiativeAPI.schemas";
import {
  $createEntityMentionNode,
  EntityMentionNode,
  type SerializedEntityMentionNode,
} from "@/components/ui/editor/nodes/entity-mention-node";

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
    const { serialized, entityType, entityId, text } = inEditor(() => {
      const node = $createEntityMentionNode(SearchEntityType.queue, 12, "Intake queue");
      const serialized = node.exportJSON() as SerializedEntityMentionNode;
      const restored = EntityMentionNode.importJSON(serialized);
      return {
        serialized,
        entityType: restored.getEntityType(),
        entityId: restored.getEntityId(),
        text: restored.getTextContent(),
      };
    });

    expect(serialized).toMatchObject({
      type: "entity-mention",
      entityType: SearchEntityType.queue,
      entityId: 12,
      text: "Intake queue",
    });
    expect(entityType).toBe(SearchEntityType.queue);
    expect(entityId).toBe(12);
    expect(text).toBe("Intake queue");
  });

  it("carries its label as text, which is what export and search read", () => {
    const text = inEditor(
      () =>
        $createEntityMentionNode(SearchEntityType.dashboard, 3, "Q1 dashboard").exportJSON().text
    );
    expect(text).toBe("Q1 dashboard");
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

  it("is a different kind of node from an @ mention of a person", () => {
    expect(EntityMentionNode.getType()).toBe("entity-mention");
  });

  it("sits in a sentence rather than between paragraphs", () => {
    const inline = inEditor(() =>
      $createEntityMentionNode(SearchEntityType.task, 1, "Ship it").isInline()
    );
    expect(inline).toBe(true);
  });

  it("keeps the name it was written with, for surfaces that cannot ask", () => {
    // An export and the search index read this; the app reads the live one.
    const text = inEditor(() =>
      $createEntityMentionNode(SearchEntityType.task, 1, "Ship it").getTextContent()
    );
    expect(text).toBe("Ship it");
  });
});
