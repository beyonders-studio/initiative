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
  /** How much of what it was asked about it was written from, when not all
   *  of it fit. */
  cutPercent: number | null;
  /** Where the changes it read start, for a catch-up. */
  since: string | null;
  /** The answer ended, rather than being stopped part-way. */
  finished: boolean;
}

/** What the sheet says about what it summarizes. */
export interface SummaryWords {
  title: string;
  intro: string;
  action: string;
  writing: string;
  cut: (percent: number) => string;
  /** Where the changes read start, for an answer that says. */
  since?: (since: string) => string;
  /** Said when the answer ends with nothing to tell. */
  empty?: string;
}

interface SummarySheetProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** The document's summary route, from the generated client. */
  request: AIStreamRequest;
  /** Kept by the page, so closing the sheet does not lose it. */
  summary: AISummary | null;
  onSummaryChange: (summary: AISummary | null) => void;
  /** What it says, where it is not a document's summary. */
  words?: SummaryWords;
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
export const SummarySheet = ({ open, onOpenChange, words, ...body }: SummarySheetProps) => {
  const { t } = useTranslation("editor");
  const said = words ?? {
    title: t("summary.title"),
    intro: t("summary.generateDescription"),
    action: t("summary.generateButton"),
    writing: t("summary.generating"),
    cut: (percent: number) => t("summary.cut", { percent }),
  };
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
          <SheetTitle className="text-base">{said.title}</SheetTitle>
        </SheetHeader>
        <div className="flex-1 overflow-y-auto p-4">
          <SummaryBody {...body} words={said} />
        </div>
      </SheetContent>
    </Sheet>
  );
};

const SummaryBody = ({
  request,
  summary,
  onSummaryChange,
  words,
}: Omit<SummarySheetProps, "open" | "onOpenChange" | "words"> & { words: SummaryWords }) => {
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
    let written: AISummary = { text: "", cutPercent: null, since: null, finished: false };
    setWriting(true);
    setError(null);
    try {
      await readAIStream(request, controller.signal, (event) => {
        if (event.error) {
          setError(messageForCode(event.error, "editor:summary.generateError"));
          return;
        }
        written = {
          ...written,
          text: written.text + (event.text ?? ""),
          cutPercent: event.cut?.percent ?? written.cutPercent,
          since: event.since ?? written.since,
        };
        onSummaryChange(written);
      });
      onSummaryChange({ ...written, finished: true });
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
  const since =
    summary?.since && words.since ? (
      <p className="text-muted-foreground text-xs">{words.since(summary.since)}</p>
    ) : null;

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

  if (!summary?.text) {
    if (writing) {
      return (
        <div className="space-y-4 py-8 text-center">
          <Loader2 className="mx-auto h-8 w-8 animate-spin text-muted-foreground" />
          <p className="text-muted-foreground text-sm">{words.writing}</p>
        </div>
      );
    }
    // Asked, and answered with nothing to tell.
    const nothing = summary?.finished && !error && words.empty;
    return (
      <div className="space-y-4 py-4 text-center">
        <Sparkles className="mx-auto h-8 w-8 text-muted-foreground" />
        <p className="text-muted-foreground text-sm">{nothing ? words.empty : words.intro}</p>
        {nothing ? (
          since
        ) : (
          <Button onClick={() => void write()}>
            <Sparkles className="h-4 w-4" />
            {words.action}
          </Button>
        )}
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
      {since}
      <div className="rounded-lg bg-muted/50 p-4">
        <p className="whitespace-pre-wrap text-sm">{summary.text}</p>
      </div>
      {summary.cutPercent !== null ? (
        <p className="text-muted-foreground text-xs">{words.cut(summary.cutPercent)}</p>
      ) : null}
      {failed}
    </div>
  );
};
