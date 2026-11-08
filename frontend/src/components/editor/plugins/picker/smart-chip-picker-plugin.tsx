import type { TFunction } from "i18next";
import { PanelTop } from "lucide-react";

import { LazyEmbedDialog } from "@/components/editor/plugins/lazy-embed-dialog";
import { SmartChipInsertDialog } from "@/components/editor/plugins/smart-chip-insert-dialog";
import { SMART_CHIP_MENU } from "@/components/editor/plugins/smart-chip-menu";
import { chipAspect, SMART_CHIP_KINDS } from "@/lib/smartChips";
import { ComponentPickerOption } from "@/ui/editor/plugins/picker/component-picker-option";

/**
 * One `/` entry per chip, built from the generated list.
 *
 * `initiativeId` is what a chip may point at: the same initiative the document
 * belongs to, so a chip cannot name work its readers cannot open.
 */
export function SmartChipPickerPlugins(
  t: TFunction<"editor">,
  initiativeId: number | null
): ComponentPickerOption[] {
  return SMART_CHIP_KINDS.map((kind) => {
    const entry = SMART_CHIP_MENU[kind];
    const title = t(entry.labelKey as never);
    return new ComponentPickerOption(title, {
      icon: entry.icon,
      keywords: [...entry.keywords, chipAspect(kind)],
      onSelect: (_, editor, showModal) =>
        showModal(title, (onClose) => (
          <SmartChipInsertDialog
            chipKind={kind}
            initiativeId={initiativeId}
            activeEditor={editor}
            onClose={onClose}
          />
        )),
    });
  });
}

/** The `/` entry for `![[ ]]`, for whoever does not know the syntax: a thing
 *  shown in full, or the tasks a filter matches, in a callout. */
export function EmbedPickerPlugin(t: TFunction<"editor">): ComponentPickerOption {
  const title = t("embeds.insert");
  return new ComponentPickerOption(title, {
    icon: <PanelTop className="size-4" />,
    keywords: ["embed", "description", "details", "card", "transclude", "callout"],
    onSelect: (_, editor, showModal) =>
      showModal(title, (onClose) => <LazyEmbedDialog activeEditor={editor} onClose={onClose} />),
  });
}
