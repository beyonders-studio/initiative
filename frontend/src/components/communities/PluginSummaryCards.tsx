import type { TFunction } from "i18next";
import { useTranslation } from "react-i18next";

import type {
  PluginDataResponse,
  PluginSummaryRead,
  PluginSummaryReturn,
} from "@/api/generated/initiativeAPI.schemas";
import { useListPluginSummaries, useReadPluginSummary } from "@/api/generated/plugins/plugins";
import { SettingsSection } from "@/components/settings/SettingsSection";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { parseDateValue } from "@/lib/formatDate";
import { localized } from "@/lib/widgets/widgetMeta";
import { dateTimeFormat, numberFormat } from "@/ui/lib/intl";
import { Progress } from "@/ui/progress";

type Translate = TFunction<["communities", "common"]>;

/** One value as the viewer's language writes it, or null when there is none. */
const formatOne = (value: unknown, type: string, lang: string, t: Translate): string | null => {
  if (value == null) return null;
  if (type === "int" && typeof value === "number") {
    return numberFormat(lang).format(value);
  }
  if (type === "datetime") {
    const date = parseDateValue(String(value));
    return date ? dateTimeFormat(lang, { dateStyle: "long" }).format(date) : null;
  }
  if (type === "bool" && typeof value === "boolean") {
    return value ? t("common:yes") : t("common:no");
  }
  return String(value);
};

/** A declared return's answer: a single value from `values`, or a list's
 *  values gathered from `rows`, joined. */
const formatReturn = (
  item: PluginSummaryReturn,
  values: Record<string, unknown>,
  rows: Record<string, unknown>[],
  lang: string,
  t: Translate
): string | null => {
  if (!item.list) return formatOne(values[item.key], item.type, lang, t);
  const shown = rows
    .map((row) => formatOne(row[item.key], item.type, lang, t))
    .filter((value): value is string => value != null);
  return shown.length ? shown.join(", ") : null;
};

/** One plug-in's figures, each labelled by the plug-in's own declaration — so
 *  nothing here knows what any plug-in measures. Drawn from whichever read the
 *  surface holding it makes. */
export const PluginSummaryFigures = ({
  summary,
  data,
  isError,
}: {
  summary: PluginSummaryRead;
  data: PluginDataResponse | undefined;
  isError: boolean;
}) => {
  const { t, i18n } = useTranslation(["communities", "common"]);
  const lang = i18n.resolvedLanguage ?? i18n.language;
  const values = (data?.values ?? {}) as Record<string, unknown>;
  const rows = (data?.rows ?? []) as Record<string, unknown>[];
  const returns = summary.returns ?? [];

  // A pure ceiling is drawn inside the measure counted against it; one that is
  // itself counted against something is still a measure of its own.
  const ceilings = new Set(returns.flatMap((item) => (item.of ? [item.of] : [])));
  const figures = returns.filter((item) => item.of || !ceilings.has(item.key));

  return isError ? (
    <p className="text-muted-foreground text-sm">{t("usagePanel.summaryUnavailable")}</p>
  ) : data ? (
    figures.map((item) => {
      const shown = formatReturn(item, values, rows, lang, t);
      if (shown == null) return null;
      const used = values[item.key];
      const ceiling = item.of ? values[item.of] : null;
      // Zero is a real ceiling; null (or absent) is none.
      const max =
        typeof ceiling === "number" && ceiling >= 0 && typeof used === "number" ? ceiling : null;
      const pct =
        max == null
          ? null
          : max === 0
            ? 100
            : Math.min(100, Math.round(((used as number) / max) * 100));
      return (
        <div key={item.key} className="space-y-2">
          <div className="flex justify-between gap-4 text-sm">
            <span className="font-medium">
              {localized(item.label ?? undefined, lang) ?? item.key}
            </span>
            <span className="text-right text-muted-foreground">
              {max == null
                ? shown
                : t("usagePanel.usedOfMax", {
                    used: shown,
                    max: formatOne(max, "int", lang, t),
                  })}
            </span>
          </div>
          {pct != null && <Progress value={pct} />}
        </div>
      );
    })
  ) : null;
};

const PluginSummaryCard = ({ summary }: { summary: PluginSummaryRead }) => {
  const communityId = useActiveCommunityId();
  const { data, isError } = useReadPluginSummary(communityId, summary.plugin_id);
  return (
    <SettingsSection title={summary.name} contentClassName="space-y-6">
      <PluginSummaryFigures summary={summary} data={data} isError={isError} />
    </SettingsSection>
  );
};

/** Where the community stands with each installed plug-in that says.
 *
 * On the Usage tab, below the community's own figures. The list comes from the
 * settings rung, like everything else on the tab, so support lent the seat sees
 * the same cards as an admin. Each card is titled with its install's name. One
 * read per card, so a plug-in that does not answer says so on its own card and
 * holds up no other. */
export const PluginSummaryCards = () => {
  const communityId = useActiveCommunityId();
  const { data } = useListPluginSummaries(communityId);

  return (
    <>
      {(data?.items ?? []).map((summary) => (
        <PluginSummaryCard key={summary.plugin_id} summary={summary} />
      ))}
    </>
  );
};
