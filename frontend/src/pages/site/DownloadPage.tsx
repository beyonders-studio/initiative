/**
 * Getting Initiative onto a device: one big button for the visitor's own
 * device, then every computer and phone below it.
 *
 * Android gets a real file: the APK attached to the release the server's
 * native floor names, which is the newest one that runs this server's web
 * bundle. A computer gets its installer from the release its own floor names.
 * An iPhone adds it to the home screen from Safari.
 */

import type { LucideIcon } from "lucide-react";
import { ArrowUpRight, Download, Monitor, Smartphone } from "lucide-react";
import { type ReactNode, useMemo } from "react";
import { Trans, useTranslation } from "react-i18next";

import { useGetFcmConfig } from "@/api/generated/settings/settings";
import {
  androidApkUrl,
  desktopInstallerUrl,
  docsUrl,
  OBTAINIUM_URL,
  RELEASES_URL,
} from "@/lib/links";
import { type DesktopOs, detectDesktopOs, detectPlatform } from "@/lib/platform";
import { Button } from "@/ui/button";
import { useResolvedTheme } from "@/ui/lib/useResolvedTheme";

import { DarkBand } from "./DarkBand";
import { SiteShell } from "./SiteShell";
import { useFrontDoor } from "./useFrontDoor";
import { usePageMeta } from "./usePageMeta";

const IOS_GUIDE = docsUrl("getting-started/install-the-app/#on-an-iphone-or-ipad");

const DESKTOP_OSES: DesktopOs[] = ["windows", "mac", "linux"];

const DESKTOP_BUTTON = {
  windows: "download.windowsButton",
  mac: "download.macButton",
  linux: "download.linuxButton",
} as const;

/** The hero's button, white on the dark band. */
const HERO_BUTTON = "h-14 bg-white px-7 text-base text-slate-950 hover:bg-slate-100";

type ButtonLook = { className?: string; variant?: "default" | "outline" };

/** The APK from the release the server's native floor names; every release
 *  when the floor is unknown. */
