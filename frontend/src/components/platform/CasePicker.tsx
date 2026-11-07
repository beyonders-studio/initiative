/**
 * Chooses the operations case an access grant is for.
 *
 * The list is the first few dozen open cases the reader can open, theirs
 * first. Typing searches those here at once, and the server for the rest — a
 * title holding it, or the case with that number. Each reads as its number
 * and title, with the stream it came in on beside it and a mark on the ones
 * assigned to the reader.
 */

import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { GrantCaseRead } from "@/api/generated/initiativeAPI.schemas";
import { useGrantCases } from "@/hooks/useAccessGrants";
import { AsyncCombobox } from "@/ui/async-combobox";
import { useDebouncedValue } from "@/ui/lib/useDebouncedValue";

/** The value the "no case" row is chosen by, where a case is optional. */
const NO_CASE = "none";

/** How a case reads in the list and on the closed picker. */
export const caseLabel = (item: Pick<GrantCaseRead, "task_id" | "title">): string =>
  `#${item.task_id} · ${item.title}`;

export const CasePicker = ({
  cases,
  value,
  onChange,
  optional = false,
  loading = false,
  disabled = false,
  "aria-label": ariaLabel,
  className,
}: {
  cases: GrantCaseRead[];
  /** The chosen case's task id. It may name a case the list no longer holds. */
  value: number | null;
  /** The chosen case's id, and the case itself where the list held it —
   *  one a search found is not in ``cases``. */
  onChange: (taskId: number | null, picked?: GrantCaseRead) => void;
  /** Offer a row for choosing no case at all. */
  optional?: boolean;
  loading?: boolean;
  disabled?: boolean;
  "aria-label"?: string;
  className?: string;
}) => {
  const { t } = useTranslation(["settings", "intake"]);
  const [search, setSearch] = useState("");
  const needle = search.trim().toLowerCase();
  // What is past the first page is the server's to find.
  const asked = useDebouncedValue(search.trim(), 250);
  const searched = useGrantCases({ enabled: asked.length > 0, search: asked });
  const local = needle
    ? cases.filter((item) => caseLabel(item).toLowerCase().includes(needle))
    : cases;
  const found = needle ? (searched.data?.items ?? []) : [];
  const shown = [
    ...local,
    ...found.filter((item) => !local.some((held) => held.task_id === item.task_id)),
  ];
  // The label of the case chosen, kept so it reads right once the search that
  // found it is gone.
  const [chosenLabel, setChosenLabel] = useState<string | null>(null);
  const chosen = value == null ? undefined : cases.find((item) => item.task_id === value);

  return (
    <AsyncCombobox
      className={className}
      aria-label={ariaLabel}
      value={value == null ? null : String(value)}
      selectedLabel={
        value == null ? null : chosen ? caseLabel(chosen) : (chosenLabel ?? `#${value}`)
      }
      items={[
        ...(optional && !needle ? [{ value: NO_CASE, label: t("accessGrants.caseNone") }] : []),
        ...shown.map((item) => ({
          value: String(item.task_id),
          label: caseLabel(item),
          hint: item.mine
            ? `${t(`intake:streams.${item.stream}.title`)} · ${t("accessGrants.caseYours")}`
            : t(`intake:streams.${item.stream}.title`),
        })),
      ]}
      onSearchChange={setSearch}
      // Searched here at once; the server is asked once typing pauses.
      debounceMs={0}
      loading={loading || (needle.length > 0 && searched.isFetching)}
      placeholder={t("accessGrants.casePlaceholder")}
      searchPlaceholder={t("accessGrants.caseSearch")}
      emptyMessage={t("accessGrants.caseEmpty")}
      disabled={disabled}
      onValueChange={(next) => {
        const picked = shown.find((item) => String(item.task_id) === next);
        setChosenLabel(picked ? caseLabel(picked) : null);
        onChange(next === NO_CASE ? null : Number(next), picked);
      }}
    />
  );
};
