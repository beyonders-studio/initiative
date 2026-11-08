import { useSearch } from "@tanstack/react-router";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type { AccessGrantRead, CommunityNotice } from "@/api/generated/initiativeAPI.schemas";
import { AccessGrantStatusBadge } from "@/components/access/AccessGrantStatusBadge";
import { SettingsSection } from "@/components/settings/SettingsSection";
import {
  flattenGrants,
  useAccessGrantLimits,
  useCancelAccessRequest,
  useCreateAccessRequest,
  useMyAccessGrants,
} from "@/hooks/useAccessGrants";
import { useAuth } from "@/hooks/useAuth";
import type { AccessGrantsSearch } from "@/lib/accessGrantsSearch";
import { toast } from "@/lib/mascotToast";
import { Capability, hasCapability } from "@/lib/permissions";
import { Button } from "@/ui/button";
import { Field } from "@/ui/field";
import { minutesLeft } from "@/ui/lib/formatDate";
import { LoadMore } from "@/ui/load-more";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/ui/select";
import { Textarea } from "@/ui/textarea";

import { CommunityPicker, type PickedCommunity } from "./CommunityPicker";
import {
  CaseField,
  CommunityNoticeField,
  communityLabel,
  durationsUpTo,
  formCommunity,
  GrantCaseMark,
  grantScope,
  noticeChoice,
  useCaseChoice,
  usePreselectedCommunity,
} from "./grantForm";

// Float the actionable grants to the top so they're never buried under dead
// history: pending (you can cancel) first, then live (currently usable), then
// everything else. Stable over the backend's newest-first ordering.
const activityRank = (grant: AccessGrantRead): number => {
  if (grant.status === "pending") return 0;
  if (grant.is_live) return 1;
  return 2;
};

// All whole-hour presets for a request, ascending.
const DURATION_PRESETS_MINUTES = [60, 240, 480, 1440];

/** The content rung the request form starts on: the one the link that opened
 *  it named, where the reader may ask for it, and read-only otherwise. A
 *  moderator, who asks for nothing else, starts on moderate. */
const startingLevel = (
  search: AccessGrantsSearch,
  canModerate: boolean,
  canAskAny: boolean
): string => {
  if (!canAskAny) return "moderate";
  if (search.form !== "request" || !search.level) return "read";
  return search.level === "moderate" && !canModerate ? "read" : search.level;
};

