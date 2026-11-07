import {
  CodeIcon,
  Heading1Icon,
  Heading2Icon,
  Heading3Icon,
  ListIcon,
  ListOrderedIcon,
  ListTodoIcon,
  QuoteIcon,
  TextIcon,
} from "lucide-react";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";

export type BlockFormatEntry = { label: string; icon: React.ReactNode };

export function useBlockTypeToBlockName(): Record<string, BlockFormatEntry> {
  const { t } = useTranslation("editor");
  return useMemo(
    () => ({
      paragraph: {
        label: t("blockNormal"),
        icon: <TextIcon className="size-4" />,
      },
      h1: {
        label: t("blockH1"),
        icon: <Heading1Icon className="size-4" />,
      },
      h2: {
        label: t("blockH2"),
        icon: <Heading2Icon className="size-4" />,
      },
      h3: {
        label: t("blockH3"),
        icon: <Heading3Icon className="size-4" />,
      },
      number: {
        label: t("numberedList"),
        icon: <ListOrderedIcon className="size-4" />,
      },
      bullet: {
        label: t("bulletedList"),
        icon: <ListIcon className="size-4" />,
      },
      check: {
        label: t("checklist"),
        icon: <ListTodoIcon className="size-4" />,
      },
      code: {
        label: t("blockCode"),
        icon: <CodeIcon className="size-4" />,
      },
      quote: {
        label: t("blockQuote"),
        icon: <QuoteIcon className="size-4" />,
      },
    }),
    [t]
  );
}
