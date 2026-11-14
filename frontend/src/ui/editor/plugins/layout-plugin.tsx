import { createCommand, type LexicalCommand, type LexicalEditor, type NodeKey } from "lexical";
import { type JSX, useState } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/ui/select";

const LAYOUTS = [
  { label: "columnLayouts.twoEqual", value: "1fr 1fr" },
  { label: "columnLayouts.twoQuarterLeft", value: "1fr 3fr" },
  { label: "columnLayouts.threeEqual", value: "1fr 1fr 1fr" },
  { label: "columnLayouts.threeWideMiddle", value: "1fr 2fr 1fr" },
  { label: "columnLayouts.fourEqual", value: "1fr 1fr 1fr 1fr" },
] as const;

export function InsertLayoutDialog({
  activeEditor,
  onClose,
}: {
  activeEditor: LexicalEditor;
  onClose: () => void;
}): JSX.Element {
  const { t } = useTranslation("editor");
  const [layout, setLayout] = useState<string>(LAYOUTS[0].value);
  const buttonLabel = LAYOUTS.find((item) => item.value === layout)?.label;

  const onClick = () => {
    activeEditor.dispatchCommand(INSERT_LAYOUT_COMMAND, layout);
    onClose();
  };

  return (
    <>
      <Select onValueChange={setLayout} defaultValue={layout}>
        <SelectTrigger className="w-full">
          <SelectValue placeholder={buttonLabel && t(buttonLabel)} />
        </SelectTrigger>
        <SelectContent className="w-full">
          {LAYOUTS.map(({ label, value }) => (
            <SelectItem key={value} value={value}>
              {t(label)}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <Button onClick={onClick}>{t("insert")}</Button>
    </>
  );
}

export const INSERT_LAYOUT_COMMAND: LexicalCommand<string> = createCommand<string>();

export const UPDATE_LAYOUT_COMMAND: LexicalCommand<{
  template: string;
  nodeKey: NodeKey;
}> = createCommand<{ template: string; nodeKey: NodeKey }>();
