/**
 * Getting Initiative onto a device, the visitor's own device first.
 *
 * Android gets a real file: the APK attached to the release the server's
 * native floor names, which is the newest one that runs this server's web
 * bundle. A computer gets its installer from the release its own floor names,
 * or installs from the browser: in one click where the browser offers its own
 * install prompt and by the guide where it doesn't. An iPhone adds it to the
 * home screen from Safari.
 */

import { Link } from "@tanstack/react-router";
import type { LucideIcon } from "lucide-react";
import {
  ArrowUpRight,
  Download,
  Globe,
  KeyRound,
  Monitor,
  RefreshCw,
  Smartphone,
  User,
} from "lucide-react";
import { type ReactNode, useEffect, useMemo, useState } from "react";
import { Trans, useTranslation } from "react-i18next";

import { useGetFcmConfig } from "@/api/generated/settings/settings";
import {
  androidApkUrl,
  desktopInstallerUrl,
  docsUrl,
  OBTAINIUM_URL,
  RELEASES_URL,
} from "@/lib/links";
import {
  type DesktopOs,
  detectDesktopOs,
  detectPlatform,
  type VisitorPlatform,
} from "@/lib/platform";
import { Button } from "@/ui/button";

import { DarkBand } from "./DarkBand";
import { SiteShell } from "./SiteShell";
import { useFrontDoor } from "./useFrontDoor";
import { usePageMeta } from "./usePageMeta";

const INSTALL_GUIDE = docsUrl("getting-started/install-the-app/");
const BROWSER_INSTALL = `${INSTALL_GUIDE}#install-it-from-the-browser`;

/** The browser's own install prompt, where it offers one (Chrome, Edge). */
interface InstallPromptEvent extends Event {
  prompt: () => Promise<void>;
}

const useInstallPrompt = () => {
  const [event, setEvent] = useState<InstallPromptEvent | null>(null);
  useEffect(() => {
    const capture = (e: Event) => {
      e.preventDefault();
      setEvent(e as InstallPromptEvent);
    };
    const installed = () => setEvent(null);
    window.addEventListener("beforeinstallprompt", capture);
    window.addEventListener("appinstalled", installed);
    return () => {
      window.removeEventListener("beforeinstallprompt", capture);
      window.removeEventListener("appinstalled", installed);
    };
  }, []);
  // A prompt can be shown once. After that, whatever the answer, it is spent,
  // and the buttons go back to pointing at the guide.
  const consume = () => {
    if (!event) return;
    void event.prompt().finally(() => setEvent(null));
  };
  return { available: event != null, consume };
};

const DESKTOP_BUTTON = {
  windows: "download.windowsButton",
  mac: "download.macButton",
  linux: "download.linuxButton",
} as const;

/** The button that gets Initiative onto this computer: the browser's prompt
 *  when it has one, the guide when it doesn't. */
const InstallButton = ({
  prompt,
  className,
  variant,
  children,
}: {
  prompt: ReturnType<typeof useInstallPrompt>;
  className?: string;
  variant?: "default" | "outline";
  children: ReactNode;
}) =>
  prompt.available ? (
    <Button size="lg" variant={variant} className={className} onClick={prompt.consume}>
      {children}
    </Button>
  ) : (
    <Button size="lg" variant={variant} className={className} asChild>
      <a href={BROWSER_INSTALL} target="_blank" rel="noopener noreferrer">
        {children}
      </a>
    </Button>
  );

const ApkButton = ({
  minNativeVersion,
  className,
  variant,
  children,
}: {
  minNativeVersion: string | null;
  className?: string;
  variant?: "default" | "outline";
  children: ReactNode;
}) => (
  <Button size="lg" variant={variant} className={className} asChild>
    {minNativeVersion ? (
      <a href={androidApkUrl(minNativeVersion)} download data-testid="android-apk">
        {children}
      </a>
    ) : (
      <a href={RELEASES_URL} target="_blank" rel="noopener noreferrer">
        {children}
      </a>
    )}
  </Button>
);

/** The installer for this computer, from the release the server's desktop
 *  floor names; every release when either is unknown. */
const DesktopButton = ({
  os,
  minDesktopVersion,
  className,
  variant,
  children,
}: {
  os: DesktopOs | null;
  minDesktopVersion: string | null;
  className?: string;
  variant?: "default" | "outline";
  children: ReactNode;
}) => (
  <Button size="lg" variant={variant} className={className} asChild>
    {os && minDesktopVersion ? (
      <a href={desktopInstallerUrl(minDesktopVersion, os)} download data-testid="desktop-installer">
        {children}
      </a>
    ) : (
      <a href={RELEASES_URL} target="_blank" rel="noopener noreferrer">
        {children}
      </a>
    )}
  </Button>
);

