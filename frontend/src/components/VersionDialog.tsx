import { Link } from "@tanstack/react-router";
import { CheckCircle2, ChevronRight, Download, ExternalLink, Loader2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { ChangelogEntry } from "@/api/generated/initiativeAPI.schemas";
import { Markdown } from "@/components/Markdown";
import { useChangelog } from "@/hooks/useSettings";
import { CHANGELOG_URL, RELEASES_URL } from "@/lib/links";
import { Badge } from "@/ui/badge";
import { Button } from "@/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/ui/collapsible";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/ui/dialog";
import { cn } from "@/ui/lib/utils";
import { ScrollArea } from "@/ui/scroll-area";

/**
 * What version this is, and what has changed lately — opened from My settings,
 * or from the "updated" toast once a new version is running (see
 * ``components/UpdatedNotice``).
 *
 * Pass ``children`` for a trigger, or ``open``/``onOpenChange`` to open it from
 * elsewhere.
 */
interface VersionDialogProps {
  children?: React.ReactNode;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  currentVersion: string;
  latestVersion?: string | null;
  hasUpdate?: boolean;
  isLoadingVersion?: boolean;
}

/** One release's notes. Its title opens and closes it; the newest starts
 *  open, and an older one stays closed until asked for, its pictures with it. */
const Release = ({
  entry,
  defaultOpen,
  className,
}: {
  entry: ChangelogEntry;
  defaultOpen: boolean;
  className?: string;
}) => {
  const { t } = useTranslation("communities");
  return (
    <Collapsible defaultOpen={defaultOpen} className={className}>
      <h4 className="font-semibold text-base">
        <CollapsibleTrigger className="group flex w-full items-center gap-2 text-left">
          <ChevronRight
            className="h-4 w-4 shrink-0 transition-transform group-data-[state=open]:rotate-90"
            aria-hidden="true"
          />
          {t("version.version", { version: entry.version })}
          <Badge variant="outline" className="font-normal text-xs">
            {entry.date}
          </Badge>
        </CollapsibleTrigger>
      </h4>
      <CollapsibleContent className="pt-3 pl-6">
        {entry.changes.trim() ? (
          <Markdown surface="release" remoteImages content={entry.changes} />
        ) : (
          <p className="text-muted-foreground text-sm">{t("version.noDetailedChanges")}</p>
        )}
      </CollapsibleContent>
    </Collapsible>
  );
};

export const VersionDialog = ({
  children,
  open,
  onOpenChange,
  currentVersion,
  latestVersion,
  hasUpdate = false,
  isLoadingVersion = false,
}: VersionDialogProps) => {
  const { t } = useTranslation("communities");

  const { data, isLoading } = useChangelog({ limit: 20 }, { enabled: open ?? true });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      {children ? <DialogTrigger asChild>{children}</DialogTrigger> : null}
      <DialogContent className="flex h-[80vh] flex-col gap-0 sm:max-w-2xl">
        <DialogHeader className="shrink-0">
          <DialogTitle>{t("version.versionInformation")}</DialogTitle>
          <DialogDescription className="sr-only">
            {t("version.currentVersionAndChangelog")}
          </DialogDescription>
        </DialogHeader>

        <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-hidden">
          <div className="shrink-0 space-y-4 border-b pb-4">
            {hasUpdate && (
              <div className="flex items-center gap-1.5 font-medium text-primary text-sm">
                <Download className="h-4 w-4" />
                <span>{t("version.updateAvailable")}</span>
              </div>
            )}
            <div className="space-y-3 text-sm">
              <div className="flex items-center justify-between">
                <span className="text-muted-foreground">{t("version.currentVersion")}</span>
                <span className="font-medium font-mono">v{currentVersion}</span>
              </div>
              {isLoadingVersion ? (
                <div className="flex items-center justify-between">
                  <span className="text-muted-foreground">{t("version.latestVersion")}</span>
                  <span className="text-muted-foreground">{t("version.latestVersionLoading")}</span>
                </div>
              ) : latestVersion ? (
                <div className="flex items-center justify-between">
                  <span className="text-muted-foreground">{t("version.latestVersion")}</span>
                  <span className={cn("font-medium font-mono", hasUpdate && "text-primary")}>
                    v{latestVersion}
                  </span>
                </div>
              ) : (
                <div className="flex items-center justify-between">
                  <span className="text-muted-foreground">{t("version.latestVersion")}</span>
                  <span className="text-muted-foreground text-xs">
                    {t("version.latestVersionUnavailable")}
                  </span>
                </div>
              )}
            </div>
            {!hasUpdate && latestVersion && (
              <div className="flex items-center gap-1.5 text-green-600 text-sm dark:text-green-400">
                <CheckCircle2 className="h-4 w-4" />
                <span>{t("version.upToDate")}</span>
              </div>
            )}
            {hasUpdate && (
              <p className="text-muted-foreground text-sm">
                {t("version.newVersionOnGitHub")}{" "}
                <a
                  href={RELEASES_URL}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-primary hover:underline"
                >
                  GitHub
                </a>
              </p>
            )}
          </div>

          {/* Changelog Section */}
          <div className="flex min-h-0 flex-1 flex-col">
            <h3 className="mb-3 shrink-0 font-semibold text-lg">{t("version.changelog")}</h3>
            {isLoading ? (
              <div className="flex items-center justify-center py-8">
                <Loader2 className="h-6 w-6 animate-spin" />
              </div>
            ) : data?.entries && data.entries.length > 0 ? (
              <ScrollArea className="[&_[data-radix-scroll-area-viewport]>div]:block! flex-1">
                {/* Radix lays the viewport's content out as a table, which
                    widens to fit a strip of pictures instead of letting it
                    scroll; the override above keeps it to the dialog's width. */}
                <div className="space-y-4 pr-6">
                  {data.entries.map((entry, entryIdx) => (
                    <Release
                      key={entry.version}
                      entry={entry}
                      defaultOpen={entryIdx === 0}
                      className={entryIdx > 0 ? "border-t pt-4" : undefined}
                    />
                  ))}
                </div>
              </ScrollArea>
            ) : (
              <p className="text-muted-foreground text-sm">{t("version.noChangelog")}</p>
            )}
            <div className="shrink-0 border-t pt-3">
              <Button variant="outline" size="sm" className="w-full" asChild>
                <a
                  href={CHANGELOG_URL}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center justify-center gap-2"
                >
                  {t("version.viewAllChanges")}
                  <ExternalLink className="h-4 w-4" />
                </a>
              </Button>
              {/* The licence notices that travel with the app; out of the
                  way on purpose, since few people go looking. */}
              <DialogClose asChild>
                <Link
                  to="/licences"
                  className="mt-3 block text-center text-muted-foreground text-xs hover:text-foreground hover:underline"
                >
                  {t("version.openSourceLicences")}
                </Link>
              </DialogClose>
            </div>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
};
