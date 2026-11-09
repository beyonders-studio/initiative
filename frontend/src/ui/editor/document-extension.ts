import { CodeExtension } from "@lexical/code";
import { CodePrismExtension } from "@lexical/code-prism";
import {
  AutoFocusExtension,
  ClearEditorExtension,
  DecoratorTextExtension,
  HorizontalRuleExtension,
  SelectionAlwaysOnDisplayExtension,
} from "@lexical/extension";
import { HistoryExtension } from "@lexical/history";
import {
  AutoLinkExtension,
  ClickableLinkExtension,
  createLinkMatcherWithRegExp,
  LinkExtension,
} from "@lexical/link";
import { CheckListExtension, ListExtension } from "@lexical/list";
import { OverflowNode } from "@lexical/overflow";
import { RichTextExtension } from "@lexical/rich-text";
import { TableCellNode, TableNode, TableRowNode } from "@lexical/table";
import {
  type AnyLexicalExtension,
  configExtension,
  defineExtension,
  type InitialEditorStateType,
} from "lexical";

import { CalloutExtension } from "@/ui/editor/extensions/callout-extension";
import { EmojisExtension } from "@/ui/editor/extensions/emojis-extension";
import { ExcalidrawExtension } from "@/ui/editor/extensions/excalidraw-extension";
import { HeadingAnchorExtension } from "@/ui/editor/extensions/heading-anchor-extension";
import { ImagesExtension } from "@/ui/editor/extensions/images-extension";
import { KeywordsExtension } from "@/ui/editor/extensions/keywords-extension";
import { LayoutExtension } from "@/ui/editor/extensions/layout-extension";
import { LinkSanitizeExtension } from "@/ui/editor/extensions/link-sanitize-extension";
import { ListMaxIndentLevelExtension } from "@/ui/editor/extensions/list-max-indent-level-extension";
import { MarkdownShortcutsExtension } from "@/ui/editor/extensions/markdown-shortcuts-extension";
import { StatusExtension } from "@/ui/editor/extensions/status-extension";
import { TweetNode } from "@/ui/editor/nodes/embeds/tweet-node";
import { YouTubeNode } from "@/ui/editor/nodes/embeds/youtube-node";
import { editorTheme } from "@/ui/editor/themes/editor-theme";
import { validateUrl } from "@/ui/editor/utils/url";

const URL_REGEX =
  /((https?:\/\/(www\.)?)|(www\.))[-a-zA-Z0-9@:%._+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}\b([-a-zA-Z0-9()@:%_+.~#?&//=]*)(?<![-.+():%])/;

const EMAIL_REGEX =
  /(([^<>()[\]\\.,;:\s@"]+(\.[^<>()[\]\\.,;:\s@"]+)*)|(".+"))@((\[[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\])|(([a-zA-Z\-0-9]+\.)+[a-zA-Z]{2,}))/;

const AUTO_LINK_MATCHERS = [
  createLinkMatcherWithRegExp(URL_REGEX, (text) =>
    text.startsWith("http") ? text : `https://${text}`
  ),
  createLinkMatcherWithRegExp(EMAIL_REGEX, (text) => `mailto:${text}`),
];

export interface DocumentExtensionOptions {
  /** Yjs owns history and the initial content when a document is shared. */
  collaborative: boolean;
  editable: boolean;
  /** What the document opens with, or `null` for an empty one. */
  initialEditorState?: InitialEditorStateType;
  /** What becomes of an error the editor catches; logged by default. */
  onError?: (error: Error) => void;
  /** The host's own nodes and behaviours, added to the core's. */
  extension?: AnyLexicalExtension;
}

/**
 * Everything the document editor is made of: its nodes, and the behaviours
 * registered on top of them, with the host's own beside the core's.
 *
 * A module of its own because what is in this list decides what typing does —
 * an extension that claims a character claims it from the pickers as well.
 */
export function documentExtension({
  collaborative,
  editable,
  initialEditorState = null,
  onError = (error) => console.error(error),
  extension,
}: DocumentExtensionOptions) {
  return defineExtension({
    name: "@initiative/document-editor",
    namespace: "Editor",
    nodes: [OverflowNode, TableNode, TableCellNode, TableRowNode, TweetNode, YouTubeNode],
    theme: editorTheme,
    editable,
    onError,
    // In collaborative mode, leave the initial state empty.
    // CollaborationPlugin owns the initial state via its initialEditorState prop.
    $initialEditorState: collaborative ? null : initialEditorState,
    dependencies: [
      RichTextExtension,
      AutoFocusExtension,
      SelectionAlwaysOnDisplayExtension,
      // History is owned by Yjs in collaborative mode; only register HistoryExtension otherwise.
      ...(collaborative ? [] : [HistoryExtension]),
      configExtension(LinkExtension, {
        validateUrl,
        attributes: { rel: "noopener noreferrer", target: "_blank" },
      }),
      configExtension(AutoLinkExtension, { matchers: AUTO_LINK_MATCHERS }),
      LinkSanitizeExtension,
      ClickableLinkExtension,
      ListExtension,
      CheckListExtension,
      HorizontalRuleExtension,
      ClearEditorExtension,
      DecoratorTextExtension,
      CodeExtension,
      CodePrismExtension,
      EmojisExtension,
      ImagesExtension,
      KeywordsExtension,
      LayoutExtension,
      CalloutExtension,
      ExcalidrawExtension,
      StatusExtension,
      HeadingAnchorExtension,
      ListMaxIndentLevelExtension,
      MarkdownShortcutsExtension,
      ...(extension ? [extension] : []),
    ],
  });
}
