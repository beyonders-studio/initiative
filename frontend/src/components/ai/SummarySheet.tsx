import { Check, Copy, Loader2, RefreshCw, Sparkles } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { type AIStreamRequest, readAIStream } from "@/api/aiStream";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { useAIEnabled } from "@/hooks/useAIEnabled";
import { getErrorMessage, messageForCode } from "@/lib/errorMessage";
import { getItem, setItem } from "@/lib/storage";

/** A summary as it has been written so far. */
export interface AISummary {
  text: string;
  /** How much of the document it was written from, when not all of it fit. */
  cutPercent: number | null;
}

interface SummarySheetProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** The document's summary route, from the generated client. */
  request: AIStreamRequest;
  /** Kept by the page, so closing the sheet does not lose it. */
  summary: AISummary | null;
  onSummaryChange: (summary: AISummary | null) => void;
}

/** Whether the sheet is open, remembered on the device under ``key``. */
export const useSummarySheet = (key: string) => {
  const [isOpen, setIsOpen] = useState(() => getItem(key) === "true");
  useEffect(() => {
    setItem(key, String(isOpen));
  }, [key, isOpen]);
  return { isOpen, setIsOpen, toggle: () => setIsOpen((open) => !open) };
};

/** A document's AI summary, in a sheet beside it, written in as it arrives. */
export const SummarySheet = ({ open, onOpenChange, ...body }: SummarySheetProps) => {
  const { t } = useTranslation("editor");
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="flex w-full flex-col overflow-hidden p-0 sm:max-w-md">
        <SheetHeader
          className="border-b px-4"
          style={{
            paddingTop: "calc(var(--safe-area-inset-top) + 0.75rem)",
            paddingBottom: "0.75rem",
          }}
        >
          <SheetTitle className="text-base">{t("summary.title")}</SheetTitle>
        </SheetHeader>
        <div className="flex-1 overflow-y-auto p-4">
          <SummaryBody {...body} />
        </div>
      </SheetContent>
    </Sheet>
  );
};

const SummaryBody = ({
  request,
  summary,
  onSummaryChange,
}: Omit<SummarySheetProps, "open" | "onOpenChange">) => {
  const { t } = useTranslation("editor");
  const { isEnabled, isLoading } = useAIEnabled();
  const [writing, setWriting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  // The summary being read, stopped when the sheet closes or another starts.
  const reading = useRef<AbortController | null>(null);
  useEffect(() => () => reading.current?.abort(), []);

  const write = async () => {
    reading.current?.abort();
    const controller = new AbortController();
    reading.current = controller;
    // The one before stays until the new one starts arriving.
    let written: AISummary = { text: "", cutPercent: null };
    setWriting(true);
    setError(null);
    try {
      await readAIStream(request, controller.signal, (event) => {
        if (event.error) {
          setError(messageForCode(event.error, "editor:summary.generateError"));
          return;
        }
        written = {
          text: written.text + (event.text ?? ""),
          cutPercent: event.cut?.percent ?? written.cutPercent,
        };
        onSummaryChange(written);
      });
    } catch (err) {
      if (!controller.signal.aborted) {
        setError(getErrorMessage(err, "editor:summary.generateError"));
      }
    } finally {
      if (reading.current === controller) setWriting(false);
    }
  };

  const copy = async () => {
    if (!summary) return;
    try {
      await navigator.clipboard.writeText(summary.text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (error) {
      console.error("Failed to copy:", error);
    }
  };

  const failed = error ? <p className="text-destructive text-sm">{error}</p> : null;

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-8">
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (!isEnabled) {
    return (
      <div className="space-y-2 py-4 text-center">
        <Sparkles className="mx-auto h-8 w-8 text-muted-foreground" />
        <p className="text-muted-foreground text-sm">{t("summary.aiNotEnabled")}</p>
      </div>
    );
  }

  if (!summary) {
    return writing ? (
      <div className="space-y-4 py-8 text-center">
        <Loader2 className="mx-auto h-8 w-8 animate-spin text-muted-foreground" />
        <p className="text-muted-foreground text-sm">{t("summary.generating")}</p>
      </div>
    ) : (
      <div className="space-y-4 py-4 text-center">
        <Sparkles className="mx-auto h-8 w-8 text-muted-foreground" />
        <p className="text-muted-foreground text-sm">{t("summary.generateDescription")}</p>
        <Button onClick={() => void write()}>
          <Sparkles className="h-4 w-4" />
          {t("summary.generateButton")}
        </Button>
        {failed}
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-end gap-1">
        <Button
          variant="ghost"
          size="icon"
          className="h-8 w-8"
          onClick={() => void copy()}
          disabled={writing}
          title={t("summary.copy")}
        >
          {copied ? <Check className="h-4 w-4 text-green-500" /> : <Copy className="h-4 w-4" />}
        </Button>
        <Button
          variant="ghost"
          size="icon"
          className="h-8 w-8"
          onClick={() => void write()}
          disabled={writing}
          title={t("summary.regenerate")}
        >
          {writing ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <RefreshCw className="h-4 w-4" />
          )}
        </Button>
      </div>
      <div className="rounded-lg bg-muted/50 p-4">
        <p className="whitespace-pre-wrap text-sm">{summary.text}</p>
      </div>
      {summary.cutPercent !== null ? (
        <p className="text-muted-foreground text-xs">
          {t("summary.cut", { percent: summary.cutPercent })}
        </p>
      ) : null}
      {failed}
    </div>
  );
};
