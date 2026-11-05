import { Building2, Plus, UserRound, X } from "lucide-react";
import { useId } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import {
  BLANK_DETAIL,
  CONTACT_DETAILS,
  type ContactDetailField,
  type ContactDetails,
  DETAIL_LABELS,
} from "@/lib/contacts";

/** How each detail's value is typed, so a phone's keyboard comes up for a phone. */
const VALUE_INPUT: Record<
  Exclude<ContactDetailField, "addresses">,
  { type: string; inputMode: "tel" | "email" | "url" }
> = {
  phones: { type: "tel", inputMode: "tel" },
  emails: { type: "email", inputMode: "email" },
  websites: { type: "text", inputMode: "url" },
};

/** Whether a contact is a person or an organization. */
export const ContactKindToggle = ({
  isOrganization,
  onChange,
}: {
  isOrganization: boolean;
  onChange: (isOrganization: boolean) => void;
}) => {
  const { t } = useTranslation("contacts");
  return (
    <ToggleGroup
      type="single"
      variant="outline"
      value={isOrganization ? "organization" : "person"}
      onValueChange={(next) => next && onChange(next === "organization")}
      aria-label={t("kind")}
      className="justify-start"
    >
      <ToggleGroupItem value="person">
        <UserRound className="h-4 w-4" />
        {t("person")}
      </ToggleGroupItem>
      <ToggleGroupItem value="organization">
        <Building2 className="h-4 w-4" />
        {t("organization")}
      </ToggleGroupItem>
    </ToggleGroup>
  );
};

/**
 * A contact's emails, phones, addresses and websites, as rows of a label and a
 * value that can be added and removed. The new-contact dialog and the contact
 * page's edit both write through here. The labels offered are suggestions;
 * any word fits.
 */
export const ContactDetailsFields = ({
  value,
  onChange,
}: {
  value: ContactDetails;
  onChange: (next: ContactDetails) => void;
}) => {
  const { t } = useTranslation("contacts");
  const id = useId();
  const set = (field: ContactDetailField, rows: ContactDetails[ContactDetailField]) =>
    onChange({ ...value, [field]: rows });

  return (
    <div className="space-y-4">
      {CONTACT_DETAILS.map((field) => {
        const fieldName = t(`fields.${field}`);
        const rows = value[field];
        return (
          <fieldset key={field} className="space-y-2">
            <legend className="mb-2 font-medium text-sm">{fieldName}</legend>
            <datalist id={`${id}-${field}`}>
              {DETAIL_LABELS[field].map((label) => (
                <option key={label} value={t(`labels.${label}`)} />
              ))}
            </datalist>
            {rows.map((detail, index) => {
              const edit = (change: Partial<typeof detail>) =>
                set(
                  field,
                  rows.map((row, at) => (at === index ? { ...row, ...change } : row))
                );
              return (
                // biome-ignore lint/suspicious/noArrayIndexKey: positional by nature; every input is controlled
                <div key={index} className="flex items-start gap-2">
                  <Input
                    aria-label={t("labelOf", { field: fieldName })}
                    list={`${id}-${field}`}
                    value={detail.label ?? ""}
                    onChange={(event) => edit({ label: event.target.value })}
                    placeholder={t("label")}
                    maxLength={40}
                    className="w-28 shrink-0"
                  />
                  {field === "addresses" ? (
                    <Textarea
                      aria-label={fieldName}
                      value={detail.value}
                      onChange={(event) => edit({ value: event.target.value })}
                      placeholder={t(`placeholders.${field}`)}
                      rows={3}
                      className="min-w-0 flex-1"
                    />
                  ) : (
                    <Input
                      aria-label={fieldName}
                      {...VALUE_INPUT[field]}
                      autoComplete="off"
                      value={detail.value}
                      onChange={(event) => edit({ value: event.target.value })}
                      placeholder={t(`placeholders.${field}`)}
                      className="min-w-0 flex-1"
                    />
                  )}
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    className="shrink-0"
                    aria-label={t("removeOf", { field: fieldName })}
                    onClick={() =>
                      set(
                        field,
                        rows.filter((_, at) => at !== index)
                      )
                    }
                  >
                    <X className="h-4 w-4" />
                  </Button>
                </div>
              );
            })}
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => set(field, [...rows, BLANK_DETAIL])}
            >
              <Plus className="h-4 w-4" />
              {t(`add.${field}`)}
            </Button>
          </fieldset>
        );
      })}
    </div>
  );
};
