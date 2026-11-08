import type { TFunction } from "i18next";

import { INSERT_CALLOUT_COMMAND } from "@/ui/editor/extensions/callout-extension";
import { CALLOUT_VARIANTS } from "@/ui/editor/nodes/callout-node";
import { CalloutIcon } from "@/ui/editor/plugins/callout-icon";
import { ComponentPickerOption } from "@/ui/editor/plugins/picker/component-picker-option";

/** One "/" entry per kind of callout, so the kind is chosen as it is made. */
export function CalloutPickerPlugins(t: TFunction<"editor">) {
  return CALLOUT_VARIANTS.map(
    (variant) =>
      new ComponentPickerOption(t("calloutOf", { kind: t(`calloutKinds.${variant}`) }), {
        icon: <CalloutIcon variant={variant} className="size-4" />,
        keywords: ["callout", "panel", "admonition", "alert", variant],
        onSelect: (_, editor) => editor.dispatchCommand(INSERT_CALLOUT_COMMAND, variant),
      })
  );
}
