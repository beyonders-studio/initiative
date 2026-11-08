/**
 * A widget narrowed to some kinds of tool. Every kind unless the reader picks
 * some; picking all of them is the same as picking none, and is kept as none,
 * so a tool added later shows up on a widget that was never narrowed.
 */

import { useTranslation } from "react-i18next";

import type { Tool } from "@/api/generated/initiativeAPI.schemas";
import type { HomeWidgetOptions } from "@/lib/home/layout";
import { TOOLS, toolNavLabelKey } from "@/lib/tools";
import { Combobox } from "@/ui/combobox";
import { Field } from "@/ui/field";

/** The kinds picked, in registry order; none picked is every kind. */
export const toolsOf = (options: HomeWidgetOptions): Tool[] => {
  const picked = Array.isArray(options.tools) ? options.tools : [];
  const kept = TOOLS.filter((tool) => picked.includes(tool));
  return kept.length > 0 ? kept : TOOLS;
};

export const narrowed = (options: HomeWidgetOptions) => toolsOf(options).length < TOOLS.length;

/** The one kind a widget is narrowed to, for a title that names it. */
export const onlyTool = (options: HomeWidgetOptions): Tool | null => {
  const tools = toolsOf(options);
  return tools.length === 1 ? tools[0] : null;
};

export const ToolsSetting = ({
  id,
  options,
  onChange,
  hint,
}: {
  id: string;
  options: HomeWidgetOptions;
  onChange: (next: HomeWidgetOptions) => void;
  hint: string;
}) => {
  const { t } = useTranslation("home");
  const { t: tNav } = useTranslation("nav");
  const picked = narrowed(options) ? toolsOf(options) : [];
  return (
    <Field label={t("widgets.tools.label")} hint={hint} id={id}>
      <Combobox
        multiple
        value={picked}
        items={TOOLS.map((tool) => ({ value: tool, label: tNav(toolNavLabelKey(tool)) }))}
        onValueChange={(values) => {
          const { tools: _dropped, ...rest } = options;
          const kept = TOOLS.filter((tool) => values.includes(tool));
          onChange(kept.length > 0 && kept.length < TOOLS.length ? { ...rest, tools: kept } : rest);
        }}
        placeholder={t("widgets.tools.all")}
      />
    </Field>
  );
};
