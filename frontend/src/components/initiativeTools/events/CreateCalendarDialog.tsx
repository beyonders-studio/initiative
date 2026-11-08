import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { DEFAULT_CALENDAR_COLOR } from "@/components/calendar";
import {
  CreateToolDialog,
  type CreateToolDialogProps,
} from "@/components/initiativeTools/shared/CreateToolDialog";
import { ColorPickerPopover } from "@/ui/color-picker-popover";
import { Field } from "@/ui/field";

/**
 * The shared create dialog with the one thing a calendar asks for beside it:
 * the colour its events are drawn in.
 */
export const CreateCalendarDialog = (
  props: Omit<CreateToolDialogProps, "tool" | "text" | "extra">
) => {
  const { t } = useTranslation("calendars");
  const [color, setColor] = useState(DEFAULT_CALENDAR_COLOR);

  const [wasOpen, setWasOpen] = useState(props.open);
  if (wasOpen !== props.open) {
    setWasOpen(props.open);
    if (!props.open) setColor(DEFAULT_CALENDAR_COLOR);
  }

  return (
    <CreateToolDialog
      {...props}
      tool={Tool.calendar}
      text={{
        ns: "calendars",
        create: "createCalendar",
        // The namespace's own `descriptionPlaceholder` is an event's.
        descriptionPlaceholder: "calendarDescriptionPlaceholder",
      }}
      extra={{
        payload: { color },
        field: (
          <Field label={t("calendarColor")}>
            <ColorPickerPopover
              value={color}
              onChangeComplete={setColor}
              triggerLabel={t("calendarColor")}
            />
          </Field>
        ),
      }}
    />
  );
};
