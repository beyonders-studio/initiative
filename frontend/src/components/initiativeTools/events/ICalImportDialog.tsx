import { AlertCircle, CheckCircle2, FileText, Upload } from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import type { ICalImportResult, ICalParseResult } from "@/api/generated/initiativeAPI.schemas";
import { isWritableCalendar } from "@/components/initiativeTools/events/CreateEventDialog";
import { useImportIcalEvents, useParseIcalFile } from "@/hooks/useCalendarEvents";
import { useCalendarsList } from "@/hooks/useCalendars";
import { useWizard } from "@/hooks/useWizard";
import { toast } from "@/lib/mascotToast";
import { browserTimezone } from "@/lib/timezones";
import type { DialogProps } from "@/types/dialog";
import { Button } from "@/ui/button";
import { Field } from "@/ui/field";
import { Label } from "@/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/ui/select";
import { WizardDialog } from "@/ui/wizard-dialog";

type Step = "upload" | "result";

interface ICalImportDialogProps extends DialogProps {
  fixedCalendarId?: number;
}

export const ICalImportDialog = ({
  open,
  onOpenChange,
  fixedCalendarId,
}: ICalImportDialogProps) => {
  const { t } = useTranslation(["calendars", "common"]);

  const { step, commit, reset } = useWizard<Step>("upload");
  const [icsContent, setIcsContent] = useState("");
  const [selectedCalendarId, setSelectedCalendarId] = useState<number | null>(
    fixedCalendarId ?? null
  );
  const [parseResult, setParseResult] = useState<ICalParseResult | null>(null);
  const [importResult, setImportResult] = useState<ICalImportResult | null>(null);

  const parseIcal = useParseIcalFile();
  const importIcal = useImportIcalEvents();

  // The counts a finished import reports, defaulted for the fields the API
  // leaves out when they are zero.
  const eventsCreated = importResult?.events_created ?? 0;
  const eventsFailed = importResult?.events_failed ?? 0;
  const importErrors = importResult?.errors ?? [];

  useEffect(() => {
    if (!open) {
      reset();
      setIcsContent("");
      setSelectedCalendarId(fixedCalendarId ?? null);
      setParseResult(null);
      setImportResult(null);
    }
  }, [open, fixedCalendarId, reset]);

  // Import creates events inside a calendar, so the target picker offers
  // exactly the calendars the user can write to.
  const calendarsQuery = useCalendarsList({ page_size: 200 }, { enabled: open });
  const writableCalendars = (calendarsQuery.data?.items ?? []).filter(isWritableCalendar);

  const MAX_ICS_SIZE = 2_000_000;
  // Dates and floating times in the file are read in the importer's zone.
  const tz = browserTimezone();

  const handleFileUpload = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;
    if (file.size > MAX_ICS_SIZE) {
      toast.error(t("calendars:import.parseFailed"));
      return;
    }
    const reader = new FileReader();
    reader.onload = (e) => {
      const content = e.target?.result as string;
      setIcsContent(content);
      parseIcal.mutate({ ics_content: content, tz }, { onSuccess: setParseResult });
    };
    reader.readAsText(file);
  };

  const handleImport = () => {
    if (!selectedCalendarId || !icsContent) return;
    importIcal.mutate(
      { calendar_id: selectedCalendarId, ics_content: icsContent, tz },
      {
        onSuccess: (result) => {
          setImportResult(result);
          commit("result");
        },
      }
    );
  };

  // One question and then a report on what it did, so there is no position
  // worth stating and no dots.
  return (
    <WizardDialog
      open={open}
      onOpenChange={onOpenChange}
      className="sm:max-w-lg"
      title={t("calendars:import.title")}
      description={t("calendars:import.uploadDescription")}
    >
      {step === "upload" && (
        <div className="space-y-4">
          <div>
            <Label>{t("calendars:import.uploadFileLabel")}</Label>
            <div className="mt-2">
              <label className="flex cursor-pointer flex-col items-center justify-center rounded-lg border-2 border-muted border-dashed p-6 transition-colors hover:bg-accent">
                <Upload className="mb-2 h-8 w-8 text-muted-foreground" />
                <span className="text-muted-foreground text-sm">
                  {parseIcal.isPending
                    ? t("calendars:import.parsing")
                    : t("calendars:import.uploadFileLabel")}
                </span>
                <input
                  type="file"
                  accept=".ics,.ical"
                  className="hidden"
                  onChange={handleFileUpload}
                />
              </label>
            </div>
          </div>

          {parseResult && (
            <div className="rounded-lg bg-muted p-4">
              <div className="flex items-center gap-2">
                <FileText className="h-4 w-4" />
                <span className="font-medium">
                  {t("calendars:import.foundEvents", { count: parseResult.event_count })}
                </span>
              </div>
              {parseResult.has_recurring && (
                <p className="mt-1 text-muted-foreground text-sm">
                  {t("calendars:import.hasRecurring")}
                </p>
              )}
              <ul className="mt-2 max-h-40 space-y-1 overflow-y-auto text-muted-foreground text-sm">
                {parseResult.events.slice(0, 20).map((ev) => (
                  <li key={ev.summary} className="truncate">
                    {ev.summary}
                  </li>
                ))}
                {parseResult.events.length > 20 && (
                  <li className="italic">
                    {}
                    {`+${parseResult.events.length - 20}`}
                  </li>
                )}
              </ul>
            </div>
          )}

          {parseResult && !fixedCalendarId && (
            <Field label={t("calendars:import.selectCalendar")}>
              <Select
                value={selectedCalendarId?.toString() ?? ""}
                onValueChange={(v) => setSelectedCalendarId(Number(v))}
              >
                <SelectTrigger>
                  <SelectValue placeholder={t("calendars:import.selectCalendar")} />
                </SelectTrigger>
                <SelectContent>
                  {writableCalendars.map((calendar) => (
                    <SelectItem key={calendar.id} value={calendar.id.toString()}>
                      {calendar.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </Field>
          )}

          <div className="flex justify-end gap-2">
            <Button variant="outline" onClick={() => onOpenChange(false)}>
              {t("common:cancel")}
            </Button>
            <Button
              onClick={handleImport}
              disabled={!parseResult || !selectedCalendarId || importIcal.isPending}
            >
              {importIcal.isPending
                ? t("calendars:import.importing")
                : t("calendars:import.importButton")}
            </Button>
          </div>
        </div>
      )}

      {step === "result" && importResult && (
        <div className="space-y-4">
          <div
            className={`flex items-center gap-3 rounded-lg p-4 ${
              eventsFailed === 0 ? "bg-green-500/10" : "bg-yellow-500/10"
            }`}
          >
            {eventsFailed === 0 ? (
              <CheckCircle2 className="h-8 w-8 text-green-500" />
            ) : (
              <AlertCircle className="h-8 w-8 text-yellow-500" />
            )}
            <div>
              <p className="font-medium">{t("calendars:import.importSuccess")}</p>
              <p className="text-muted-foreground text-sm">
                {t("calendars:import.eventsCreated", { count: eventsCreated })}
                {eventsFailed > 0 &&
                  `, ${t("calendars:import.eventsFailed", { count: eventsFailed })}`}
              </p>
            </div>
          </div>

          {importErrors.length > 0 && (
            <div className="max-h-40 overflow-y-auto rounded-lg bg-muted p-3">
              <ul className="space-y-1 text-muted-foreground text-xs">
                {importErrors.map((error, index) => (
                  // Two events in a file may share a title and a problem.
                  // biome-ignore lint/suspicious/noArrayIndexKey: the list is fixed once shown
                  <li key={index}>
                    {t(`calendars:import.problems.${error.problem}`, {
                      title: error.title ?? t("calendars:import.problems.untitled"),
                    })}
                  </li>
                ))}
              </ul>
            </div>
          )}

          <div className="flex justify-end">
            <Button onClick={() => onOpenChange(false)}>{t("common:done")}</Button>
          </div>
        </div>
      )}
    </WizardDialog>
  );
};
