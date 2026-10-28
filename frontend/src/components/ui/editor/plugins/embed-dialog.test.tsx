import { useLexicalComposerContext } from "@lexical/react/LexicalComposerContext";
import { LexicalExtensionComposer } from "@lexical/react/LexicalExtensionComposer";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { $getRoot, type LexicalEditor } from "lexical";
import { HttpResponse } from "msw";
import { useMemo } from "react";
import { describe, expect, it, vi } from "vitest";

import { buildProject, buildPropertyDefinition } from "@/__tests__/factories";
import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { definitionsHandler } from "@/__tests__/helpers/handlers/property.handlers";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";
import { EditorInitiativeContext } from "@/components/ui/editor/context/editor-initiative-context";
import { documentExtension } from "@/components/ui/editor/document-extension";
import { $isReferenceEmbedNode } from "@/components/ui/editor/nodes/reference-embed-node";
import { EmbedDialog } from "@/components/ui/editor/plugins/embed-dialog";
import { TooltipProvider } from "@/components/ui/tooltip";

let editor!: LexicalEditor;

function Harness({ onClose }: { onClose: () => void }) {
  const extension = useMemo(() => documentExtension({ collaborative: false, editable: true }), []);
  return (
    <EditorInitiativeContext.Provider value={7}>
      <LexicalExtensionComposer extension={extension} contentEditable={null}>
        <TooltipProvider>
          <Dialog onClose={onClose} />
        </TooltipProvider>
      </LexicalExtensionComposer>
    </EditorInitiativeContext.Provider>
  );
}

function Dialog({ onClose }: { onClose: () => void }) {
  const [found] = useLexicalComposerContext();
  editor = found;
  return <EmbedDialog activeEditor={found} onClose={onClose} />;
}

const embeds = () =>
  editor.getEditorState().read(() =>
    $getRoot()
      .getChildren()
      .filter($isReferenceEmbedNode)
      .map((node) => node.exportJSON())
  );

describe("choosing what an embed shows", () => {
  it("inserts a count of the tasks a filter matches in the page's initiative", async () => {
    const onClose = vi.fn();
    renderPage(() => <Harness onClose={onClose} />);

    await userEvent.click(await screen.findByRole("tab", { name: "Tasks matching a filter" }));
    await userEvent.type(screen.getByLabelText("Label"), "Open launch tasks");
    await userEvent.click(screen.getByRole("radio", { name: "Count" }));
    await userEvent.click(screen.getByRole("button", { name: "Embed" }));

    await waitFor(() => expect(onClose).toHaveBeenCalled());
    const [embed] = embeds();
    expect(embed.text).toBe("Open launch tasks");
    expect(embed.display).toEqual({ mode: "count" });
    expect(embed.query).toMatchObject({ initiative_id: 7, project_id: null });
  });

  it("offers one project's metadata as columns, under whose it is", async () => {
    server.use(
      communityHttp.get("/projects/", () =>
        HttpResponse.json({
          items: [buildProject({ id: 3, name: "Launch", initiative_id: 7 })],
          total_count: 1,
          page: 1,
          page_size: 0,
          has_next: false,
          has_prev: false,
        })
      ),
      definitionsHandler([buildPropertyDefinition({ id: 12, name: "Budget" })], {
        project: [buildPropertyDefinition({ id: 14, name: "Sprint", project_id: 3 })],
      })
    );
    const onClose = vi.fn();
    renderPage(() => <Harness onClose={onClose} />);
    const user = userEvent.setup();

    await user.click(await screen.findByRole("tab", { name: "Tasks matching a filter" }));
    await user.click(screen.getByRole("combobox", { name: "From" }));
    await user.click(await screen.findByRole("option", { name: "Launch" }));
    await user.click(screen.getByRole("radio", { name: "Table" }));

    const metadata = await screen.findByRole("group", { name: "This project's metadata" });
    await user.click(within(metadata).getByRole("checkbox", { name: "Sprint" }));
    expect(
      within(screen.getByRole("group", { name: "Initiative properties" })).getByRole("checkbox", {
        name: "Budget",
      })
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Embed" }));

    await waitFor(() => expect(onClose).toHaveBeenCalled());
    const [embed] = embeds();
    expect(embed.query).toMatchObject({ initiative_id: 7, project_id: 3 });
    expect((embed.display as { columns: string[] }).columns).toContain("property:14");
  });
});
