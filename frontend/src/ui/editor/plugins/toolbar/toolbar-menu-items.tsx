import {
  EraserIcon,
  LinkIcon,
  PaintBucketIcon,
  PaletteIcon,
  PlusIcon,
  RedoIcon,
  TextIcon,
  TypeIcon,
  UndoIcon,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import { useBlockTypeToBlockName } from "@/ui/editor/plugins/toolbar/block-format/block-format-data";
import { useCurrentAlignment } from "@/ui/editor/plugins/toolbar/element-format-toolbar-plugin";
import {
  BLOCK_FORMAT_ORDER,
  type BlockFormatType,
  type EditorAction,
  type EditorSwatch,
  FONT_SIZE_PRESETS,
  type InsertAction,
  useAlignmentActions,
  useApplyFontSize,
  useApplyStyle,
  useBlockFormatActions,
  useBlockInsertActions,
  useClearFormatting,
  useCodeLanguageActions,
  useColorSwatches,
  useHistoryActions,
  useIndentActions,
  useSubSuperActions,
  useTextFormatActions,
  useToggleLink,
} from "@/ui/editor/plugins/toolbar/toolbar-actions";
import { OverflowMenuItem, OverflowSubmenu } from "@/ui/overflow-toolbar";

/**
 * One action as a line of the overflow menu.
 *
 * `onSelect` rather than `onClick`: the menu closes itself, and the editor gets
 * its selection back instead of the entry swallowing the click.
 */
const ActionItem = ({ action }: { action: EditorAction }) => (
  <OverflowMenuItem onSelect={action.run} className={action.active ? "bg-accent" : ""}>
    {action.icon}
    <span>{action.label}</span>
  </OverflowMenuItem>
);

const SwatchItems = ({
  swatches,
  onPick,
}: {
  swatches: EditorSwatch[];
  onPick: (value: string) => void;
}) => (
  <>
    {swatches.map((swatch) => (
      <OverflowMenuItem key={swatch.label + swatch.value} onSelect={() => onPick(swatch.value)}>
        <span
          aria-hidden
          className="size-4 rounded border"
          style={{ backgroundColor: swatch.value || "transparent" }}
        />
        <span>{swatch.label}</span>
      </OverflowMenuItem>
    ))}
  </>
);

export const HistoryMenuItems = () => {
  const { undo, redo, canUndo, canRedo } = useHistoryActions();
  const { t } = useTranslation("editor");

  return (
    <>
      <OverflowMenuItem onSelect={undo} disabled={!canUndo}>
        <UndoIcon className="size-4" />
        <span>{t("undo")}</span>
      </OverflowMenuItem>
      <OverflowMenuItem onSelect={redo} disabled={!canRedo}>
        <RedoIcon className="size-4" />
        <span>{t("redo")}</span>
      </OverflowMenuItem>
    </>
  );
};

export const BlockFormatMenuItems = ({
  types = BLOCK_FORMAT_ORDER,
}: {
  types?: readonly BlockFormatType[];
}) => {
  const actions = useBlockFormatActions(types);
  const names = useBlockTypeToBlockName();
  const { t } = useTranslation("editor");
  const current = actions.find((action) => action.active);

  return (
    <OverflowSubmenu
      icon={current?.icon ?? names.paragraph.icon}
      id="textStyle"
      label={t("textStyle")}
    >
      {actions.map((action) => (
        <ActionItem key={action.id} action={action} />
      ))}
    </OverflowSubmenu>
  );
};

export const CodeLanguageMenuItems = () => {
  const actions = useCodeLanguageActions();
  const { t } = useTranslation("editor");

  return (
    <OverflowSubmenu
      icon={<TextIcon className="size-4" />}
      id="codeLanguage"
      label={t("selectLanguage")}
    >
      {actions.map((action) => (
        <ActionItem key={action.id} action={action} />
      ))}
    </OverflowSubmenu>
  );
};

export const FontSizeMenuItems = () => {
  const applyFontSize = useApplyFontSize();
  const { t } = useTranslation("editor");

  return (
    <OverflowSubmenu icon={<TypeIcon className="size-4" />} id="fontSize" label={t("fontSize")}>
      {FONT_SIZE_PRESETS.map((size) => (
        <OverflowMenuItem key={size} onSelect={() => applyFontSize(size)}>
          <span>{size}</span>
        </OverflowMenuItem>
      ))}
    </OverflowSubmenu>
  );
};

export const FontFormatMenuItems = () => {
  // The menu is opened for one edit at a time, so it does not track what the
  // selection already carries — every entry simply toggles.
  const actions = useTextFormatActions([]);
  return (
    <>
      {actions.map((action) => (
        <ActionItem key={action.id} action={action} />
      ))}
    </>
  );
};

export const SubSuperMenuItems = () => {
  const actions = useSubSuperActions();
  return (
    <>
      {actions.map((action) => (
        <ActionItem key={action.id} action={action} />
      ))}
    </>
  );
};

export const LinkMenuItem = ({
  setIsLinkEditMode,
}: {
  setIsLinkEditMode: (value: boolean) => void;
}) => {
  const toggleLink = useToggleLink(setIsLinkEditMode);
  const { t } = useTranslation("editor");

  return (
    <OverflowMenuItem onSelect={toggleLink}>
      <LinkIcon className="size-4" />
      <span>{t("insertLink")}</span>
    </OverflowMenuItem>
  );
};

export const ClearFormattingMenuItem = () => {
  const clearFormatting = useClearFormatting();
  const { t } = useTranslation("editor");

  return (
    <OverflowMenuItem onSelect={clearFormatting}>
      <EraserIcon className="size-4" />
      <span>{t("clearFormatting")}</span>
    </OverflowMenuItem>
  );
};

export const FontColorMenuItems = () => {
  const { text } = useColorSwatches();
  const applyStyle = useApplyStyle();
  const { t } = useTranslation("editor");

  return (
    <OverflowSubmenu
      icon={<PaletteIcon className="size-4" />}
      id="textColor"
      label={t("textColor")}
    >
      <SwatchItems swatches={text} onPick={(value) => applyStyle("color", value)} />
    </OverflowSubmenu>
  );
};

export const FontBackgroundMenuItems = () => {
  const { background } = useColorSwatches();
  const applyStyle = useApplyStyle();
  const { t } = useTranslation("editor");

  return (
    <OverflowSubmenu
      icon={<PaintBucketIcon className="size-4" />}
      id="background"
      label={t("background")}
    >
      <SwatchItems
        swatches={background}
        onPick={(value) => applyStyle("background-color", value)}
      />
    </OverflowSubmenu>
  );
};

export const ElementFormatMenuItems = () => {
  const current = useCurrentAlignment();
  const alignments = useAlignmentActions(current);
  const indents = useIndentActions();
  const { t } = useTranslation("editor");

  return (
    <OverflowSubmenu
      icon={alignments.find((action) => action.active)?.icon}
      id="align"
      label={t("align")}
    >
      {[...alignments, ...indents].map((action) => (
        <ActionItem key={action.id} action={action} />
      ))}
    </OverflowSubmenu>
  );
};

export const BlockInsertMenuItems = (props: {
  rich: boolean;
  hostActions: readonly InsertAction[];
}) => {
  const actions = useBlockInsertActions(props);
  const { t } = useTranslation("editor");

  return (
    <OverflowSubmenu icon={<PlusIcon className="size-4" />} id="insert" label={t("insert")}>
      {actions.map((action) => (
        <ActionItem key={action.id} action={action} />
      ))}
    </OverflowSubmenu>
  );
};
