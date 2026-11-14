import { useSearch } from "@tanstack/react-router";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  AccessGrantRead,
  CommunityNotice,
  GrantCaseRead,
} from "@/api/generated/initiativeAPI.schemas";
import { useGrantCases } from "@/hooks/useAccessGrants";
import type { AccessGrantsForm, AccessGrantsSearch } from "@/lib/accessGrantsSearch";
import { CasePicker } from "@/pages/operator/CasePicker";
import { Field } from "@/ui/field";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/ui/select";

import type { PickedCommunity } from "./CommunityPicker";

export const communityLabel = (grant: {
  community_name?: string | null;
  community_id: number;
}): string =>
  grant.community_name
    ? `${grant.community_name} (#${grant.community_id})`
    : `#${grant.community_id}`;

/**
 * The presets up to the server's ceiling for this caller, and the ceiling
 * itself where it is not one of them. The server enforces the ceiling; this
 * only decides which windows to offer.
 */
export const durationsUpTo = (presets: number[], max: number | undefined): number[] => {
  if (max === undefined) return [];
  const offered = presets.filter((minutes) => minutes <= max);
  return offered.includes(max) ? offered : [...offered, max];
};

/**
 * The community a form starts with, when the page was opened for that form
 * from a row on the Communities tab.
 */
export const usePreselectedCommunity = (form: AccessGrantsForm): PickedCommunity | null => {
  const search = useSearch({ strict: false }) as AccessGrantsSearch;
  if (!search.community || search.form !== form) return null;
  return { id: search.community, name: search.name ?? null };
};

/**
 * The operations case a form is for: the open cases on offer, whether one must
 * be named, and the one chosen, starting from the case the page was opened
 * for when it was opened for this form.
 */
export const useCaseChoice = (form: AccessGrantsForm) => {
  const search = useSearch({ strict: false }) as AccessGrantsSearch;
  const cases = useGrantCases();
  const [caseTaskId, setChosenId] = useState<number | null>(
    search.form === form ? (search.case ?? null) : null
  );
  // A case a search found is not in the first page, so it is kept as chosen.
  const [found, setFound] = useState<GrantCaseRead | undefined>(undefined);
  const items = cases.data?.items ?? [];
  const setCaseTaskId = (taskId: number | null, picked?: GrantCaseRead) => {
    setChosenId(taskId);
    setFound(picked);
  };
  const listed =
    caseTaskId == null
      ? undefined
      : (items.find((item) => item.task_id === caseTaskId) ??
        (found?.task_id === caseTaskId ? found : undefined));
  // A case the page was opened for that is past the first page is looked up
  // by its number, so the form knows what it allows.
  const lookedUp = useGrantCases({
    enabled: caseTaskId != null && cases.isSuccess && listed === undefined,
    search: `#${caseTaskId}`,
  });
  return {
    items,
    loading: cases.isLoading,
    loaded: cases.isSuccess,
    required: cases.data?.required ?? false,
    caseTaskId,
    setCaseTaskId,
    chosen: listed ?? lookedUp.data?.items.find((item) => item.task_id === caseTaskId),
  };
};

type CaseChoice = ReturnType<typeof useCaseChoice>;

/**
 * The community a form asks about: the one picked, or else the one the chosen
 * case is about.
 */
export const formCommunity = (
  picked: PickedCommunity | null,
  chosen: GrantCaseRead | undefined
): PickedCommunity | null =>
  picked ?? (chosen?.subject_community_id != null ? { id: chosen.subject_community_id } : null);

/** The case picker, what it asks of the form, and a word where the community
 *  picked is not the one the case is about. The server decides; this only
 *  says so before it is asked. */
export const CaseField = ({
  choice,
  community,
  optional,
}: {
  choice: CaseChoice;
  community: PickedCommunity | null;
  optional: boolean;
}) => {
  const { t } = useTranslation("settings");
  const subject = choice.chosen?.subject_community_id ?? null;
  const otherCommunity = subject != null && community != null && community.id !== subject;
  let hint: string | null = null;
  if (choice.caseTaskId == null) {
    if (optional) hint = t("accessGrants.caseOptionalHint");
    else if (choice.required) {
      hint =
        choice.loaded && choice.items.length === 0
          ? t("accessGrants.caseRequiredNoneOpen")
          : t("accessGrants.caseRequiredHint");
    }
  }
  return (
    <Field label={t("accessGrants.caseLabel")} hint={hint} className="space-y-1">
      <CasePicker
        cases={choice.items}
        value={choice.caseTaskId}
        onChange={choice.setCaseTaskId}
        optional={optional || !choice.required}
        loading={choice.loading}
      />
      {otherCommunity ? (
        <p className="text-warning text-xs">
          {t("accessGrants.caseOtherCommunity", { community: subject })}
        </p>
      ) : null}
    </Field>
  );
};

/**
 * Whether the community is told of the access, as the chosen case allows: a
 * support case always tells it when access starts, and a security or
 * moderation case leaves it to the asker. The server settles it; this only
 * offers what it will take.
 */
export const CommunityNoticeField = ({
  id,
  chosen,
  value,
  onChange,
}: {
  id: string;
  chosen: GrantCaseRead | undefined;
  value: CommunityNotice;
  onChange: (value: CommunityNotice) => void;
}) => {
  const { t } = useTranslation("settings");
  if (chosen?.community_notice === "always") {
    return (
      <p className="col-span-full text-muted-foreground text-xs">
        {t("accessGrants.notice.always")}
      </p>
    );
  }
  if (chosen?.community_notice !== "optional") return null;
  return (
    <Field
      label={t("accessGrants.notice.label")}
      hint={t("accessGrants.notice.help")}
      id={id}
      className="space-y-1"
    >
      <Select value={value} onValueChange={(next) => onChange(next as CommunityNotice)}>
        <SelectTrigger>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="none">{t("accessGrants.notice.none")}</SelectItem>
          <SelectItem value="when_granted">{t("accessGrants.notice.when_granted")}</SelectItem>
          <SelectItem value="when_ended">{t("accessGrants.notice.when_ended")}</SelectItem>
        </SelectContent>
      </Select>
    </Field>
  );
};

/** What a form sends for the community's notice: a choice only where the
 *  chosen case offers one. */
export const noticeChoice = (chosen: GrantCaseRead | undefined, notice: CommunityNotice) =>
  chosen?.community_notice === "optional" && notice !== "none" ? { community_notice: notice } : {};

/** The case a grant was asked for, by its number, and when its community is
 *  told of it. */
export const GrantCaseMark = ({ grant }: { grant: AccessGrantRead }) => {
  const { t } = useTranslation("settings");
  if (grant.case_task_id == null) return null;
  // Reaching the case needs the operations community's address, which this
  // page does not hold, so the number stands alone.
  return (
    <span className="shrink-0 text-muted-foreground text-xs">
      {t("accessGrants.caseMark", { id: grant.case_task_id })}
      {grant.community_notice !== "none"
        ? ` · ${t(`accessGrants.notice.mark.${grant.community_notice}`)}`
        : null}
    </span>
  );
};

/** What a grant is for and how far it goes, in one phrase — the level alone is
 *  ambiguous now that a settings grant carries its own vocabulary. */
export const grantScope = (grant: { purpose?: string; access_level: string }): string =>
  grant.purpose === "settings" ? `settings · ${grant.access_level}` : grant.access_level;
