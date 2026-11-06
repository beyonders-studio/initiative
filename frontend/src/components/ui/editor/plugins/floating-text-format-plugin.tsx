import { $isCodeHighlightNode } from "@lexical/code";
import { $isLinkNode, TOGGLE_LINK_COMMAND } from "@lexical/link";
import { useLexicalComposerContext } from "@lexical/react/LexicalComposerContext";
import { mergeRegister } from "@lexical/utils";
import {
  $getSelection,
  $isParagraphNode,
  $isRangeSelection,
  $isTextNode,
  $onUpdate,
  COMMAND_PRIORITY_LOW,
  FORMAT_TEXT_COMMAND,
  type LexicalEditor,
  SELECTION_CHANGE_COMMAND,
} from "lexical";
import {
  BoldIcon,
  CodeIcon,
  ItalicIcon,
  LinkIcon,
  Sparkles,
  StrikethroughIcon,
  SubscriptIcon,
  SuperscriptIcon,
  UnderlineIcon,
} from "lucide-react";
import { type Dispatch, type JSX, useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useTranslation } from "react-i18next";

import { AIWriteAction } from "@/api/generated/initiativeAPI.schemas";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { AI_WRITE_COMMAND } from "@/components/ui/editor/plugins/ai-writing-plugin";
import { getDOMRangeRect } from "@/components/ui/editor/utils/get-dom-range-rect";
import { getSelectedNode } from "@/components/ui/editor/utils/get-selected-node";
import { setFloatingElemPosition } from "@/components/ui/editor/utils/set-floating-elem-position";
import { Separator } from "@/components/ui/separator";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { displayNames } from "@/lib/intl";

/** The languages a selection can be translated into, as language tags. */
const TRANSLATE_INTO = [
  "en",
  "es",
  "fr",
  "de",
  "it",
  "pt",
  "nl",
  "pl",
  "sv",
  "uk",
  "ru",
  "ar",
  "hi",
  "zh",
  "ja",
  "ko",
];

