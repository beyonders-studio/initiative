/**
 * The frame every front-door page sits in: a header that is always there,
 * with the same few places in it (Download, Pricing where plans are sold,
 * the docs, signing in and up), and a footer that lists the rest.
 *
 * On a phone the places fold into a menu under the header, and signing up
 * stays beside it as the one button.
 */

import { Link } from "@tanstack/react-router";
import { ArrowRight, ArrowUpRight, Menu, X } from "lucide-react";
import { type ReactNode, useState } from "react";
import { useTranslation } from "react-i18next";

import { LogoIcon } from "@/components/LogoIcon";
import { ModeToggle } from "@/components/ModeToggle";
import { Button } from "@/components/ui/button";
import { useLegalIndex } from "@/hooks/useLegalDocuments";
import { reopenConsent } from "@/lib/consent";
import { DOCS_URL, docsUrl, REPO_URL } from "@/lib/links";
import { cn } from "@/lib/utils";

import { LANDING_KEYFRAMES } from "./effects";
import { useFrontDoor } from "./useFrontDoor";

type Place = "download" | "pricing" | "whats-new";

const navLink =
  "inline-flex min-h-11 items-center rounded-lg px-3.5 font-medium text-foreground/80 hover:bg-muted hover:text-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring";

const Header = ({ current }: { current?: Place }) => {
  const { t } = useTranslation("landing");
  const { registrationOpen, showsPricing } = useFrontDoor();
  const [open, setOpen] = useState(false);

  const places: { key: Place; to: string; label: string }[] = [
    { key: "download", to: "/download", label: t("nav.download") },
    ...(showsPricing ? [{ key: "pricing" as const, to: "/pricing", label: t("nav.pricing") }] : []),
  ];

  return (
    <header className="sticky top-0 z-50 border-b bg-background/90 backdrop-blur-xl">
      <div className="mx-auto flex h-15 max-w-6xl items-center justify-between gap-4 px-4 sm:px-8 md:h-17">
        <Link
          to="/welcome"
          className="flex items-center gap-2.5 font-bold text-foreground text-xl tracking-tight sm:text-2xl"
          aria-label={t("nav.home")}
        >
          <LogoIcon className="h-8 w-8" aria-hidden="true" />
          <span className="pride-wordmark">initiative</span>
        </Link>
        <div className="flex items-center gap-1.5">
          <nav className="mr-2 hidden items-center gap-0.5 md:flex" aria-label={t("nav.mainAria")}>
            {places.map((place) => (
              <Link
                key={place.key}
                to={place.to}
                className={cn(navLink, current === place.key && "bg-muted text-foreground")}
                aria-current={current === place.key ? "page" : undefined}
              >
                {place.label}
              </Link>
            ))}
            <a href={DOCS_URL} target="_blank" rel="noopener noreferrer" className={navLink}>
              {t("nav.docs")}
            </a>
            {registrationOpen ? (
              <Link to="/login" search={true} className={navLink}>
                {t("nav.signIn")}
              </Link>
            ) : null}
          </nav>
          <div className="hidden md:block">
            <ModeToggle />
          </div>
          <Button asChild>
            {registrationOpen ? (
              <Link to="/start">{t("nav.signUp")}</Link>
            ) : (
              <Link to="/login" search={true}>
                {t("nav.signIn")}
              </Link>
            )}
          </Button>
          <Button
            variant="outline"
            size="icon"
            className="h-11 w-11 md:hidden"
            aria-label={t("nav.menu")}
            aria-expanded={open}
            aria-controls={open ? "landing-menu" : undefined}
            onClick={() => setOpen((value) => !value)}
          >
            {open ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
          </Button>
        </div>
      </div>
      {open ? (
        <nav
          id="landing-menu"
          className="border-t px-4 pt-2 pb-4 md:hidden"
          aria-label={t("nav.mainAria")}
        >
          {places.map((place) => (
            <Link
              key={place.key}
              to={place.to}
              className="flex min-h-14 items-center justify-between border-b font-semibold text-lg"
            >
              {place.label}
              <ArrowRight className="h-5 w-5" aria-hidden="true" />
            </Link>
          ))}
          <a
            href={DOCS_URL}
            target="_blank"
            rel="noopener noreferrer"
            className="flex min-h-14 items-center justify-between border-b font-semibold text-lg"
          >
            {t("nav.docs")}
            <ArrowUpRight className="h-5 w-5" aria-hidden="true" />
          </a>
          {registrationOpen ? (
            <Link
              to="/login"
              search={true}
              className="flex min-h-14 items-center justify-between font-semibold text-lg"
            >
              {t("nav.signIn")}
              <ArrowRight className="h-5 w-5" aria-hidden="true" />
            </Link>
          ) : null}
          <div className="flex justify-end pt-3">
            <ModeToggle />
          </div>
        </nav>
      ) : null}
    </header>
  );
};

const footerLink =
  "inline-flex min-h-9 items-center rounded text-muted-foreground text-sm hover:text-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring";

/** GitHub's mark, which lucide no longer draws. */
const GitHubMark = () => (
  <svg viewBox="0 0 24 24" className="h-4 w-4 fill-current" aria-hidden="true">
    <path d="M12 .5a11.5 11.5 0 0 0-3.64 22.41c.58.1.79-.25.79-.56v-2c-3.2.7-3.88-1.37-3.88-1.37-.53-1.34-1.29-1.7-1.29-1.7-1.05-.72.08-.7.08-.7 1.16.08 1.77 1.19 1.77 1.19 1.03 1.77 2.71 1.26 3.37.96.1-.75.4-1.26.73-1.55-2.56-.29-5.25-1.28-5.25-5.69 0-1.26.45-2.29 1.19-3.09-.12-.29-.52-1.47.11-3.06 0 0 .97-.31 3.17 1.18a11 11 0 0 1 5.77 0c2.2-1.49 3.17-1.18 3.17-1.18.63 1.59.23 2.77.11 3.06.74.8 1.19 1.83 1.19 3.09 0 4.42-2.7 5.39-5.26 5.68.41.36.78 1.06.78 2.14v3.17c0 .31.21.67.8.56A11.5 11.5 0 0 0 12 .5Z" />
  </svg>
);

const External = ({ href, children }: { href: string; children: ReactNode }) => (
  <a href={href} target="_blank" rel="noopener noreferrer" className={footerLink}>
    {children}
  </a>
);

const Footer = () => {
  const { t } = useTranslation("landing");
  const { showsPricing, cookieConsentEnabled } = useFrontDoor();
  const { documents } = useLegalIndex();

  return (
    <footer className="border-t">
      <div className="mx-auto max-w-6xl px-4 pt-14 pb-10 sm:px-8">
        <div className="grid grid-cols-2 gap-6 sm:gap-8 md:grid-cols-[2fr_1fr_1fr_1fr]">
          <div className="col-span-2 md:col-span-1">
            <div className="flex items-center gap-2.5 font-bold text-foreground text-xl">
              <LogoIcon className="h-7 w-7" aria-hidden="true" />
              <span className="pride-wordmark">initiative</span>
            </div>
            <p className="mt-3 max-w-xs text-muted-foreground text-sm">{t("footer.tagline")}</p>
          </div>
          <div>
            <h2 className="mb-2 font-bold text-sm">{t("footer.getIt")}</h2>
            <ul>
              <li>
                <Link to="/download" className={footerLink}>
                  {t("footer.download")}
                </Link>
              </li>
              {showsPricing ? (
                <li>
                  <Link to="/pricing" className={footerLink}>
                    {t("footer.pricing")}
                  </Link>
                </li>
              ) : null}
              <li>
                <Link to="/whats-new" className={footerLink}>
                  {t("footer.changelog")}
                </Link>
              </li>
            </ul>
          </div>
          <div>
            <h2 className="mb-2 font-bold text-sm">{t("footer.docs")}</h2>
            <ul>
              <li>
                <External href={docsUrl("getting-started/")}>{t("footer.gettingStarted")}</External>
              </li>
              <li>
                <External href={docsUrl("faq/")}>{t("footer.faq")}</External>
              </li>
              <li>
                <External href={docsUrl("running-a-server/")}>{t("footer.server")}</External>
              </li>
              <li>
                <External href={docsUrl("security/")}>{t("footer.security")}</External>
              </li>
            </ul>
          </div>
          <div>
            <h2 className="mb-2 font-bold text-sm">{t("footer.socials")}</h2>
            <ul>
              <li>
                <a
                  href={REPO_URL}
                  target="_blank"
                  rel="noopener noreferrer"
                  className={`${footerLink} gap-2`}
                >
                  <GitHubMark />
                  {t("footer.github")}
                </a>
              </li>
            </ul>
          </div>
        </div>
        <div className="mt-10 flex flex-wrap items-center gap-x-6 gap-y-2 text-muted-foreground text-sm">
          <p>{t("footer.copyright", { year: new Date().getFullYear() })}</p>
          {/* Every document the deployment publishes, not only the ones an
              account accepts: a refund policy has to be findable before
              anyone buys. None where it names no portal. */}
          {documents.map((document) =>
            document.url ? (
              <External key={document.slug} href={document.url}>
                {document.title}
              </External>
            ) : (
              <Link
                key={document.slug}
                to="/legal/$slug"
                params={{ slug: document.slug }}
                className={footerLink}
              >
                {document.title}
              </Link>
            )
          )}
          {/* Taking an answer back has to be as easy as giving one, and a
              front-door reader has no settings page to go to. Only where the
              deployment asks the question at all. */}
          {cookieConsentEnabled ? (
            <button type="button" onClick={reopenConsent} className={footerLink}>
              {t("footer.cookies")}
            </button>
          ) : null}
        </div>
      </div>
    </footer>
  );
};

const SkipLink = () => {
  const { t } = useTranslation("landing");
  return (
    <a
      href="#landing-main"
      className="sr-only z-[60] rounded-lg bg-primary px-4 py-2 font-semibold text-primary-foreground focus:not-sr-only focus:fixed focus:top-2 focus:left-2"
    >
      {t("nav.skip")}
    </a>
  );
};

export const LandingShell = ({ current, children }: { current?: Place; children: ReactNode }) => (
  <div className="min-h-screen overflow-x-clip bg-background text-foreground">
    <style>{LANDING_KEYFRAMES}</style>
    <SkipLink />
    <Header current={current} />
    <main id="landing-main">{children}</main>
    <Footer />
  </div>
);
