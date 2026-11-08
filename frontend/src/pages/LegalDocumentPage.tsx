import { Link, useParams } from "@tanstack/react-router";
import { ArrowLeft } from "lucide-react";
import { useTranslation } from "react-i18next";

import { LogoIcon } from "@/components/LogoIcon";
import { Markdown } from "@/components/Markdown";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useLegalDocument, useLegalIndex } from "@/hooks/useLegalDocuments";

/**
 * One of the deployment's legal documents, read in the app.
 *
 * Public, because the signup form links here and nobody is signed in yet, and
 * rendered here rather than linked out to for the same reason the landing
 * page renders the price book: the reader stays where they were. A document
 * kept elsewhere (the customer's own contract) has no text here: the page
 * links to it.
 */
export const LegalDocumentPage = () => {
  const { t } = useTranslation(["legal", "common"]);
  const { slug } = useParams({ strict: false }) as { slug?: string };
  const { documents, enabled, isLoading } = useLegalIndex();
  const entry = documents.find((candidate) => candidate.slug === slug);
  const elsewhere = entry?.url ?? null;
  const document = useLegalDocument(enabled && !isLoading && !elsewhere ? slug : undefined);

  return (
    <div className="flex min-h-app flex-col items-center bg-muted/60 px-4 py-10">
      <Link
        // The app packages have no front page; sign-in is where they start.
        to={__IS_CAPACITOR__ ? "/login" : "/welcome"}
        className="mb-6 flex items-center gap-3 font-semibold text-2xl text-primary tracking-tight"
      >
        <LogoIcon className="h-8 w-8" aria-hidden="true" focusable="false" />
        <span className="pride-wordmark">{t("common:appName")}</span>
      </Link>
      <Card className="w-full max-w-3xl shadow-lg">
        <CardHeader>
          <CardTitle>{entry?.title ?? t("legal:documentFallbackTitle")}</CardTitle>
          {entry?.effective_date ? (
            <p className="text-muted-foreground text-xs">
              {t("legal:effective", { date: entry.effective_date })}
              {entry.version ? ` · ${t("legal:version", { version: entry.version })}` : null}
            </p>
          ) : null}
        </CardHeader>
        <CardContent>
          {document.isLoading ? (
            <p className="text-muted-foreground text-sm">{t("common:loading")}</p>
          ) : null}
          {elsewhere ? (
            <a
              href={elsewhere}
              target="_blank"
              rel="noreferrer"
              className="text-primary text-sm underline-offset-4 hover:underline"
            >
              {t("legal:readWhereKept")}
            </a>
          ) : null}
          {!elsewhere && !document.isLoading && (!enabled || document.isError) ? (
            <p className="text-muted-foreground text-sm">{t("legal:unavailable")}</p>
          ) : null}
          {document.data ? <Markdown remoteImages content={document.data} /> : null}
        </CardContent>
      </Card>
      <Link
        to="/login"
        className="mt-6 flex items-center gap-1 text-muted-foreground text-sm hover:text-foreground"
      >
        <ArrowLeft className="h-4 w-4" aria-hidden="true" />
        {t("legal:backToSignIn")}
      </Link>
    </div>
  );
};