const ApkButton = ({
  minNativeVersion,
  className,
  variant,
  children,
}: ButtonLook & { minNativeVersion: string | null; children: ReactNode }) => (
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

/** One computer's installer, from the release the server's desktop floor
 *  names; every release when the floor is unknown. */
const DesktopButton = ({
  os,
  minDesktopVersion,
  className,
  variant,
  children,
}: ButtonLook & {
  os: DesktopOs | null;
  minDesktopVersion: string | null;
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

const IosButton = ({ className, variant, children }: ButtonLook & { children: ReactNode }) => (
  <Button size="lg" variant={variant} className={className} asChild>
    <a href={IOS_GUIDE} target="_blank" rel="noopener noreferrer">
      {children}
      <ArrowUpRight className="h-4 w-4" aria-hidden="true" />
    </a>
  </Button>
);

/** The app on a computer, with the same screen on a phone in front of it. */
const Screens = () => {
  const { t } = useTranslation("landing");
  const dark = useResolvedTheme() === "dark";
  const src = (name: string) => `/site/${name}${dark ? ".dark" : ""}.webp`;
  return (
    <div className="relative mx-auto mt-12 max-w-5xl pr-[9%] sm:mt-16">
      <div className="overflow-hidden rounded-lg border border-white/15 bg-slate-900 shadow-2xl shadow-black/60 sm:rounded-2xl">
        <img
          src={src("download-computer")}
          alt={t("download.screensAlt")}
          width={2560}
          height={1600}
          className="block h-auto w-full"
        />
      </div>
      <div className="absolute right-0 bottom-[-6%] w-[26%] rounded-[1.1rem] border-4 border-slate-950 bg-slate-950 shadow-2xl shadow-black/70 ring-1 ring-white/20 sm:rounded-[2.2rem] sm:border-8">
        <img
          src={src("download-phone")}
          alt=""
          width={780}
          height={1688}
          className="block h-auto w-full rounded-[0.8rem] sm:rounded-[1.7rem]"
        />
      </div>
    </div>
  );
};

/** One kind of device, with every way to get the app onto it. */
const Device = ({
  id,
  icon: Icon,
  title,
  body,
  children,
}: {
  id: string;
  icon: LucideIcon;
  title: string;
  body: ReactNode;
  children: ReactNode;
}) => (
  <section
    className="flex flex-col rounded-3xl border bg-card p-6 sm:p-9"
    aria-labelledby={`download-${id}`}
  >
    <span className="flex h-12 w-12 items-center justify-center rounded-2xl bg-primary/10 text-primary">
      <Icon className="h-6 w-6" aria-hidden="true" />
    </span>
    <h2 id={`download-${id}`} className="mt-5 font-extrabold text-2xl tracking-tight sm:text-3xl">
      {title}
    </h2>
    <p className="mt-2 text-lg text-muted-foreground">{body}</p>
    <div className="mt-7 flex flex-col gap-5">{children}</div>
  </section>
);

export const DownloadPage = () => {
  const { t } = useTranslation("landing");
  const { config } = useFrontDoor();
  usePageMeta(t("meta.downloadTitle"), t("meta.downloadDescription"));
  // The Android app only gets push where this server has it switched on.
  const fcm = useGetFcmConfig(undefined, { query: { staleTime: 300_000 } });
  const push = fcm.data?.enabled === true;
  const minNativeVersion = config?.min_native_version ?? null;
  const minDesktopVersion = config?.min_desktop_version ?? null;
  const platform = useMemo(() => detectPlatform(), []);
  // A phone's browser also says Linux; only a computer is offered a file.
  const desktopOs = useMemo(() => (platform === "desktop" ? detectDesktopOs() : null), [platform]);

  return (
    <SiteShell current="download">
      <DarkBand stars aria-labelledby="landing-download-title">
        <div className="relative mx-auto max-w-6xl px-4 pt-12 pb-16 sm:px-8 sm:pt-20 sm:pb-24">
          <div className="mx-auto max-w-3xl text-center">
            <h1
              id="landing-download-title"
              className="font-extrabold text-[2.6rem] leading-tight tracking-tight sm:text-6xl"
            >
              {t("download.title")}{" "}
              <span className="text-amber-400">{t("download.titleHighlight")}</span>
            </h1>
            <p className="mt-4 text-lg text-slate-300 sm:text-xl">{t("download.description")}</p>
            <div className="mt-8 flex justify-center">
              {platform === "android" ? (
                <ApkButton minNativeVersion={minNativeVersion} className={HERO_BUTTON}>
                  <Download className="h-5 w-5" aria-hidden="true" />
                  {t("download.androidButton")}
                </ApkButton>
              ) : platform === "ios" ? (
                <IosButton className={HERO_BUTTON}>{t("download.iosButton")}</IosButton>
              ) : (
                <DesktopButton
                  os={desktopOs}
                  minDesktopVersion={minDesktopVersion}
                  className={HERO_BUTTON}
                >
                  <Download className="h-5 w-5" aria-hidden="true" />
                  {t(desktopOs ? DESKTOP_BUTTON[desktopOs] : "download.desktopButton")}
                </DesktopButton>
              )}
            </div>
          </div>
          <Screens />
        </div>
      </DarkBand>

      <div className="mx-auto grid max-w-6xl grid-cols-fill-80/2 gap-4 px-4 py-14 sm:gap-6 sm:px-8 sm:py-20">
        <Device
          id="computer"
          icon={Monitor}
          title={t("download.computer.title")}
          body={t("download.computer.body")}
        >
          <div className="flex flex-wrap gap-2.5">
            {minDesktopVersion ? (
              DESKTOP_OSES.map((os) => (
                <DesktopButton
                  key={os}
                  os={os}
                  minDesktopVersion={minDesktopVersion}
                  variant={os === desktopOs ? "default" : "outline"}
                >
                  <Download className="h-4 w-4" aria-hidden="true" />
                  {t(`download.os.${os}`)}
                </DesktopButton>
              ))
            ) : (
              <DesktopButton os={null} minDesktopVersion={null} variant="outline">
                {t("download.releases")}
                <ArrowUpRight className="h-4 w-4" aria-hidden="true" />
              </DesktopButton>
            )}
          </div>
        </Device>

        <Device
          id="phone"
          icon={Smartphone}
          title={t("download.phone.title")}
          body={t(push ? "download.phone.bodyPush" : "download.phone.body")}
        >
          <div className="flex flex-wrap gap-2.5">
            <ApkButton
              minNativeVersion={minNativeVersion}
              variant={platform === "android" ? "default" : "outline"}
            >
              <Download className="h-4 w-4" aria-hidden="true" />
              {t("download.os.android")}
            </ApkButton>
            <IosButton variant={platform === "ios" ? "default" : "outline"}>
              {t("download.os.ios")}
            </IosButton>
          </div>
          <div className="space-y-1 text-muted-foreground text-sm">
            <p>
              <Trans
                t={t}
                i18nKey="download.phone.obtainium"
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
            <p>{t("download.phone.iosHow")}</p>
          </div>
        </Device>
      </div>
    </SiteShell>
  );
};