export const RequestSection = () => {
  const { t } = useTranslation(["settings", "common"]);
  const { user } = useAuth();
  // Reading what the platform holds is moderation work: only those who
  // moderate content may ask for it.
  const canModerate = hasCapability(user, Capability.contentModerate);
  // Everything else — read, read-write, settings — is access.request_any's: a
  // moderator asks for moderation access alone.
  const canAskAny = hasCapability(user, Capability.accessRequestAny);
  const myGrants = useMyAccessGrants();
  const limits = useAccessGrantLimits();
  const sortedGrants = useMemo(
    () => flattenGrants(myGrants.data?.pages).sort((a, b) => activityRank(a) - activityRank(b)),
    [myGrants.data]
  );
  const durationOptions = durationsUpTo(
    DURATION_PRESETS_MINUTES,
    limits.data?.max_duration_minutes
  );
  const defaultDuration = String(durationOptions.includes(240) ? 240 : (durationOptions[0] ?? ""));
  const search = useSearch({ strict: false }) as AccessGrantsSearch;
  const preselected = usePreselectedCommunity("request");
  const [pickedCommunity, setCommunity] = useState<PickedCommunity | null>(preselected);
  const caseChoice = useCaseChoice("request");
  const community = formCommunity(pickedCommunity, caseChoice.chosen);
  // Two axes, asked for independently. "none" is how you say you do not want
  // one — clearing up after an incident wants both; having a look wants only
  // the first.
  const [level, setLevel] = useState<string>(() => startingLevel(search, canModerate, canAskAny));
  const [settingsLevel, setSettingsLevel] = useState("none");
  // Null until chosen: the offered windows arrive with the limits above.
  const [chosenDuration, setDuration] = useState<string | null>(null);
  const duration = chosenDuration ?? defaultDuration;
  const [reason, setReason] = useState("");
  const [notice, setNotice] = useState<CommunityNotice>("none");

  const createRequest = useCreateAccessRequest({
    onSuccess: () => {
      toast.success(t("accessGrants.requestSubmitted"));
      setCommunity(null);
      caseChoice.setCaseTaskId(null);
      setReason("");
      setNotice("none");
      setDuration(null);
    },
  });
  const cancelRequest = useCancelAccessRequest();

  // A request must name at least one authority.
  const asksForSomething = level !== "none" || settingsLevel !== "none";
  // And, where the deployment says so, the case it is for.
  const namesItsCase = !caseChoice.required || caseChoice.caseTaskId != null;

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!community || !reason.trim() || !asksForSomething || !namesItsCase || !duration) return;
    createRequest.mutate({
      community_id: community.id,
      ...(level === "none" ? {} : { access_level: level as "read" | "read_write" | "moderate" }),
      ...(settingsLevel === "none"
        ? {}
        : { settings_level: settingsLevel as "admin" | "superadmin" }),
      reason: reason.trim(),
      requested_duration_minutes: Number.parseInt(duration, 10),
      ...(caseChoice.caseTaskId == null ? {} : { case_task_id: caseChoice.caseTaskId }),
      ...noticeChoice(caseChoice.chosen, notice),
    });
  };

  return (
    <SettingsSection
      title={t("accessGrants.requestTitle")}
      description={t("accessGrants.requestDescription")}
    >
      <form className="grid grid-cols-pair gap-4" onSubmit={submit}>
        <Field label={t("accessGrants.communityLabel")} className="space-y-1">
          <CommunityPicker
            aria-label={t("accessGrants.communityLabel")}
            value={community}
            onChange={setCommunity}
          />
        </Field>
        <CaseField choice={caseChoice} community={community} optional={false} />
        <CommunityNoticeField
          id="ag-notice"
          chosen={caseChoice.chosen}
          value={notice}
          onChange={setNotice}
        />
        <Field
          label={t("accessGrants.purposeContent")}
          hint={t("accessGrants.purposeContentHelp")}
          className="space-y-1"
        >
          <Select value={level} onValueChange={setLevel}>
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {canAskAny ? (
                <>
                  <SelectItem value="none">{t("accessGrants.levelNone")}</SelectItem>
                  <SelectItem value="read">{t("accessGrants.levelRead")}</SelectItem>
                  <SelectItem value="read_write">{t("accessGrants.levelReadWrite")}</SelectItem>
                </>
              ) : null}
              {canModerate ? (
                <SelectItem value="moderate">{t("accessGrants.levelModerate")}</SelectItem>
              ) : null}
            </SelectContent>
          </Select>
        </Field>
        {canAskAny ? (
          <Field
            label={t("accessGrants.purposeSettings")}
            hint={t("accessGrants.purposeSettingsHelp")}
            className="space-y-1"
          >
            <Select value={settingsLevel} onValueChange={setSettingsLevel}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="none">{t("accessGrants.levelNone")}</SelectItem>
                <SelectItem value="admin">{t("accessGrants.levelAdmin")}</SelectItem>
                <SelectItem value="superadmin">{t("accessGrants.levelSuperadmin")}</SelectItem>
              </SelectContent>
            </Select>
          </Field>
        ) : null}
        <Field label={t("accessGrants.durationLabel")} className="space-y-1">
          <Select value={duration} onValueChange={setDuration}>
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {durationOptions.map((minutes) => (
                <SelectItem key={minutes} value={String(minutes)}>
                  {t("accessGrants.durationHours", { count: minutes / 60 })}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Field>
        <Field label={t("accessGrants.reasonLabel")} className="col-span-full space-y-1">
          <Textarea
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder={t("accessGrants.reasonPlaceholder")}
            required
          />
        </Field>
        <div className="col-span-full">
          <Button
            type="submit"
            disabled={!community || createRequest.isPending || !asksForSomething || !namesItsCase}
          >
            {createRequest.isPending ? t("common:submitting") : t("accessGrants.submitRequest")}
          </Button>
          {!asksForSomething && (
            <p className="mt-2 text-muted-foreground text-xs">{t("accessGrants.nothingAsked")}</p>
          )}
        </div>
      </form>

      <div className="space-y-2">
        <h3 className="font-medium text-sm">{t("accessGrants.myRequests")}</h3>
        {!sortedGrants.length ? (
          <p className="text-muted-foreground text-sm">{t("accessGrants.noRequests")}</p>
        ) : (
          <ul className="divide-y rounded-md border">
            {sortedGrants.map((grant) => {
              const left = minutesLeft(grant.expires_at);
              return (
                <li key={grant.id} className="flex items-center justify-between gap-3 p-3">
                  <div className="min-w-0">
                    <p className="truncate text-sm">
                      {communityLabel(grant)} · {grantScope(grant)}
                    </p>
                    <p className="flex gap-2 text-muted-foreground text-xs">
                      <GrantCaseMark grant={grant} />
                      <span className="truncate">{grant.reason}</span>
                    </p>
                  </div>
                  <div className="flex items-center gap-2">
                    {grant.is_live && left !== null && (
                      <span className="text-muted-foreground text-xs">
                        {t("accessGrants.expiresIn", { minutes: left })}
                      </span>
                    )}
                    <AccessGrantStatusBadge grant={grant} />
                    {grant.status === "pending" && (
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        onClick={() => cancelRequest.mutate(grant.id)}
                        disabled={cancelRequest.isPending}
                      >
                        {t("common:cancel")}
                      </Button>
                    )}
                  </div>
                </li>
              );
            })}
          </ul>
        )}
        <LoadMore
          className="pt-1"
          hasMore={myGrants.hasNextPage}
          loading={myGrants.isFetchingNextPage}
          onLoadMore={myGrants.fetchNextPage}
        />
      </div>
    </SettingsSection>
  );
};