const PlatformCard = ({
  icon: Icon,
  title,
  sub,
  platform,
  children,
}: {
  icon: LucideIcon;
  title: string;
  sub: string;
  platform: string;
  children: ReactNode;
}) => (
  <li
    className="flex flex-col gap-3.5 rounded-2xl border bg-card p-5 sm:p-6"
    data-platform={platform}
  >
    <div className="flex items-center gap-3">
      <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-primary/10 text-primary">
        <Icon className="h-5 w-5" aria-hidden="true" />
      </span>
      <div>
        <h3 className="font-bold text-lg">{title}</h3>
        <p className="text-muted-foreground text-sm">{sub}</p>
      </div>
    </div>
    {children}
  </li>
);

const Fact = ({ icon: Icon, title, body }: { icon: LucideIcon; title: string; body: string }) => (
  <li className="flex items-start gap-3.5 rounded-2xl bg-muted/60 p-5">
    <Icon className="mt-0.5 h-5 w-5 shrink-0 text-primary" aria-hidden="true" />
    <div>
      <h3 className="font-bold">{title}</h3>
      <p className="mt-0.5 text-muted-foreground text-sm">{body}</p>
    </div>
  </li>
);

const PLATFORM_NAME: Record<
  VisitorPlatform,
  "download.platformAndroid" | "download.platformIos" | "download.platformDesktop"
> = {
  android: "download.platformAndroid",
  ios: "download.platformIos",
  desktop: "download.platformDesktop",
};

