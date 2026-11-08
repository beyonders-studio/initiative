import { useTranslation } from "react-i18next";

import { dateRangeBounds } from "@/lib/dateRange";
import { DateTimePicker } from "@/ui/date-time-picker";
import { Field } from "@/ui/field";

type ProjectDateFieldsProps = {
  /** Namespaces the two field ids so several instances can share a page. */
  idPrefix: string;
  /** `YYYY-MM-DD`, or "" for unset — the shape `DateTimePicker` speaks. */
  startDate: string;
  endDate: string;
  onStartDateChange: (value: string) => void;
  onEndDateChange: (value: string) => void;
  disabled?: boolean;
};

/**
 * The optional start/end date pair for a project, shared by the create dialog
 * and project settings. Each date stands alone; the two bound each other's
 * calendar, and an inverted range is called out here while the caller disables
 * its submit.
 */
export const ProjectDateFields = ({
  idPrefix,
  startDate,
  endDate,
  onStartDateChange,
  onEndDateChange,
  disabled = false,
}: ProjectDateFieldsProps) => {
  const { t } = useTranslation(["projects", "dates", "common"]);
  const dateRange = dateRangeBounds(startDate, endDate);

  return (
    <div className="space-y-2">
      <div className="grid grid-cols-pair gap-4">
        <Field label={t("projects:schedule.startLabel")}>
          <DateTimePicker
            value={startDate}
            onChange={onStartDateChange}
            includeTime={false}
            disabled={disabled}
            placeholder={t("common:optional")}
            calendarProps={dateRange.startCalendarProps}
          />
        </Field>
        <Field label={t("projects:schedule.endLabel")}>
          <DateTimePicker
            value={endDate}
            onChange={onEndDateChange}
            includeTime={false}
            disabled={disabled}
            placeholder={t("common:optional")}
            calendarProps={dateRange.endCalendarProps}
          />
        </Field>
      </div>
      {dateRange.isInverted ? (
        <p className="text-destructive text-sm" role="alert">
          {t("dates:invalidRange")}
        </p>
      ) : null}
    </div>
  );
};
