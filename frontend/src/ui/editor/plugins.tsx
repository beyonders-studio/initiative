import { useLexicalComposerContext } from "@lexical/react/LexicalComposerContext";
import { TabIndentationPlugin } from "@lexical/react/LexicalTabIndentationPlugin";
import { TablePlugin } from "@lexical/react/LexicalTablePlugin";
import { useExtensionDependency } from "@lexical/react/useExtensionComponent";
import { type ReactNode, type RefObject, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { ContentEditable } from "@/ui/editor/editor-ui/content-editable";
import { ImagesExtension } from "@/ui/editor/extensions/images-extension";
import { MarkdownShortcutsExtension } from "@/ui/editor/extensions/markdown-shortcuts-extension";
import { ActionsPlugin } from "@/ui/editor/plugins/actions/actions-plugin";
import { CharacterLimitPlugin } from "@/ui/editor/plugins/actions/character-limit-plugin";
import { ClearEditorActionPlugin } from "@/ui/editor/plugins/actions/clear-editor-plugin";
import { CounterCharacterPlugin } from "@/ui/editor/plugins/actions/counter-character-plugin";
import { EditModeTogglePlugin } from "@/ui/editor/plugins/actions/edit-mode-toggle-plugin";
import { ImportExportPlugin } from "@/ui/editor/plugins/actions/import-export-plugin";
import { MarkdownTogglePlugin } from "@/ui/editor/plugins/actions/markdown-toggle-plugin";
import { SpeechToTextPlugin } from "@/ui/editor/plugins/actions/speech-to-text-plugin";
import { TreeViewPlugin } from "@/ui/editor/plugins/actions/tree-view-plugin";
import { CalloutActionMenuPlugin } from "@/ui/editor/plugins/callout-action-menu-plugin";
import { CodeActionMenuPlugin } from "@/ui/editor/plugins/code-action-menu-plugin";
import { ComponentPickerMenuPlugin } from "@/ui/editor/plugins/component-picker-menu-plugin";
import { ContextMenuPlugin } from "@/ui/editor/plugins/context-menu-plugin";
import { DragDropPastePlugin } from "@/ui/editor/plugins/drag-drop-paste-plugin";
import { DraggableBlockPlugin } from "@/ui/editor/plugins/draggable-block-plugin";
import { AutoEmbedPlugin } from "@/ui/editor/plugins/embeds/auto-embed-plugin";
import { TwitterPlugin } from "@/ui/editor/plugins/embeds/twitter-plugin";
import { YouTubePlugin } from "@/ui/editor/plugins/embeds/youtube-plugin";
import { EmojiPickerPlugin } from "@/ui/editor/plugins/emoji-picker-plugin";
import { FloatingLinkEditorPlugin } from "@/ui/editor/plugins/floating-link-editor-plugin";
import { FloatingTextFormatToolbarPlugin } from "@/ui/editor/plugins/floating-text-format-plugin";
import { LegacyNodesPlugin } from "@/ui/editor/plugins/legacy-nodes-plugin";
import { MermaidPreviewPlugin } from "@/ui/editor/plugins/mermaid-preview-plugin";
import { AlignmentPickerPlugin } from "@/ui/editor/plugins/picker/alignment-picker-plugin";
import { BulletedListPickerPlugin } from "@/ui/editor/plugins/picker/bulleted-list-picker-plugin";
import { CalloutPickerPlugins } from "@/ui/editor/plugins/picker/callout-picker-plugin";
import { CheckListPickerPlugin } from "@/ui/editor/plugins/picker/check-list-picker-plugin";
import { CodePickerPlugin } from "@/ui/editor/plugins/picker/code-picker-plugin";
import { ColumnsLayoutPickerPlugin } from "@/ui/editor/plugins/picker/columns-layout-picker-plugin";
import type { ComponentPickerOption } from "@/ui/editor/plugins/picker/component-picker-option";
import { DiagramPickerPlugin } from "@/ui/editor/plugins/picker/diagram-picker-plugin";
import { DividerPickerPlugin } from "@/ui/editor/plugins/picker/divider-picker-plugin";
import { DrawingPickerPlugin } from "@/ui/editor/plugins/picker/drawing-picker-plugin";
import { EmbedsPickerPlugin } from "@/ui/editor/plugins/picker/embeds-picker-plugin";
import { HeadingPickerPlugin } from "@/ui/editor/plugins/picker/heading-picker-plugin";
import { ImagePickerPlugin } from "@/ui/editor/plugins/picker/image-picker-plugin";
import { NumberedListPickerPlugin } from "@/ui/editor/plugins/picker/numbered-list-picker-plugin";
import { ParagraphPickerPlugin } from "@/ui/editor/plugins/picker/paragraph-picker-plugin";
import { QuotePickerPlugin } from "@/ui/editor/plugins/picker/quote-picker-plugin";
import { StatusPickerPlugin } from "@/ui/editor/plugins/picker/status-picker-plugin";
import {
  DynamicTablePickerPlugin,
  TablePickerPlugin,
} from "@/ui/editor/plugins/picker/table-picker-plugin";
import { TabFocusPlugin } from "@/ui/editor/plugins/tab-focus-plugin";
import { TableActionMenuPlugin } from "@/ui/editor/plugins/table-action-menu-plugin";
import { BlockFormatDropDown } from "@/ui/editor/plugins/toolbar/block-format-toolbar-plugin";
import { BlockInsertPlugin } from "@/ui/editor/plugins/toolbar/block-insert-plugin";
import { ClearFormattingToolbarPlugin } from "@/ui/editor/plugins/toolbar/clear-formatting-toolbar-plugin";
import { CodeLanguageToolbarPlugin } from "@/ui/editor/plugins/toolbar/code-language-toolbar-plugin";
import { ElementFormatToolbarPlugin } from "@/ui/editor/plugins/toolbar/element-format-toolbar-plugin";
import { FontBackgroundToolbarPlugin } from "@/ui/editor/plugins/toolbar/font-background-toolbar-plugin";
import { FontColorToolbarPlugin } from "@/ui/editor/plugins/toolbar/font-color-toolbar-plugin";
import { FontFormatToolbarPlugin } from "@/ui/editor/plugins/toolbar/font-format-toolbar-plugin";
import { FontSizeToolbarPlugin } from "@/ui/editor/plugins/toolbar/font-size-toolbar-plugin";
import { HistoryToolbarPlugin } from "@/ui/editor/plugins/toolbar/history-toolbar-plugin";
import { LinkToolbarPlugin } from "@/ui/editor/plugins/toolbar/link-toolbar-plugin";
import { SubSuperToolbarPlugin } from "@/ui/editor/plugins/toolbar/subsuper-toolbar-plugin";
import {
  BLOCK_FORMAT_ORDER,
  type BlockFormatType,
  type InsertAction,
} from "@/ui/editor/plugins/toolbar/toolbar-actions";
import {
  BlockFormatMenuItems,
  BlockInsertMenuItems,
  ClearFormattingMenuItem,
  CodeLanguageMenuItems,
  ElementFormatMenuItems,
  FontBackgroundMenuItems,
  FontColorMenuItems,
  FontFormatMenuItems,
  FontSizeMenuItems,
  HistoryMenuItems,
  LinkMenuItem,
  SubSuperMenuItems,
} from "@/ui/editor/plugins/toolbar/toolbar-menu-items";
import { ToolbarPlugin } from "@/ui/editor/plugins/toolbar/toolbar-plugin";
import type { EditorVariant } from "@/ui/editor/variant";
import { cn } from "@/ui/lib/utils";
import { OverflowToolbar, type OverflowToolbarItem } from "@/ui/overflow-toolbar";

const placeholder = "Press / for commands...";

/** The block types a document offers — everything but the deeper headings. */
const DOCUMENT_BLOCK_TYPES: readonly BlockFormatType[] = BLOCK_FORMAT_ORDER;

/**
 * The row of controls over a document.
 *
 * One row, written once. What it can hold is a question about the editor's own
 * width — a document open beside the sidebar is narrower than the window says —
 * so the controls that no longer fit shed into a named menu at its end instead
 * of the row being swapped wholesale at a viewport breakpoint.
 *
 * Order is load-bearing, because the row sheds from the right: undo and the
 * block type are the last to go.
 */
function DocumentToolbar({
  blockType,
  variant,
  insertActions,
  setIsLinkEditMode,
}: {
  blockType: string;
  variant: EditorVariant;
  insertActions: readonly InsertAction[];
  setIsLinkEditMode: (value: boolean) => void;
}) {
  const { t } = useTranslation("editor");
  // The typesetting half of the toolbar. A document is a place to typeset; a
  // notice is a place to say something, so it gets the writing controls and
  // not the layout ones.
  const rich = variant === "document";
  const insert = { rich, hostActions: insertActions };

  const items: OverflowToolbarItem[] = [
    { id: "history", node: <HistoryToolbarPlugin />, menu: <HistoryMenuItems /> },
    {
      id: "blockFormat",
      startsGroup: true,
      node: <BlockFormatDropDown types={DOCUMENT_BLOCK_TYPES} />,
      menu: <BlockFormatMenuItems types={DOCUMENT_BLOCK_TYPES} />,
    },
  ];

  if (blockType === "code") {
    // Inside a code block there is nothing to typeset — only which language it
    // is written in.
    items.push({
      id: "codeLanguage",
      startsGroup: true,
      node: <CodeLanguageToolbarPlugin />,
      menu: <CodeLanguageMenuItems />,
    });
  } else {
    if (rich) {
      items.push({
        id: "fontSize",
        startsGroup: true,
        node: <FontSizeToolbarPlugin />,
        menu: <FontSizeMenuItems />,
      });
    }

    items.push({
      id: "fontFormat",
      startsGroup: true,
      node: <FontFormatToolbarPlugin />,
      menu: <FontFormatMenuItems />,
    });
    if (rich) {
      items.push({
        id: "subSuper",
        node: <SubSuperToolbarPlugin />,
        menu: <SubSuperMenuItems />,
      });
    }
    items.push({
      id: "link",
      startsGroup: !rich,
      node: <LinkToolbarPlugin setIsLinkEditMode={setIsLinkEditMode} />,
      menu: <LinkMenuItem setIsLinkEditMode={setIsLinkEditMode} />,
    });

    // Clearing formatting, the colours and aligning are one-in-a-hundred on a
    // notice, so there they live in the menu however wide the composer gets
    // rather than costing a button above every one. On a document they take
    // their turn in the row like everything else.
    items.push({
      id: "clearFormatting",
      startsGroup: true,
      menuOnly: !rich,
      node: <ClearFormattingToolbarPlugin />,
      menu: <ClearFormattingMenuItem />,
    });
    if (rich) {
      items.push(
        {
          id: "fontColor",
          startsGroup: true,
          node: <FontColorToolbarPlugin />,
          menu: <FontColorMenuItems />,
        },
        {
          id: "fontBackground",
          node: <FontBackgroundToolbarPlugin />,
          menu: <FontBackgroundMenuItems />,
        }
      );
    }
    items.push({
      id: "elementFormat",
      startsGroup: true,
      menuOnly: !rich,
      node: <ElementFormatToolbarPlugin />,
      menu: <ElementFormatMenuItems />,
    });

    items.push({
      id: "blockInsert",
      startsGroup: true,
      node: <BlockInsertPlugin {...insert} />,
      menu: <BlockInsertMenuItems {...insert} />,
    });
  }

  // The spreadsheet toolbar's tint (`muted` at 20%), mixed onto the page rather
  // than laid over it: this bar and the actions bar below stick over scrolled
  // text, so both have to be opaque. A full `bg-muted` bar is the same colour as
  // a pressed button's `bg-accent`, which left bold, italic and the rest with no
  // visible on state.
  return (
    <OverflowToolbar
      data-editor-toolbar
      items={items}
      label={t("format")}
      moreLabel={t("moreFormatting")}
      className="vertical-align-middle sticky top-0 z-10 gap-2 border-b bg-[color-mix(in_oklab,var(--muted)_20%,var(--background))] p-1"
      rowClassName="gap-2"
    />
  );
}

export function Plugins({
  showToolbar = true,
  readOnly = false,
  collaborative = false,
  cursorsContainerRef,
  variant = "document",
  maxLength,
  compact = false,
  plugins,
  pickerOptions = [],
  insertActions = [],
  selectionActions,
}: {
  showToolbar?: boolean;
  readOnly?: boolean;
  collaborative?: boolean;
  cursorsContainerRef?: RefObject<HTMLDivElement>;
  /** Which surface this is. `post` narrows the toolbar to what writing a
   *  notice needs — see `EditorVariant`. */
  variant?: EditorVariant;
  /** Characters a body may hold, shown as a remaining count. The server is
   *  still the authority; this is so nobody writes past the limit unaware. */
  maxLength?: number;
  /** The container already supplies the horizontal gutter — a post rendered
   *  in a card on the board, say — so the editor takes none of its own.
   *
   *  Deliberately not derived from `readOnly`: a post's own page renders it
   *  read-only for anyone without write access, and there the body must sit at
   *  the same offset a writer sees, not shift left because of who is looking.
   *  Height is a separate question and does follow `readOnly`. */
  compact?: boolean;
  /** The host's behaviours, mounted with the core's, given the element the
   *  floating menus are drawn in. */
  plugins?: (anchorElem: HTMLDivElement | null) => ReactNode;
  /** What the host adds to the `/` menu, after the core's inserts. */
  pickerOptions?: readonly ComponentPickerOption[];
  /** What the host adds to the toolbar's Insert menu, after the core's. */
  insertActions?: readonly InsertAction[];
  /** What the host adds to the toolbar over a selection. */
  selectionActions?: ReactNode;
}) {
  const { t } = useTranslation("editor");
  const [editor] = useLexicalComposerContext();
  // The typesetting half of the toolbar. A document is a place to typeset; a
  // notice is a place to say something, so it gets the writing controls and
  // not the layout ones.
  const rich = variant === "document";
  const [floatingAnchorElem, setFloatingAnchorElem] = useState<HTMLDivElement | null>(null);
  const transformers = useExtensionDependency(MarkdownShortcutsExtension).output;
  const insertImage = useExtensionDependency(ImagesExtension).config.insert;
  const [isLinkEditMode, setIsLinkEditMode] = useState<boolean>(false);

  // Enforce read-only mode
  useEffect(() => {
    editor.setEditable(!readOnly);
  }, [editor, readOnly]);

  const onRef = (_floatingAnchorElem: HTMLDivElement) => {
    if (_floatingAnchorElem !== null) {
      setFloatingAnchorElem(_floatingAnchorElem);
    }
  };

  return (
    // A column that fills the editor's scrollport (which has a definite height
    // only in fullscreen; elsewhere `min-h-full` resolves to auto and this is a
    // plain block). The content region below grows into the leftover space so
    // the actions bar's `sticky bottom-0` has somewhere to stick to even when
    // the document is shorter than the viewport.
    <div className="relative flex min-h-full flex-col">
      {/* `data-editor-toolbar` marks what sits over the top of the scrollport:
          it sticks there, so anything scrolled to has to clear it. Measured
          rather than assumed, because the row's height follows its contents. */}
      {showToolbar && (
        <ToolbarPlugin>
          {({ blockType }) => (
            <DocumentToolbar
              blockType={blockType}
              variant={variant}
              insertActions={insertActions}
              setIsLinkEditMode={setIsLinkEditMode}
            />
          )}
        </ToolbarPlugin>
      )}
      <div className="relative grow">
        <div className="relative">
          {/* Horizontal padding lives on this wrapper, not the ContentEditable root:
              lexical 0.45 writes an inline `padding-inline-start` on the editable
              (from node indent) which would override a `px-*` class to 0. Its guard
              is `indent === 0`, but our nodes' __indent is `undefined`, so it emits
              `calc(undefined * ...)`. Revisit (move padding back) once lexical fixes
              the guard — expected in 0.46. */}
          {/* The writing gutter. A body whose container already pads it —
              a post in a card on the board — takes none of its own. */}
          <div className={cn(compact ? "px-0" : "px-8")} ref={onRef}>
            <ContentEditable
              placeholder={placeholder}
              className={cn(
                "ContentEditable__root relative block focus:outline-none",
                // A writing surface reserves a page to write on. A notice being
                // *read* is only as tall as what it says — a floor would put an
                // empty half-screen under every two-line post, on the board and
                // on its own page alike.
                variant === "post" && readOnly ? "py-2" : "min-h-72 pt-4 pb-14"
              )}
            />
          </div>
          {collaborative && <div ref={cursorsContainerRef} className="collaboration-cursors" />}
        </div>

        <TablePlugin hasCellMerge hasCellBackgroundColor />
        {/* Everything from here to the picker below is an editing affordance —
            a drag handle, a typeahead, a hover menu. None of it renders any of
            the document, and a read-only view mounts one of these per card on
            a board. Left mounted it was the largest thing a post cost to
            scroll past. What is NOT gated is what a reader needs: the nodes
            themselves and link sanitizing. The host gates its own plugins. */}
        {!readOnly && <TableActionMenuPlugin anchorElem={floatingAnchorElem} readOnly={readOnly} />}
        {!readOnly && <CalloutActionMenuPlugin anchorElem={floatingAnchorElem} />}
        {!readOnly && <TabIndentationPlugin />}

        <LegacyNodesPlugin />
        {/* Ungated: a reader needs the diagram more than a writer does. */}
        <MermaidPreviewPlugin />
        {plugins?.(floatingAnchorElem)}
        {!readOnly && <DraggableBlockPlugin anchorElem={floatingAnchorElem} />}

        {/* Turns a pasted URL into an embed. The embed NODES render without
            it; this is the conversion, which only an editor does. */}
        {!readOnly && <AutoEmbedPlugin />}
        <TwitterPlugin />
        <YouTubePlugin />

        {!readOnly && <CodeActionMenuPlugin anchorElem={floatingAnchorElem} />}

        {!readOnly && <TabFocusPlugin />}

        {!readOnly && (
          <ComponentPickerMenuPlugin
            baseOptions={[
              ParagraphPickerPlugin(),
              HeadingPickerPlugin({ n: 1 }),
              HeadingPickerPlugin({ n: 2 }),
              HeadingPickerPlugin({ n: 3 }),
              TablePickerPlugin(),
              CheckListPickerPlugin(),
              NumberedListPickerPlugin(),
              BulletedListPickerPlugin(),
              QuotePickerPlugin(),
              ...CalloutPickerPlugins(t),
              CodePickerPlugin(),
              DividerPickerPlugin(),
              EmbedsPickerPlugin({ embed: "tweet" }),
              EmbedsPickerPlugin({ embed: "youtube-video" }),
              ...(insertImage ? [ImagePickerPlugin(insertImage)] : []),
              DrawingPickerPlugin(t),
              DiagramPickerPlugin(t),
              StatusPickerPlugin(t),
              ...pickerOptions,
              ColumnsLayoutPickerPlugin(),
              AlignmentPickerPlugin({ alignment: "left" }),
              AlignmentPickerPlugin({ alignment: "center" }),
              AlignmentPickerPlugin({ alignment: "right" }),
              AlignmentPickerPlugin({ alignment: "justify" }),
            ]}
            dynamicOptionsFn={DynamicTablePickerPlugin}
          />
        )}

        {!readOnly && <ContextMenuPlugin />}
        {!readOnly && <DragDropPastePlugin />}
        {!readOnly && <EmojiPickerPlugin />}

        <FloatingLinkEditorPlugin
          anchorElem={floatingAnchorElem}
          isLinkEditMode={isLinkEditMode}
          setIsLinkEditMode={setIsLinkEditMode}
        />
        <FloatingTextFormatToolbarPlugin
          anchorElem={floatingAnchorElem}
          setIsLinkEditMode={setIsLinkEditMode}
          actions={selectionActions}
        />
      </div>
      {showToolbar && (
        <ActionsPlugin>
          {/* The same fill as the toolbar above, for the same reasons. */}
          <div className="sticky bottom-0 z-10 clear-both flex items-center justify-between gap-2 overflow-auto border-t bg-[color-mix(in_oklab,var(--muted)_20%,var(--background))] p-1">
            <div className="flex flex-1 justify-start"></div>
            <div>
              {/* With a limit, what matters is how much is left; without one,
                  how much there is. */}
              {maxLength !== undefined ? (
                <CharacterLimitPlugin maxLength={maxLength} charset="UTF-16" />
              ) : (
                <CounterCharacterPlugin charset="UTF-16" />
              )}
            </div>
            <div className="flex flex-1 justify-end">
              {/* A notice keeps the count and nothing else. Importing a file,
                  toggling to Markdown source, switching to read-only and
                  clearing the whole body are document tools — on a board they
                  are five buttons under a paragraph nobody asked to typeset. */}
              {rich && (
                <>
                  <SpeechToTextPlugin />
                  <ImportExportPlugin />
                  <MarkdownTogglePlugin transformers={transformers} />
                  <EditModeTogglePlugin forceReadOnly={readOnly} />
                  <ClearEditorActionPlugin />
                  <TreeViewPlugin />
                </>
              )}
            </div>
          </div>
        </ActionsPlugin>
      )}
    </div>
  );
}
