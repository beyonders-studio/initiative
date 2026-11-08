import { ImageIcon } from "lucide-react";

import type { ImagesConfig } from "@/ui/editor/extensions/images-extension";
import { ComponentPickerOption } from "@/ui/editor/plugins/picker/component-picker-option";

export function ImagePickerPlugin(insert: NonNullable<ImagesConfig["insert"]>) {
  return new ComponentPickerOption("Image", {
    icon: <ImageIcon className="size-4" />,
    keywords: ["image", "photo", "picture", "file"],
    onSelect: (_, editor, showModal) => insert(editor, showModal),
  });
}
