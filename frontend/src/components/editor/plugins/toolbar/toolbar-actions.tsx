import { $createCodeNode, $isCodeNode } from "@lexical/code";
import { CODE_LANGUAGE_FRIENDLY_NAME_MAP } from "@lexical/code-prism";
import { INSERT_HORIZONTAL_RULE_COMMAND } from "@lexical/extension";
import { $isLinkNode, TOGGLE_LINK_COMMAND } from "@lexical/link";
import {
  $isListNode,
  INSERT_CHECK_LIST_COMMAND,
  INSERT_ORDERED_LIST_COMMAND,
  INSERT_UNORDERED_LIST_COMMAND,
} from "@lexical/list";
import { INSERT_EMBED_COMMAND } from "@lexical/react/LexicalAutoEmbedPlugin";
import { useLexicalComposerContext } from "@lexical/react/LexicalComposerContext";
import { $isDecoratorBlockNode } from "@lexical/react/LexicalDecoratorBlockNode";
import {
  $createHeadingNode,
  $createQuoteNode,
  $isHeadingNode,
  $isQuoteNode,
} from "@lexical/rich-text";
import { $patchStyleText, $setBlocksType } from "@lexical/selection";
import { $isTableSelection } from "@lexical/table";
import {
  $findMatchingParent,
  $getNearestBlockElementAncestorOrThrow,
  mergeRegister,
} from "@lexical/utils";
import {
  $createParagraphNode,
  $getSelection,
  $isRangeSelection,
  $isRootOrShadowRoot,
  $isTextNode,
  CAN_REDO_COMMAND,
  CAN_UNDO_COMMAND,
  COMMAND_PRIORITY_CRITICAL,
  FORMAT_ELEMENT_COMMAND,
  FORMAT_TEXT_COMMAND,
  INDENT_CONTENT_COMMAND,
  OUTDENT_CONTENT_COMMAND,
  REDO_COMMAND,
  type TextFormatType,
  UNDO_COMMAND,
} from "lexical";
import {
  AlignCenterIcon,
  AlignJustifyIcon,
  AlignLeftIcon,
  AlignRightIcon,
  BoldIcon,
  Columns3Icon,
  ImageIcon,
  IndentDecreaseIcon,
  IndentIncreaseIcon,
  ItalicIcon,
  PanelTop,
  PenTool,
  RectangleEllipsis,
  ScissorsIcon,
  StrikethroughIcon,
  SubscriptIcon,
  SuperscriptIcon,
  TableIcon,
  Tag,
  UnderlineIcon,
} from "lucide-react";
import { type ReactNode, useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { useToolbarContext } from "@/components/editor/context/toolbar-context";
import { INSERT_CALLOUT_COMMAND } from "@/components/editor/extensions/callout-extension";
import { INSERT_EXCALIDRAW_COMMAND } from "@/components/editor/extensions/excalidraw-extension";
import { INSERT_STATUS_COMMAND } from "@/components/editor/extensions/status-extension";
import { CalloutIcon } from "@/components/editor/plugins/callout-icon";
import { EmbedConfigs } from "@/components/editor/plugins/embeds/auto-embed-plugin";
import { InsertImageDialog } from "@/components/editor/plugins/images-plugin";
import { InsertLayoutDialog } from "@/components/editor/plugins/layout-plugin";
import { LazyEmbedDialog } from "@/components/editor/plugins/lazy-embed-dialog";
import { MERMAID_LANGUAGE } from "@/components/editor/plugins/mermaid-preview-plugin";
import { SmartChipInsertDialog } from "@/components/editor/plugins/smart-chip-insert-dialog";
import { InsertTableDialog } from "@/components/editor/plugins/table-plugin";
import { useBlockTypeToBlockName } from "@/components/editor/plugins/toolbar/block-format/block-format-data";
import { getSelectedNode } from "@/components/editor/utils/get-selected-node";
import { sanitizeUrl } from "@/ui/lib/safeUrl";

/**
 * One thing the toolbar can do, as data rather than as a rendered control.
 *
 * It has to be data because the same action is placed two ways: as a button or
 * a dropdown entry in the row while it fits, and as a labelled menu entry once
 * the row has shed it. Everything here is consumed by both.
 */
export interface EditorAction {
  id: string;
  label: string;
  icon: ReactNode;
  run: () => void;
  /** Whether the selection already carries this, where that is meaningful. */
  active?: boolean;
}

/** A named colour a swatch list offers. An empty value clears the property. */
export interface EditorSwatch {
  label: string;
  value: string;
}

/** The block types a body can be set to, in the order the picker offers them. */
export const BLOCK_FORMAT_ORDER = [
  "paragraph",
  "h1",
  "h2",
  "h3",
  "number",
  "bullet",
  "check",
  "code",
  "quote",
] as const;

export type BlockFormatType = (typeof BLOCK_FORMAT_ORDER)[number];

export const useBlockFormatActions = (types: readonly BlockFormatType[]): EditorAction[] => {
  const names = useBlockTypeToBlockName();
  const { activeEditor, blockType, setBlockType } = useToolbarContext();

  const toParagraph = useCallback(() => {
    activeEditor.update(() => {
      const selection = $getSelection();
      if ($isRangeSelection(selection)) {
        $setBlocksType(selection, () => $createParagraphNode());
      }
    });
  }, [activeEditor]);

  const apply = (type: BlockFormatType) => {
    if (type === blockType) {
      // Picking the type a block already is turns it off, so a list or a quote
      // has a way back to plain text without a second control.
      if (type !== "paragraph") toParagraph();
      return;
    }
    setBlockType(type);
    switch (type) {
      case "paragraph":
        toParagraph();
        return;
      case "h1":
      case "h2":
      case "h3":
        activeEditor.update(() => {
          const selection = $getSelection();
          $setBlocksType(selection, () => $createHeadingNode(type));
        });
        return;
      case "number":
        activeEditor.dispatchCommand(INSERT_ORDERED_LIST_COMMAND, undefined);
        return;
      case "bullet":
        activeEditor.dispatchCommand(INSERT_UNORDERED_LIST_COMMAND, undefined);
        return;
      case "check":
        activeEditor.dispatchCommand(INSERT_CHECK_LIST_COMMAND, undefined);
        return;
      case "quote":
        activeEditor.update(() => {
          const selection = $getSelection();
          $setBlocksType(selection, () => $createQuoteNode());
        });
        return;
      case "code":
        activeEditor.update(() => {
          let selection = $getSelection();
          if (selection === null) return;
          if (selection.isCollapsed()) {
            $setBlocksType(selection, () => $createCodeNode());
            return;
          }
          const textContent = selection.getTextContent();
          selection.insertNodes([$createCodeNode()]);
          selection = $getSelection();
          if ($isRangeSelection(selection)) selection.insertRawText(textContent);
        });
        return;
    }
  };

  return types.map((type) => ({
    id: type,
    label: names[type].label,
    icon: names[type].icon,
    active: blockType === type,
    run: () => apply(type),
  }));
};

const TEXT_FORMATS = [
  { id: "bold", labelKey: "bold", Icon: BoldIcon },
  { id: "italic", labelKey: "italic", Icon: ItalicIcon },
  { id: "underline", labelKey: "underline", Icon: UnderlineIcon },
  { id: "strikethrough", labelKey: "strikethrough", Icon: StrikethroughIcon },
] as const;

/** The ids, for reading them off a selection. */
export const TEXT_FORMAT_IDS = TEXT_FORMATS.map((format) => format.id);

/** Bold, italic, underline and strikethrough, with what the selection has. */
export const useTextFormatActions = (activeFormats: string[]): EditorAction[] => {
  const { activeEditor } = useToolbarContext();
  const { t } = useTranslation("editor");

  return TEXT_FORMATS.map(({ id, labelKey, Icon }) => ({
    id,
    label: t(labelKey),
    icon: <Icon className="size-4" />,
    active: activeFormats.includes(id),
    run: () => activeEditor.dispatchCommand(FORMAT_TEXT_COMMAND, id as TextFormatType),
  }));
};

export const useSubSuperActions = (): EditorAction[] => {
  const { activeEditor } = useToolbarContext();
  const { t } = useTranslation("editor");

  return [
    {
      id: "subscript",
      label: t("subscript"),
      icon: <SubscriptIcon className="size-4" />,
      run: () => activeEditor.dispatchCommand(FORMAT_TEXT_COMMAND, "subscript"),
    },
    {
      id: "superscript",
      label: t("superscript"),
      icon: <SuperscriptIcon className="size-4" />,
      run: () => activeEditor.dispatchCommand(FORMAT_TEXT_COMMAND, "superscript"),
    },
  ];
};

/** Strip every style and format from the selection, back to plain body text. */
export const useClearFormatting = () => {
  const { activeEditor } = useToolbarContext();

  return useCallback(() => {
    activeEditor.update(() => {
      const selection = $getSelection();
      if (!($isRangeSelection(selection) || $isTableSelection(selection))) return;

      const anchor = selection.anchor;
      const focus = selection.focus;
      const nodes = selection.getNodes();
      const extractedNodes = selection.extract();

      if (anchor.key === focus.key && anchor.offset === focus.offset) return;

      nodes.forEach((node, index) => {
        // Split the first and last node at the selection so unselected text
        // inside them keeps what it had.
        if ($isTextNode(node)) {
          let textNode = node;
          if (index === 0 && anchor.offset !== 0) {
            textNode = textNode.splitText(anchor.offset)[1] || textNode;
          }
          if (index === nodes.length - 1) {
            textNode = textNode.splitText(focus.offset)[0] || textNode;
          }
          const extractedTextNode = extractedNodes[0];
          if (nodes.length === 1 && $isTextNode(extractedTextNode)) {
            textNode = extractedTextNode;
          }

          if (textNode.__style !== "") textNode.setStyle("");
          if (textNode.__format !== 0) {
            textNode.setFormat(0);
            $getNearestBlockElementAncestorOrThrow(textNode).setFormat("");
          }
        } else if ($isHeadingNode(node) || $isQuoteNode(node)) {
          node.replace($createParagraphNode(), true);
        } else if ($isDecoratorBlockNode(node)) {
          node.setFormat("");
        }
      });
    });
  }, [activeEditor]);
};

const ALIGNMENTS = [
  { id: "left", labelKey: "alignLeft", Icon: AlignLeftIcon },
  { id: "center", labelKey: "alignCenter", Icon: AlignCenterIcon },
  { id: "right", labelKey: "alignRight", Icon: AlignRightIcon },
  { id: "justify", labelKey: "alignJustify", Icon: AlignJustifyIcon },
] as const;

export type AlignmentType = (typeof ALIGNMENTS)[number]["id"];

/** The alignment options, and the icon standing for whichever is in force. */
export const useAlignmentActions = (current: AlignmentType): EditorAction[] => {
  const { activeEditor } = useToolbarContext();
  const { t } = useTranslation("editor");

  return ALIGNMENTS.map(({ id, labelKey, Icon }) => ({
    id,
    label: t(labelKey),
    icon: <Icon className="size-4" />,
    active: current === id,
    run: () => activeEditor.dispatchCommand(FORMAT_ELEMENT_COMMAND, id),
  }));
};

export const useIndentActions = (): EditorAction[] => {
  const { activeEditor } = useToolbarContext();
  const { t } = useTranslation("editor");

  return [
    {
      id: "indent",
      label: t("indent"),
      icon: <IndentIncreaseIcon className="size-4" />,
      run: () => activeEditor.dispatchCommand(INDENT_CONTENT_COMMAND, undefined),
    },
    {
      id: "outdent",
      label: t("outdent"),
      icon: <IndentDecreaseIcon className="size-4" />,
      run: () => activeEditor.dispatchCommand(OUTDENT_CONTENT_COMMAND, undefined),
    },
  ];
};

/** Everything the insert picker offers, gated by what this surface supports. */
export const useBlockInsertActions = ({
  rich,
  supportsSmartChips,
  initiativeId,
}: {
  rich: boolean;
  supportsSmartChips: boolean;
  initiativeId: number | null;
}): EditorAction[] => {
  const { activeEditor, showModal } = useToolbarContext();
  const { t } = useTranslation("editor");

  const actions: EditorAction[] = [];

  if (rich) {
    actions.push({
      id: "horizontal-rule",
      label: t("horizontalRule"),
      icon: <ScissorsIcon className="size-4" />,
      run: () => activeEditor.dispatchCommand(INSERT_HORIZONTAL_RULE_COMMAND, undefined),
    });
  }

  actions.push(
    {
      id: "image",
      label: t("image"),
      icon: <ImageIcon className="size-4" />,
      run: () =>
        showModal(t("insertImage"), (onClose) => (
          <InsertImageDialog activeEditor={activeEditor} onClose={onClose} />
        )),
    },
    {
      id: "table",
      label: t("table"),
      icon: <TableIcon className="size-4" />,
      run: () =>
        showModal(t("insertTable"), (onClose) => (
          <InsertTableDialog activeEditor={activeEditor} onClose={onClose} />
        )),
    }
  );

  if (rich) {
    actions.push({
      id: "status",
      label: t("status"),
      icon: <Tag className="size-4" />,
      run: () => activeEditor.dispatchCommand(INSERT_STATUS_COMMAND, undefined),
    });
    actions.push({
      id: "drawing",
      label: t("drawing"),
      icon: <PenTool className="size-4" />,
      run: () => activeEditor.dispatchCommand(INSERT_EXCALIDRAW_COMMAND, undefined),
    });
    actions.push({
      id: "callout",
      label: t("callout"),
      icon: <CalloutIcon variant="info" className="size-4" />,
      run: () => activeEditor.dispatchCommand(INSERT_CALLOUT_COMMAND, "info"),
    });
    actions.push({
      id: "columns",
      label: t("columnsLayout"),
      icon: <Columns3Icon className="size-4" />,
      run: () =>
        showModal(t("insertColumnsLayout"), (onClose) => (
          <InsertLayoutDialog activeEditor={activeEditor} onClose={onClose} />
        )),
    });
  }

  actions.push(
    ...EmbedConfigs.map((embed) => ({
      id: embed.type,
      label: embed.contentNameKey
        ? (t(embed.contentNameKey as never) as string)
        : embed.contentName,
      icon: embed.icon,
      run: () => activeEditor.dispatchCommand(INSERT_EMBED_COMMAND, embed.type),
    }))
  );

  if (supportsSmartChips) {
    actions.push({
      id: "smart-chip",
      label: t("smartChips.insert"),
      icon: <RectangleEllipsis className="size-4" />,
      run: () =>
        showModal(t("smartChips.insert"), (onClose) => (
          <SmartChipInsertDialog
            initiativeId={initiativeId}
            activeEditor={activeEditor}
            onClose={onClose}
          />
        )),
    });
    // A thing shown in full, or the tasks a filter matches — what `![[ ]]`
    // and the `/` menu's Embed make, for whoever reaches for the toolbar.
    actions.push({
      id: "reference-embed",
      label: t("embeds.insert"),
      icon: <PanelTop className="size-4" />,
      run: () =>
        showModal(t("embeds.insert"), (onClose) => (
          <LazyEmbedDialog activeEditor={activeEditor} onClose={onClose} />
        )),
    });
  }

  return actions;
};

/** The swatches the menu offers for text colour and for highlight. */
export const useColorSwatches = (): { text: EditorSwatch[]; background: EditorSwatch[] } => {
  const { t } = useTranslation("editor");

  return useMemo(
    () => ({
      text: [
        { label: t("colorDefault"), value: "" },
        { label: t("colorBlack"), value: "#000000" },
        { label: t("colorGray"), value: "#6b7280" },
        { label: t("colorRed"), value: "#ef4444" },
        { label: t("colorOrange"), value: "#f97316" },
        { label: t("colorYellow"), value: "#eab308" },
        { label: t("colorGreen"), value: "#22c55e" },
        { label: t("colorBlue"), value: "#3b82f6" },
        { label: t("colorPurple"), value: "#a855f7" },
        { label: t("colorPink"), value: "#ec4899" },
      ],
      background: [
        { label: t("colorNone"), value: "" },
        { label: t("colorGray"), value: "#f3f4f6" },
        { label: t("colorRed"), value: "#fee2e2" },
        { label: t("colorOrange"), value: "#ffedd5" },
        { label: t("colorYellow"), value: "#fef9c3" },
        { label: t("colorGreen"), value: "#dcfce7" },
        { label: t("colorBlue"), value: "#dbeafe" },
        { label: t("colorPurple"), value: "#f3e8ff" },
        { label: t("colorPink"), value: "#fce7f3" },
      ],
    }),
    [t]
  );
};

/** Paint a style property across the selection, or clear it on an empty value. */
export const useApplyStyle = () => {
  const { activeEditor } = useToolbarContext();

  return useCallback(
    (property: "color" | "background-color", value: string) => {
      activeEditor.update(() => {
        const selection = $getSelection();
        if (selection !== null) $patchStyleText(selection, { [property]: value || null });
      });
    },
    [activeEditor]
  );
};

/** The sizes the menu offers, where the row offers a stepper instead. */
export const FONT_SIZE_PRESETS = [12, 14, 16, 18, 20, 24, 32, 48] as const;

/** The languages a code block can be written in, and how to set one. */
export const useCodeLanguageActions = (): EditorAction[] => {
  const { activeEditor } = useToolbarContext();

  // Mermaid has no highlighting of its own, so it is not in Lexical's list;
  // it is offered because a block written in it is drawn as its diagram.
  const languages: Array<[string, string]> = [
    ...Object.entries(CODE_LANGUAGE_FRIENDLY_NAME_MAP),
    [MERMAID_LANGUAGE, "Mermaid"],
  ];
  return languages.map(([language, friendlyName]) => ({
    id: language,
    label: friendlyName,
    icon: null,
    run: () => {
      activeEditor.update(() => {
        const selection = $getSelection();
        if (!$isRangeSelection(selection)) return;
        const anchorNode = selection.anchor.getNode();
        const element =
          anchorNode.getKey() === "root"
            ? anchorNode
            : ($findMatchingParent(anchorNode, (node) => {
                const parent = node.getParent();
                return parent !== null && $isRootOrShadowRoot(parent);
              }) ?? anchorNode.getTopLevelElementOrThrow());
        if (!$isListNode(element) && $isCodeNode(element)) element.setLanguage(language);
      });
    },
  }));
};

/** Undo and redo, and whether there is anything to undo or redo. */
export const useHistoryActions = () => {
  const [editor] = useLexicalComposerContext();
  const { activeEditor } = useToolbarContext();
  const [isEditable, setIsEditable] = useState(editor.isEditable());
  const [canUndo, setCanUndo] = useState(false);
  const [canRedo, setCanRedo] = useState(false);

  useEffect(() => {
    return mergeRegister(
      editor.registerEditableListener(setIsEditable),
      activeEditor.registerCommand<boolean>(
        CAN_UNDO_COMMAND,
        (payload) => {
          setCanUndo(payload);
          return false;
        },
        COMMAND_PRIORITY_CRITICAL
      ),
      activeEditor.registerCommand<boolean>(
        CAN_REDO_COMMAND,
        (payload) => {
          setCanRedo(payload);
          return false;
        },
        COMMAND_PRIORITY_CRITICAL
      )
    );
  }, [activeEditor, editor]);

  return {
    undo: () => activeEditor.dispatchCommand(UNDO_COMMAND, undefined),
    redo: () => activeEditor.dispatchCommand(REDO_COMMAND, undefined),
    canUndo: canUndo && isEditable,
    canRedo: canRedo && isEditable,
  };
};

/**
 * Turn the selection into a link, or unlink it.
 *
 * Reads whether it is already a link at the moment it runs, so the same
 * callback serves the row's toggle, the menu entry and the keyboard shortcut.
 */
export const useToggleLink = (setIsLinkEditMode: (value: boolean) => void) => {
  const { activeEditor } = useToolbarContext();

  return useCallback(() => {
    let isLink = false;
    activeEditor.getEditorState().read(() => {
      const selection = $getSelection();
      if (!$isRangeSelection(selection)) return;
      const node = getSelectedNode(selection);
      isLink = $isLinkNode(node) || $isLinkNode(node.getParent());
    });

    setIsLinkEditMode(!isLink);
    activeEditor.dispatchCommand(TOGGLE_LINK_COMMAND, isLink ? null : sanitizeUrl("https://"));
  }, [activeEditor, setIsLinkEditMode]);
};

export const MIN_FONT_SIZE = 1;
export const MAX_FONT_SIZE = 72;
export const DEFAULT_FONT_SIZE = 16;

/** Set the selection's font size, clamped to what the editor accepts. */
export const useApplyFontSize = () => {
  const { activeEditor } = useToolbarContext();

  return useCallback(
    (size: number) => {
      const clamped = Math.min(Math.max(size, MIN_FONT_SIZE), MAX_FONT_SIZE);
      activeEditor.update(() => {
        const selection = $getSelection();
        if (selection !== null) $patchStyleText(selection, { "font-size": `${clamped}px` });
      });
      return clamped;
    },
    [activeEditor]
  );
};
