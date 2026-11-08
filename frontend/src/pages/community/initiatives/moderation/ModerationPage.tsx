import { useParams } from "@tanstack/react-router";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { useModerationReports } from "@/hooks/useModeration";
import { CardGridSkeleton, SkeletonRegion } from "@/ui/page-skeletons";
import { PaginationBar } from "@/ui/pagination-bar";
import { Tabs, TabsList, TabsTrigger } from "@/ui/tabs";

import { LogArea } from "./LogArea";
import { MembersArea } from "./MembersArea";
import { ReportCard } from "./ReportCard";
import { SharingArea } from "./SharingArea";

export const ModerationPage = () => {
  const { t } = useTranslation(["moderation", "common"]);
  const communityId = useActiveCommunityId();
  const { initiativeId } = useParams({ strict: false }) as { initiativeId?: string };
  const initiative = Number(initiativeId);
  const [area, setArea] = useState<ConsoleArea>("reports");
  const [tab, setTab] = useState<"open" | "settled">("open");
  const [page, setPage] = useState(1);

  const { data, isLoading } = useModerationReports(
    {
      communityId: communityId ?? 0,
      initiativeId: initiative,
      settled: tab === "settled",
      page,
    },
    { enabled: Boolean(communityId) && Number.isFinite(initiative) }
  );

  const reports = data?.items ?? [];

  const showTab = (next: "open" | "settled") => {
    setTab(next);
    setPage(1);
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="font-semibold text-3xl tracking-tight">{t("title")}</h1>
        <p className="text-muted-foreground">{t("subtitle")}</p>
      </div>

      {/* What a moderator acts on, and what they act with. The second two are
          views onto standing they already hold — being here grants nothing. */}
      <Tabs value={area} onValueChange={(v) => setArea(v as ConsoleArea)}>
        <TabsList>
          <TabsTrigger value="reports">{t("areas.reports")}</TabsTrigger>
          <TabsTrigger value="members">{t("areas.members")}</TabsTrigger>
          <TabsTrigger value="sharing">{t("areas.sharing")}</TabsTrigger>
          <TabsTrigger value="log">{t("areas.log")}</TabsTrigger>
        </TabsList>
      </Tabs>

      {area === "members" && <MembersArea initiativeId={initiative} />}
      {area === "log" && <LogArea communityId={communityId ?? 0} initiativeId={initiative} />}
      {area === "sharing" && (
        <SharingArea communityId={communityId ?? 0} initiativeId={initiative} />
      )}

      {area === "reports" && (
        <Tabs value={tab} onValueChange={(v) => showTab(v as "open" | "settled")}>
          <TabsList>
            <TabsTrigger value="open">{t("tabs.open")}</TabsTrigger>
            <TabsTrigger value="settled">{t("tabs.settled")}</TabsTrigger>
          </TabsList>
        </Tabs>
      )}

      {area === "reports" &&
        (isLoading ? (
          <SkeletonRegion>
            <CardGridSkeleton count={3} className="space-y-4" />
          </SkeletonRegion>
        ) : (
          <div className="space-y-4">
            {reports.length === 0 ? (
              <p className="text-muted-foreground text-sm">
                {tab === "open" ? t("empty.open") : t("empty.settled")}
              </p>
            ) : (
              // A reported comment is shown by its opening words.
              reports.map((report) => (
                <ReportCard
                  key={report.id}
                  report={report}
                  communityId={communityId ?? 0}
                  initiativeId={initiative}
                />
              ))
            )}

            {/* The server's page, which may be earlier than the one asked
                for when reports settled in between left fewer pages. */}
            {data && (
              <PaginationBar
                className="pt-2"
                page={data.page}
                pageSize={data.page_size}
                totalCount={data.total_count}
                hasNext={data.has_next}
                onPageChange={setPage}
              />
            )}
          </div>
        ))}
    </div>
  );
};

type ConsoleArea = "reports" | "members" | "sharing" | "log";