export const DownloadPage = () => {
  const { t } = useTranslation("landing");
  const { config, passkeyLoginEnabled } = useFrontDoor();
  usePageMeta(t("meta.downloadTitle"), t("meta.downloadDescription"));
  // The Android app only gets push where this server has it switched on.
  const fcm = useGetFcmConfig(undefined, { query: { staleTime: 300_000 } });
  const push = fcm.data?.enabled === true;
  const minNativeVersion = config?.min_native_version ?? null;
  const minDesktopVersion = config?.min_desktop_version ?? null;
  const platform = useMemo(() => detectPlatform(), []);
  const desktopOs = useMemo<DesktopOs | null>(() => detectDesktopOs(), []);
  const prompt = useInstallPrompt();
  const desktopLabel = t(desktopOs ? DESKTOP_BUTTON[desktopOs] : "download.desktopButton");

  return (
    <SiteShell current="download">
      <DarkBand stars aria-labelledby="landing-download-title">
        <div className="relative mx-auto max-w-6xl px-4 pt-10 pb-20 sm:px-8 sm:pt-18 sm:pb-24">
          <h1
            id="landing-download-title"
            className="font-extrabold text-[2.6rem] leading-tight tracking-tight sm:text-6xl"
          >
            {t("download.title")}{" "}
            <span className="text-amber-400">{t("download.titleHighlight")}</span>
          </h1>
          <p className="mt-4 max-w-2xl text-lg text-slate-300">
            {t(push ? "download.descriptionPush" : "download.description")}
          </p>
        </div>
      </DarkBand>

      <div className="mx-auto max-w-6xl px-4 sm:px-8">
        <section
          className="relative -mt-12 grid items-center gap-5 rounded-3xl border bg-card p-5 shadow-2xl sm:gap-8 sm:p-9 md:grid-cols-[1fr_auto]"
          aria-labelledby="landing-download-feature"
        >
          <div>
            <p className="font-semibold text-amber-700 text-sm dark:text-amber-400">
              {t("download.detected", { platform: t(PLATFORM_NAME[platform]) })}
            </p>
            <h2
              id="landing-download-feature"
              className="mt-1 font-extrabold text-2xl tracking-tight sm:text-3xl"
            >
              {t(`download.${platform}Title`)}
            </h2>
            <p className="mt-2 text-muted-foreground">
              {t(
                platform === "android"
                  ? push
                    ? "download.androidBodyPush"
                    : "download.androidBody"
                  : `download.${platform}Body`
              )}
            </p>
          </div>
          <div className="flex flex-col gap-2.5 md:min-w-72">
            {platform === "android" ? (
              <>
                <ApkButton minNativeVersion={minNativeVersion} className="h-14 text-base">
                  <Download className="h-5 w-5" aria-hidden="true" />
                  {t("download.androidButton")}
                </ApkButton>
                {minNativeVersion ? (
                  <p className="text-center text-muted-foreground text-sm">
                    {t("download.version", { version: minNativeVersion })}
                  </p>
                ) : null}
              </>
            ) : platform === "ios" ? (
              <Button size="lg" className="h-14 text-base" asChild>
                <a href={BROWSER_INSTALL} target="_blank" rel="noopener noreferrer">
                  {t("download.iosButton")}
                  <ArrowUpRight className="h-4 w-4" aria-hidden="true" />
                </a>
              </Button>
            ) : (
              <>
                <DesktopButton
                  os={desktopOs}
                  minDesktopVersion={minDesktopVersion}
                  className="h-14 text-base"
                >
                  <Download className="h-5 w-5" aria-hidden="true" />
                  {desktopLabel}
                </DesktopButton>
                <InstallButton prompt={prompt} variant="outline">
                  {t("download.browserInstall")}
                </InstallButton>
                <p className="text-center text-muted-foreground text-sm">
                  {minDesktopVersion
                    ? t("download.version", { version: minDesktopVersion })
                    : t("download.desktopMeta")}
                </p>
              </>
            )}
          </div>
        </section>

        <ul
          className="mt-8 grid gap-3 sm:mt-10 sm:gap-4 md:grid-cols-2 lg:grid-cols-4"
          aria-label={t("download.cardsAria")}
        >
          <PlatformCard
            icon={Smartphone}
            title={t("download.android.title")}
            sub={t("download.android.sub")}
            platform="android"
          >
            <p className="flex-1 text-muted-foreground text-sm">
              <Trans
                t={t}
                i18nKey={push ? "download.android.bodyPush" : "download.android.body"}
                components={{
                  1: (
                    // biome-ignore lint/a11y/useAnchorContent: Trans fills the link with the translated text
                    <a
                      href={OBTAINIUM_URL}
                      className="font-medium text-primary underline-offset-4 hover:underline"
                    />
                  ),
                }}
              />
            </p>
            <ApkButton minNativeVersion={minNativeVersion} variant="outline" className="w-full">
              <Download className="h-4 w-4" aria-hidden="true" />
              {minNativeVersion ? t("download.android.button") : t("download.releases")}
            </ApkButton>
          </PlatformCard>
          <PlatformCard
            icon={Smartphone}
            title={t("download.ios.title")}
            sub={t("download.ios.sub")}
            platform="ios"
          >
            <ol className="flex-1 list-decimal pl-5 text-sm">
              <li>{t("download.ios.step1")}</li>
              <li>{t("download.ios.step2")}</li>
              <li>{t("download.ios.step3")}</li>
            </ol>
            <Button variant="outline" size="lg" className="w-full" asChild>
              <a href={BROWSER_INSTALL} target="_blank" rel="noopener noreferrer">
                {t("download.ios.button")}
                <ArrowUpRight className="h-4 w-4" aria-hidden="true" />
              </a>
            </Button>
          </PlatformCard>
          <PlatformCard
            icon={Monitor}
            title={t("download.desktop.title")}
            sub={t("download.desktop.sub")}
            platform="desktop"
          >
            <p className="flex-1 text-muted-foreground text-sm">{t("download.desktop.body")}</p>
            <DesktopButton
              // A phone's browser also says Linux; only a computer is offered a file.
              os={platform === "desktop" ? desktopOs : null}
              minDesktopVersion={minDesktopVersion}
              variant="outline"
              className="w-full"
            >
              <Download className="h-4 w-4" aria-hidden="true" />
              {platform === "desktop" && desktopOs && minDesktopVersion
                ? desktopLabel
                : t("download.releases")}
            </DesktopButton>
            <InstallButton prompt={prompt} variant="outline" className="w-full">
              {t("download.browserInstall")}
            </InstallButton>
          </PlatformCard>
          <PlatformCard
            icon={Globe}
            title={t("download.browser.title")}
            sub={t("download.browser.sub")}
            platform="browser"
          >
            <p className="flex-1 text-muted-foreground text-sm">{t("download.browser.body")}</p>
            <Button variant="outline" size="lg" className="w-full" asChild>
              <Link to="/login" search={true}>
                {t("download.browser.button")}
              </Link>
            </Button>
          </PlatformCard>
        </ul>

        <ul
          className="mt-8 mb-20 grid gap-3 sm:mt-10 sm:mb-24 sm:gap-4 md:grid-cols-3"
          aria-label={t("download.factsAria")}
        >
          <Fact
            icon={RefreshCw}
            title={t("download.updatesTitle")}
            body={t("download.updatesBody")}
          />
          <Fact icon={User} title={t("download.accountTitle")} body={t("download.accountBody")} />
          {passkeyLoginEnabled ? (
            <Fact
              icon={KeyRound}
              title={t("download.passkeysTitle")}
              body={t("download.passkeysBody")}
            />
          ) : null}
        </ul>
      </div>
    </SiteShell>
  );
};
