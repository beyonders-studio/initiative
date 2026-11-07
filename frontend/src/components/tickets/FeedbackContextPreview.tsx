/**
 * Where the app was, as feedback will send it: shown before it is sent, and
 * removed with one click. Nothing in it names a person or a thing — the page
 * is its route, with every id left out.
 */

import { X } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { FeedbackContext } from "@/api/generated/initiativeAPI.schemas";
import { Button } from "@/ui/button";

/** The fields, in the order they are shown. */
const FIELDS = ["app_version", "platform", "locale", "theme", "route", "viewport"] as const;

export interface FeedbackContextPreviewProps {
  context: FeedbackContext;
  onRemove: () => void;
}

export const FeedbackContextPreview = ({ context, onRemove }: FeedbackContextPreviewProps) => {
  const { t } = useTranslation("intake");
  const shown = FIELDS.filter((field) => context[field]);
  if (shown.length === 0) return null;
  return (
    <div className="space-y-2 rounded-md border p-3">
      <div className="flex items-center justify-between gap-2">
        <p className="font-medium text-sm">{t("feedback.context.title")}</p>
        <Button type="button" variant="ghost" size="sm" onClick={onRemove}>
          <X className="h-4 w-4" aria-hidden="true" />
          {t("feedback.context.remove")}
        </Button>
      </div>
      <p className="text-muted-foreground text-xs">{t("feedback.context.help")}</p>
      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
        {shown.map((field) => (
          <div key={field} className="contents">
            <dt className="text-muted-foreground">{t(`feedback.context.fields.${field}`)}</dt>
            <dd className="break-all font-mono">{context[field]}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
};
