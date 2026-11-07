import { useTranslation } from "react-i18next";

import { useThirdPartyNotices } from "@/hooks/useThirdPartyNotices";
import { Card, CardContent } from "@/ui/card";
import { Skeleton } from "@/ui/skeleton";

/**
 * The third-party licence notices the app ships with, read inside the app.
 *
 * Reached only from the version dialog. A plain link to the text file would do
 * on the web, but in the phone apps it would leave for the system browser,
 * which cannot see a file inside the app, so the page fetches the bundled file
 * and shows it here instead.
 */
export const LicencesPage = () => {
  const { t } = useTranslation("communities");
  const notices = useThirdPartyNotices();

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <h1 className="font-semibold text-3xl tracking-tight">{t("version.licencesTitle")}</h1>
      <Card>
        <CardContent className="py-6">
          {notices.isLoading ? (
            <div className="space-y-2">
              <Skeleton className="h-4 w-2/3" />
              <Skeleton className="h-4 w-1/2" />
            </div>
          ) : notices.data ? (
            <pre className="overflow-x-auto whitespace-pre-wrap break-words font-mono text-muted-foreground text-xs">
              {notices.data}
            </pre>
          ) : (
            <p className="text-muted-foreground text-sm">{t("version.licencesUnavailable")}</p>
          )}
        </CardContent>
      </Card>
    </div>
  );
};
