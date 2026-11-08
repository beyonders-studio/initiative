/**
 * Which page the wiki opens on, and which one a new page is copied from.
 *
 * These sit on Details rather than with the reading settings because they name
 * particular pages — they are facts about this wiki's contents, like its name
 * and its description, rather than choices about how it is read.
 *
 * Both save on pick. There is no combination of the two that has to be applied
 * at once, so there is nothing to submit.
 */

import { useTranslation } from "react-i18next";

import { useUpdateWiki, useWiki, useWikiPages } from "@/hooks/useWikis";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/ui/select";
import { Separator } from "@/ui/separator";

/** A labelled row: the control on the right, what it does underneath. */
const Setting = ({
  label,
  hint,
  control,
}: {
  label: string;
  hint?: string;
  control: React.ReactNode;
}) => (
  <div className="flex items-start justify-between gap-4 py-3">
    <div className="min-w-0 space-y-0.5">
      <p className="font-medium text-sm">{label}</p>
      {hint ? <p className="text-muted-foreground text-xs">{hint}</p> : null}
    </div>
    <div className="shrink-0">{control}</div>
  </div>
);

export const WikiPagesCard = ({ wikiId }: { wikiId: number }) => {
  const { t } = useTranslation(["wikis", "common"]);
  const isValidId = Number.isFinite(wikiId);

  const wikiQuery = useWiki(isValidId ? wikiId : null);
  const pagesQuery = useWikiPages(isValidId ? wikiId : null);
  const update = useUpdateWiki(wikiId);

  const wiki = wikiQuery.data;
  const pages = pagesQuery.data?.items ?? [];

  if (!wiki) return null;

  const canWrite = wiki.can.edit;
  const save = (patch: Parameters<typeof update.mutate>[0]) => {
    if (canWrite) update.mutate(patch);
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("settings.pages")}</CardTitle>
        <CardDescription>{t("settings.pagesDescription")}</CardDescription>
      </CardHeader>
      <CardContent>
        <Setting
          label={t("settings.home")}
          hint={t("settings.homeDescription")}
          control={
            <Select
              value={wiki.home_page_id ? String(wiki.home_page_id) : "none"}
              onValueChange={(value) =>
                save({ home_page_id: value === "none" ? null : Number(value) })
              }
              disabled={!canWrite}
            >
              <SelectTrigger className="w-48">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="none">{t("settings.homeNone")}</SelectItem>
                {pages.map((page) => (
                  <SelectItem key={page.id} value={String(page.id)}>
                    {page.title || t("common:untitled")}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          }
        />

        <Separator />

        <Setting
          label={t("settings.template")}
          hint={t("settings.templateDescription")}
          control={
            <Select
              value={wiki.template_page_id ? String(wiki.template_page_id) : "none"}
              onValueChange={(value) =>
                save({ template_page_id: value === "none" ? null : Number(value) })
              }
              disabled={!canWrite}
            >
              <SelectTrigger className="w-48">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="none">{t("settings.templateNone")}</SelectItem>
                {pages.map((page) => (
                  <SelectItem key={page.id} value={String(page.id)}>
                    {page.title || t("common:untitled")}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          }
        />
      </CardContent>
    </Card>
  );
};
