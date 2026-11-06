import { useTranslation } from "react-i18next";

import {
  type ContactCsvColumn,
  type ContactCsvPreview,
  ContactCsvTarget,
  MetadataType,
} from "@/api/generated/initiativeAPI.schemas";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useProperties } from "@/hooks/useProperties";

/** A column nothing reads, and a detail with no label column. */
const IGNORE = "ignore";
const NO_LABEL = "none";
const PROPERTY = "property:";

/** What a column can hold besides an initiative property. */
const FIXED_TARGETS = Object.values(ContactCsvTarget).filter(
  (target): target is Exclude<ContactCsvTarget, "property"> => target !== ContactCsvTarget.property
);

/** The details, whose values may each have a label in a column beside them. */
const DETAILS = new Set<ContactCsvTarget>([
  ContactCsvTarget.emails,
  ContactCsvTarget.phones,
  ContactCsvTarget.addresses,
  ContactCsvTarget.websites,
]);

export interface ContactColumnsStepProps {
  /** The sheet as the server read it, with what it says each column holds. */
  sheet: ContactCsvPreview;
  /** Where the contacts go; an initiative's properties are columns' targets
   *  too, and the community's contacts have none. */
  initiativeId: number | null;
  value: ContactCsvColumn[];
  onChange: (next: ContactCsvColumn[]) => void;
}

/** What each column of a spreadsheet of contacts holds: one of a contact's
 * fields, its tags, one of the initiative's properties, or nothing. A detail's
 * column can read its labels from another. Starts from what the server read
 * the headers as, so an export of contacts has nothing left to choose. */
export function ContactColumnsStep({
  sheet,
  initiativeId,
  value,
  onChange,
}: ContactColumnsStepProps) {
  const { t } = useTranslation("imports");
  const properties = useProperties({
    initiativeId: initiativeId ?? undefined,
    enabled: initiativeId !== null,
  });
  const byColumn = new Map(value.map((column) => [column.column, column]));
  const put = (index: number, next: ContactCsvColumn | null) =>
    onChange(
      [...value.filter((column) => column.column !== index), ...(next ? [next] : [])].sort(
        (a, b) => a.column - b.column
      )
    );
  const pick = (index: number, choice: string) =>
    put(
      index,
      choice === IGNORE
        ? null
        : choice.startsWith(PROPERTY)
          ? {
              column: index,
              target: ContactCsvTarget.property,
              property_id: Number(choice.slice(PROPERTY.length)),
            }
          : { column: index, target: choice as ContactCsvTarget, label_column: null }
    );
  const named = (header: string, index: number) =>
    header || t("wizard.contacts.untitled", { n: index + 1 });

  return (
    <ul className="max-h-[50vh] space-y-3 overflow-y-auto">
      {sheet.headers.map((header, index) => {
        const column = byColumn.get(index);
        const choice = !column
          ? IGNORE
          : column.target === ContactCsvTarget.property
            ? `${PROPERTY}${column.property_id}`
            : column.target;
        const sample = sheet.samples.find((row) => row[index])?.[index];
        return (
          // biome-ignore lint/suspicious/noArrayIndexKey: a sheet's headers may repeat; its columns are by position
          <li key={index} className="space-y-1.5 rounded-lg border p-3">
            <Label htmlFor={`contacts-column-${index}`} className="text-sm">
              {named(header, index)}
            </Label>
            {sample ? <p className="truncate text-muted-foreground text-xs">{sample}</p> : null}
            <div className="grid grid-cols-pair gap-2">
              <Select value={choice} onValueChange={(next) => pick(index, next)}>
                <SelectTrigger id={`contacts-column-${index}`}>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={IGNORE}>{t("wizard.contacts.targets.ignore")}</SelectItem>
                  {FIXED_TARGETS.map((target) => (
                    <SelectItem key={target} value={target}>
                      {t(`wizard.contacts.targets.${target}`)}
                    </SelectItem>
                  ))}
                  {/* A column fills a value for nobody's signature. */}
                  {(properties.data ?? [])
                    .filter((property) => property.type !== MetadataType.signature)
                    .map((property) => (
                      <SelectItem key={property.id} value={`${PROPERTY}${property.id}`}>
                        {property.name}
                      </SelectItem>
                    ))}
                </SelectContent>
              </Select>
              {column && DETAILS.has(column.target) ? (
                <Select
                  value={column.label_column == null ? NO_LABEL : String(column.label_column)}
                  onValueChange={(next) =>
                    put(index, {
                      ...column,
                      label_column: next === NO_LABEL ? null : Number(next),
                    })
                  }
                >
                  <SelectTrigger
                    aria-label={t("wizard.contacts.labelOf", { column: named(header, index) })}
                  >
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={NO_LABEL}>{t("wizard.contacts.noLabel")}</SelectItem>
                    {sheet.headers.map((other, at) =>
                      at === index ? null : (
                        // biome-ignore lint/suspicious/noArrayIndexKey: as above
                        <SelectItem key={at} value={String(at)}>
                          {t("wizard.contacts.labelFrom", { column: named(other, at) })}
                        </SelectItem>
                      )
                    )}
                  </SelectContent>
                </Select>
              ) : null}
            </div>
          </li>
        );
      })}
    </ul>
  );
}
