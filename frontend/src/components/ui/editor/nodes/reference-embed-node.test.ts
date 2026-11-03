import { buildEditorFromExtensions } from "@lexical/extension";
import { $convertFromMarkdownString, $convertToMarkdownString } from "@lexical/markdown";
import { RichTextExtension } from "@lexical/rich-text";
import {
  $createParagraphNode,
  $createTextNode,
  $getRoot,
  defineExtension,
  type ElementNode,
  type LexicalEditor,
} from "lexical";
import { describe, expect, it } from "vitest";

import { SearchEntityType } from "@/api/generated/initiativeAPI.schemas";
import {
  $createEntityMentionNode,
  $isEntityMentionNode,
  EntityMentionNode,
} from "@/components/ui/editor/nodes/entity-mention-node";
import {
  $isReferenceEmbedNode,
  $showAsEmbed,
  $showAsLink,
  ReferenceEmbedNode,
} from "@/components/ui/editor/nodes/reference-embed-node";
import { EMBED } from "@/components/ui/editor/transformers/markdown-embed-transformer";
import { EMPTY_TASK_FILTERS } from "@/lib/filters/taskFilters";

function makeEditor(): LexicalEditor {
  return buildEditorFromExtensions(
    defineExtension({
      name: "@test/embeds",
      dependencies: [RichTextExtension],
      nodes: [EntityMentionNode, ReferenceEmbedNode],
      onError: (error) => {
        throw error;
      },
    })
  );
}

const types = (editor: LexicalEditor) =>
  editor.getEditorState().read(() =>
    $getRoot()
      .getChildren()
      .map((child) => child.getType())
  );

describe("an embed in markdown", () => {
  it("is `![[ ]]`, carrying the reference and the name", () => {
    const editor = makeEditor();
    const source = "![[task:12|Roll call]]";
    let exported = "";
    editor.update(() => $convertFromMarkdownString(source, [EMBED]), { discrete: true });
    editor.getEditorState().read(() => {
      const embed = $getRoot().getFirstChild();
      expect($isReferenceEmbedNode(embed)).toBe(true);
      if (!$isReferenceEmbedNode(embed)) return;
      expect([embed.getEntityType(), embed.getEntityId(), embed.getTextContent()]).toEqual([
        SearchEntityType.task,
        12,
        "Roll call",
      ]);
      exported = $convertToMarkdownString([EMBED]);
    });
    expect(exported).toBe(source);
  });

  it("stays text when it names no kind of thing", () => {
    const editor = makeEditor();
    editor.update(() => $convertFromMarkdownString("![[spell:3|Fireball]]", [EMBED]), {
      discrete: true,
    });
    expect(types(editor)).toEqual(["paragraph"]);
  });
});

describe("switching between a link and an embed", () => {
  it("moves a link mid-sentence onto a line of its own, and back", () => {
    const editor = makeEditor();
    editor.update(
      () => {
        const link = $createEntityMentionNode(SearchEntityType.task, 12, "Roll call");
        $getRoot()
          .clear()
          .append($createParagraphNode().append($createTextNode("see "), link));
        $showAsEmbed(link);
      },
      { discrete: true }
    );
    // The sentence keeps its words; the embed follows it, with a line after
    // to keep writing on.
    expect(types(editor)).toEqual(["paragraph", "reference-embed", "paragraph"]);

    editor.update(
      () => {
        const embed = $getRoot().getChildAtIndex(1);
        if ($isReferenceEmbedNode(embed)) $showAsLink(embed);
      },
      { discrete: true }
    );
    editor.getEditorState().read(() => {
      const line = $getRoot().getChildAtIndex(1);
      expect(line?.getType()).toBe("paragraph");
      const link = $getRoot().getChildAtIndex<ElementNode>(1)?.getFirstChild?.();
      expect($isEntityMentionNode(link) && link.getEntityId()).toBe(12);
    });
  });

  it("takes the line over when the link was all that was on it", () => {
    const editor = makeEditor();
    editor.update(
      () => {
        const link = $createEntityMentionNode(SearchEntityType.queue, 4, "Intake");
        $getRoot().clear().append($createParagraphNode().append(link));
        $showAsEmbed(link);
      },
      { discrete: true }
    );
    expect(types(editor)).toEqual(["reference-embed", "paragraph"]);
  });
});

describe("what an embed keeps", () => {
  const stored = (node: object) => {
    const editor = makeEditor();
    editor.setEditorState(
      editor.parseEditorState({
        root: {
          type: "root",
          version: 1,
          direction: null,
          format: "",
          indent: 0,
          children: [node],
        },
      } as never)
    );
    return editor.getEditorState().read(() => {
      const embed = $getRoot().getFirstChild();
      if (!$isReferenceEmbedNode(embed)) throw new Error("not an embed");
      return embed.exportJSON();
    });
  };

  it("reads one saved before it had a choice as a card", () => {
    const json = stored({
      type: "reference-embed",
      version: 1,
      entityType: "task",
      entityId: 12,
      text: "Roll call",
    });
    expect(json.display).toEqual({ mode: "card" });
    expect(json.query).toBeUndefined();
  });

  it("keeps the facts it shows, and the filter it shows tasks for", () => {
    const query = {
      initiative_id: 3,
      project_id: 9,
      filters: { ...EMPTY_TASK_FILTERS, status_categories: ["todo"] },
      sort: [{ field: "due_date", dir: "asc" }],
    };
    expect(
      stored({
        type: "reference-embed",
        version: 2,
        entityType: "task",
        entityId: 12,
        text: "Roll call",
        display: { mode: "fields", fields: ["task:status", "task:due", "nonsense"] },
      }).display
    ).toEqual({ mode: "fields", fields: ["task:status", "task:due"] });

    const json = stored({
      type: "reference-embed",
      version: 2,
      entityType: "task",
      entityId: 0,
      text: "Open launch tasks",
      display: { mode: "table", columns: ["title", "dueDate"] },
      query,
    });
    expect(json.query).toEqual(query);
    expect(json.display).toEqual({ mode: "table", columns: ["title", "dueDate"] });
  });

  it("reads a filter whose values were damaged as the values it can trust", () => {
    const json = stored({
      type: "reference-embed",
      version: 2,
      entityType: "task",
      entityId: 0,
      text: "Open launch tasks",
      display: { mode: "list" },
      query: { initiative_id: 3, filters: { properties: null, assignees: ["me", 4] }, sort: "x" },
    });
    expect(json.query).toEqual({
      initiative_id: 3,
      project_id: null,
      filters: { ...EMPTY_TASK_FILTERS, assignees: ["me"] },
      sort: [],
    });
  });
});