/** Writing help for the selection, from the toolbar over it. */
function AIWritingMenu({ editor }: { editor: LexicalEditor }) {
  const { t, i18n } = useTranslation("editor");
  const names = displayNames(i18n.language, { type: "language" });
  const ask = (action: AIWriteAction, language?: string) =>
    editor.dispatchCommand(AI_WRITE_COMMAND, { action, language });
  return (
    <DropdownMenu modal={false}>
      <DropdownMenuTrigger asChild>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          aria-label={t("writing.menu")}
          // Keeps the selection the help is asked about.
          onMouseDown={(event) => event.preventDefault()}
        >
          <Sparkles className="h-4 w-4" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" onCloseAutoFocus={(event) => event.preventDefault()}>
        <DropdownMenuItem onSelect={() => ask(AIWriteAction.rewrite)}>
          {t("writing.rewrite")}
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={() => ask(AIWriteAction.shorten)}>
          {t("writing.shorten")}
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={() => ask(AIWriteAction.fix)}>
          {t("writing.fix")}
        </DropdownMenuItem>
        <DropdownMenuSub>
          <DropdownMenuSubTrigger>{t("writing.translate")}</DropdownMenuSubTrigger>
          <DropdownMenuSubContent className="max-h-72 overflow-y-auto">
            {TRANSLATE_INTO.map((language) => (
              <DropdownMenuItem
                key={language}
                onSelect={() => ask(AIWriteAction.translate, language)}
              >
                {names.of(language)}
              </DropdownMenuItem>
            ))}
          </DropdownMenuSubContent>
        </DropdownMenuSub>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function FloatingTextFormat({
  editor,
  anchorElem,
  isLink,
  isBold,
  isItalic,
  isUnderline,
  isCode,
  isStrikethrough,
  isSubscript,
  isSuperscript,
  setIsLinkEditMode,
  aiWriting,
}: {
  editor: LexicalEditor;
  anchorElem: HTMLElement;
  aiWriting: boolean;
  isBold: boolean;
  isCode: boolean;
  isItalic: boolean;
  isLink: boolean;
  isStrikethrough: boolean;
  isSubscript: boolean;
  isSuperscript: boolean;
  isUnderline: boolean;
  setIsLinkEditMode: Dispatch<boolean>;
}): JSX.Element {
  const popupCharStylesEditorRef = useRef<HTMLDivElement | null>(null);

  const insertLink = useCallback(() => {
    if (!isLink) {
      setIsLinkEditMode(true);
      editor.dispatchCommand(TOGGLE_LINK_COMMAND, "https://");
    } else {
      setIsLinkEditMode(false);
      editor.dispatchCommand(TOGGLE_LINK_COMMAND, null);
    }
  }, [editor, isLink, setIsLinkEditMode]);

  function mouseMoveListener(e: MouseEvent) {
    if (popupCharStylesEditorRef?.current && (e.buttons === 1 || e.buttons === 3)) {
      if (popupCharStylesEditorRef.current.style.pointerEvents !== "none") {
        const x = e.clientX;
        const y = e.clientY;
        const elementUnderMouse = document.elementFromPoint(x, y);

        if (!popupCharStylesEditorRef.current.contains(elementUnderMouse)) {
          // Mouse is not over the target element => not a normal click, but probably a drag
          popupCharStylesEditorRef.current.style.pointerEvents = "none";
        }
      }
    }
  }
  function mouseUpListener() {
    if (popupCharStylesEditorRef?.current) {
      if (popupCharStylesEditorRef.current.style.pointerEvents !== "auto") {
        popupCharStylesEditorRef.current.style.pointerEvents = "auto";
      }
    }
  }

  // biome-ignore lint/correctness/useExhaustiveDependencies: listeners are stable closures over the ref; only re-attach when the ref identity changes
  useEffect(() => {
    if (popupCharStylesEditorRef?.current) {
      document.addEventListener("mousemove", mouseMoveListener);
      document.addEventListener("mouseup", mouseUpListener);

      return () => {
        document.removeEventListener("mousemove", mouseMoveListener);
        document.removeEventListener("mouseup", mouseUpListener);
      };
    }
  }, [popupCharStylesEditorRef]);

  const $updateTextFormatFloatingToolbar = useCallback(() => {
    const selection = $getSelection();

    const popupCharStylesEditorElem = popupCharStylesEditorRef.current;
    const nativeSelection = window.getSelection();

    if (popupCharStylesEditorElem === null) {
      return;
    }

    const rootElement = editor.getRootElement();
    if (
      selection !== null &&
      nativeSelection !== null &&
      !nativeSelection.isCollapsed &&
      rootElement?.contains(nativeSelection.anchorNode)
    ) {
      const rangeRect = getDOMRangeRect(nativeSelection, rootElement);

      setFloatingElemPosition(rangeRect, popupCharStylesEditorElem, anchorElem, isLink);
    }
  }, [editor, anchorElem, isLink]);

  useEffect(() => {
    const scrollerElem = anchorElem.parentElement;

    const update = () => {
      editor.getEditorState().read(() => {
        $updateTextFormatFloatingToolbar();
      });
    };

    window.addEventListener("resize", update);
    if (scrollerElem) {
      scrollerElem.addEventListener("scroll", update);
    }

    return () => {
      window.removeEventListener("resize", update);
      if (scrollerElem) {
        scrollerElem.removeEventListener("scroll", update);
      }
    };
  }, [editor, $updateTextFormatFloatingToolbar, anchorElem]);

  useEffect(() => {
    editor.getEditorState().read(() => {
      $updateTextFormatFloatingToolbar();
    });
    return mergeRegister(
      editor.registerUpdateListener(({ editorState }) => {
        editorState.read(() => {
          $updateTextFormatFloatingToolbar();
        });
      }),

      editor.registerCommand(
        SELECTION_CHANGE_COMMAND,
        () => {
          $onUpdate(() => editor.read("latest", $updateTextFormatFloatingToolbar));
          return false;
        },
        COMMAND_PRIORITY_LOW
      )
    );
  }, [editor, $updateTextFormatFloatingToolbar]);

  return (
    <div
      ref={popupCharStylesEditorRef}
      className="absolute top-0 left-0 flex gap-1 rounded-md border bg-background p-1 opacity-0 shadow-md transition-opacity duration-300 will-change-transform"
    >
      {editor.isEditable() && (
        <>
          <ToggleGroup
            type="multiple"
            defaultValue={[
              isBold ? "bold" : "",
              isItalic ? "italic" : "",
              isUnderline ? "underline" : "",
              isStrikethrough ? "strikethrough" : "",
              isSubscript ? "subscript" : "",
              isSuperscript ? "superscript" : "",
              isCode ? "code" : "",
              isLink ? "link" : "",
            ]}
          >
            <ToggleGroupItem
              value="bold"
              aria-label="Toggle bold"
              onClick={() => {
                editor.dispatchCommand(FORMAT_TEXT_COMMAND, "bold");
              }}
              size="sm"
            >
              <BoldIcon className="h-4 w-4" />
            </ToggleGroupItem>
            <ToggleGroupItem
              value="italic"
              aria-label="Toggle italic"
              onClick={() => {
                editor.dispatchCommand(FORMAT_TEXT_COMMAND, "italic");
              }}
              size="sm"
            >
              <ItalicIcon className="h-4 w-4" />
            </ToggleGroupItem>
            <ToggleGroupItem
              value="underline"
              aria-label="Toggle underline"
              onClick={() => {
                editor.dispatchCommand(FORMAT_TEXT_COMMAND, "underline");
              }}
              size="sm"
            >
              <UnderlineIcon className="h-4 w-4" />
            </ToggleGroupItem>
            <ToggleGroupItem
              value="strikethrough"
              aria-label="Toggle strikethrough"
              onClick={() => {
                editor.dispatchCommand(FORMAT_TEXT_COMMAND, "strikethrough");
              }}
              size="sm"
            >
              <StrikethroughIcon className="h-4 w-4" />
            </ToggleGroupItem>
            <Separator orientation="vertical" />
            <ToggleGroupItem
              value="code"
              aria-label="Toggle code"
              onClick={() => {
                editor.dispatchCommand(FORMAT_TEXT_COMMAND, "code");
              }}
              size="sm"
            >
              <CodeIcon className="h-4 w-4" />
            </ToggleGroupItem>
            <ToggleGroupItem value="link" aria-label="Toggle link" onClick={insertLink} size="sm">
              <LinkIcon className="h-4 w-4" />
            </ToggleGroupItem>
            <Separator orientation="vertical" />
          </ToggleGroup>
          <ToggleGroup
            type="single"
            defaultValue={isSubscript ? "subscript" : isSuperscript ? "superscript" : ""}
          >
            <ToggleGroupItem
              value="subscript"
              aria-label="Toggle subscript"
              onClick={() => {
                editor.dispatchCommand(FORMAT_TEXT_COMMAND, "subscript");
              }}
              size="sm"
            >
              <SubscriptIcon className="h-4 w-4" />
            </ToggleGroupItem>
            <ToggleGroupItem
              value="superscript"
              aria-label="Toggle superscript"
              onClick={() => {
                editor.dispatchCommand(FORMAT_TEXT_COMMAND, "superscript");
              }}
              size="sm"
            >
              <SuperscriptIcon className="h-4 w-4" />
            </ToggleGroupItem>
          </ToggleGroup>
          {aiWriting ? (
            <>
              <Separator orientation="vertical" />
              <AIWritingMenu editor={editor} />
            </>
          ) : null}
        </>
      )}
    </div>
  );
}

function useFloatingTextFormatToolbar(
  editor: LexicalEditor,
  anchorElem: HTMLDivElement | null,
  setIsLinkEditMode: Dispatch<boolean>,
  aiWriting: boolean
): JSX.Element | null {
  const [isText, setIsText] = useState(false);
  const [isLink, setIsLink] = useState(false);
  const [isBold, setIsBold] = useState(false);
  const [isItalic, setIsItalic] = useState(false);
  const [isUnderline, setIsUnderline] = useState(false);
  const [isStrikethrough, setIsStrikethrough] = useState(false);
  const [isSubscript, setIsSubscript] = useState(false);
  const [isSuperscript, setIsSuperscript] = useState(false);
  const [isCode, setIsCode] = useState(false);

  const updatePopup = useCallback(() => {
    editor.getEditorState().read(() => {
      // Should not to pop up the floating toolbar when using IME input
      if (editor.isComposing()) {
        return;
      }
      const selection = $getSelection();
      const nativeSelection = window.getSelection();
      const rootElement = editor.getRootElement();

      if (
        nativeSelection !== null &&
        (!$isRangeSelection(selection) ||
          rootElement === null ||
          !rootElement.contains(nativeSelection.anchorNode))
      ) {
        setIsText(false);
        return;
      }

      if (!$isRangeSelection(selection)) {
        return;
      }

      const node = getSelectedNode(selection);

      // Update text format
      setIsBold(selection.hasFormat("bold"));
      setIsItalic(selection.hasFormat("italic"));
      setIsUnderline(selection.hasFormat("underline"));
      setIsStrikethrough(selection.hasFormat("strikethrough"));
      setIsSubscript(selection.hasFormat("subscript"));
      setIsSuperscript(selection.hasFormat("superscript"));
      setIsCode(selection.hasFormat("code"));

      // Update links
      const parent = node.getParent();
      if ($isLinkNode(parent) || $isLinkNode(node)) {
        setIsLink(true);
      } else {
        setIsLink(false);
      }

      if (!$isCodeHighlightNode(selection.anchor.getNode()) && selection.getTextContent() !== "") {
        setIsText($isTextNode(node) || $isParagraphNode(node));
      } else {
        setIsText(false);
      }

      const rawTextContent = selection.getTextContent().replace(/\n/g, "");
      if (!selection.isCollapsed() && rawTextContent === "") {
        setIsText(false);
        return;
      }
    });
  }, [editor]);

  useEffect(() => {
    document.addEventListener("selectionchange", updatePopup);
    return () => {
      document.removeEventListener("selectionchange", updatePopup);
    };
  }, [updatePopup]);

  useEffect(() => {
    return mergeRegister(
      editor.registerUpdateListener(() => {
        updatePopup();
      }),
      editor.registerRootListener(() => {
        if (editor.getRootElement() === null) {
          setIsText(false);
        }
      })
    );
  }, [editor, updatePopup]);

  if (!isText || !anchorElem) {
    return null;
  }

  return createPortal(
    <FloatingTextFormat
      editor={editor}
      anchorElem={anchorElem}
      isLink={isLink}
      isBold={isBold}
      isItalic={isItalic}
      isStrikethrough={isStrikethrough}
      isSubscript={isSubscript}
      isSuperscript={isSuperscript}
      isUnderline={isUnderline}
      isCode={isCode}
      setIsLinkEditMode={setIsLinkEditMode}
      aiWriting={aiWriting}
    />,
    anchorElem
  );
}

export function FloatingTextFormatToolbarPlugin({
  anchorElem,
  setIsLinkEditMode,
  aiWriting = false,
}: {
  anchorElem: HTMLDivElement | null;
  setIsLinkEditMode: Dispatch<boolean>;
  /** Whether to offer writing help on the selection. */
  aiWriting?: boolean;
}): JSX.Element | null {
  const [editor] = useLexicalComposerContext();

  return useFloatingTextFormatToolbar(editor, anchorElem, setIsLinkEditMode, aiWriting);
}
