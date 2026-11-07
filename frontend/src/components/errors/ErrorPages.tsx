import { type ErrorComponentProps, Link, useCanGoBack, useRouter } from "@tanstack/react-router";
import { FileQuestion, RefreshCw, TriangleAlert } from "lucide-react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/ui/button";
import {
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/ui/empty";
import { cn } from "@/ui/lib/utils";

/**
 * Whether an error is a lazily loaded chunk that is no longer on the server —
 * what a tab open across a deployment meets when it navigates. The router
 * already reloads once for this; reaching a page with it means that did not
 * help, and the reader is offered a reload of their own rather than a fault.
 * Same messages the router matches on (Chrome, Firefox, Safari).
 */
export const isStaleBundleError = (error: unknown): boolean => {
  const message = (error as { message?: unknown } | null)?.message;
  if (typeof message !== "string") {
    return false;
  }
  return (
    message.startsWith("Failed to fetch dynamically imported module") ||
    message.startsWith("error loading dynamically imported module") ||
    message.startsWith("Importing a module script failed")
  );
};

const errorText = (error: unknown): string | null => {
  if (error instanceof Error) {
    return import.meta.env.DEV && error.stack ? error.stack : error.message;
  }
  return typeof error === "string" ? error : null;
};

interface ErrorStateProps {
  icon: ReactNode;
  title: string;
  description: string;
  actions: ReactNode;
  error?: unknown;
  /** Fill the window, for a failure outside the app shell. */
  fullScreen?: boolean;
}

/** The body every error screen shares: what happened, and what to do next. */
export const ErrorState = ({
  icon,
  title,
  description,
  actions,
  error,
  fullScreen = false,
}: ErrorStateProps) => {
  const { t } = useTranslation("common");
  const details = error === undefined ? null : errorText(error);

  return (
    <Empty role="alert" className={cn(fullScreen ? "min-h-screen" : "min-h-[60vh]")}>
      <EmptyHeader>
        <EmptyMedia variant="icon">{icon}</EmptyMedia>
        <EmptyTitle>{title}</EmptyTitle>
        <EmptyDescription>{description}</EmptyDescription>
      </EmptyHeader>
      <EmptyContent>
        <div className="flex flex-wrap justify-center gap-2">{actions}</div>
        {details ? (
          <details className="w-full text-left">
            <summary className="cursor-pointer text-center text-muted-foreground text-xs">
              {t("errorPage.details")}
            </summary>
            <pre className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap break-words rounded-md bg-muted p-3 text-xs">
              {details}
            </pre>
          </details>
        ) : null}
      </EmptyContent>
    </Empty>
  );
};

const reload = () => window.location.reload();

/** Offered in place of a fault when the page's code was replaced by a newer release. */
export const StaleBundleState = ({ fullScreen }: { fullScreen?: boolean }) => {
  const { t } = useTranslation("common");
  return (
    <ErrorState
      fullScreen={fullScreen}
      icon={<RefreshCw aria-hidden="true" />}
      title={t("errorPage.updatedTitle")}
      description={t("errorPage.updatedDescription")}
      actions={<Button onClick={reload}>{t("errorPage.reload")}</Button>}
    />
  );
};

/**
 * The router's default error screen. It takes the place of the route that
 * failed, so a page that breaks keeps the app shell around it.
 */
export const RouteErrorPage = ({ error, reset }: ErrorComponentProps) => {
  const { t } = useTranslation(["common", "nav"]);
  const router = useRouter();

  if (isStaleBundleError(error)) {
    return <StaleBundleState />;
  }

  const retry = () => {
    reset();
    void router.invalidate();
  };

  return (
    <ErrorState
      icon={<TriangleAlert aria-hidden="true" />}
      title={t("errorPage.title")}
      description={t("errorPage.description")}
      error={error}
      actions={
        <>
          <Button onClick={retry}>{t("tryAgain")}</Button>
          <Button variant="outline" asChild>
            <Link to="/">{t("errorPage.toHome", { home: t("nav:home") })}</Link>
          </Button>
        </>
      }
    />
  );
};

/** The router's default screen for an address that leads nowhere. */
export const NotFoundPage = () => {
  const { t } = useTranslation(["common", "nav"]);
  const router = useRouter();
  const canGoBack = useCanGoBack();

  return (
    <ErrorState
      icon={<FileQuestion aria-hidden="true" />}
      title={t("notFoundPage.title")}
      description={t("notFoundPage.description")}
      actions={
        <>
          {canGoBack ? (
            <Button variant="outline" onClick={() => router.history.back()}>
              {t("back")}
            </Button>
          ) : null}
          <Button asChild>
            <Link to="/">{t("errorPage.toHome", { home: t("nav:home") })}</Link>
          </Button>
        </>
      }
    />
  );
};
