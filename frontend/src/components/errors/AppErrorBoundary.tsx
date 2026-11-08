import { TriangleAlert } from "lucide-react";
import { Component, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { ErrorState, isStaleBundleError, StaleBundleState } from "@/components/errors/ErrorPages";
import { Button } from "@/ui/button";

const AppErrorFallback = ({ error }: { error: unknown }) => {
  const { t } = useTranslation("common");

  if (isStaleBundleError(error)) {
    return <StaleBundleState fullScreen />;
  }

  return (
    <ErrorState
      fullScreen
      icon={<TriangleAlert aria-hidden="true" />}
      title={t("errorPage.title")}
      description={t("errorPage.appDescription")}
      error={error}
      actions={<Button onClick={() => window.location.reload()}>{t("errorPage.reload")}</Button>}
    />
  );
};

/**
 * The last boundary, above the providers and the router. The router catches
 * what a route renders; this catches the providers and anything mounted beside
 * the router. The app's state is gone by the time it shows, so the one way on
 * is a reload.
 */
export class AppErrorBoundary extends Component<
  { children: ReactNode },
  // Boxed so a thrown falsy value still counts as caught.
  { caught: { error: unknown } | null }
> {
  state = { caught: null as { error: unknown } | null };

  static getDerivedStateFromError(error: unknown) {
    return { caught: { error } };
  }

  render() {
    const { caught } = this.state;
    return caught ? <AppErrorFallback error={caught.error} /> : this.props.children;
  }
}
