import { Capacitor } from "@capacitor/core";
import { Download } from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { desktopCanUpdate, setAutoUpdateConsent } from "@/lib/desktopUpdates";
import { androidApkUrl, desktopInstallerUrl, PLAY_STORE_URL, RELEASES_URL } from "@/lib/links";
import { detectDesktopOs } from "@/lib/platform";
import AppEnvironment, { PLAY_STORE_INSTALLER } from "@/plugins/appEnvironment";
import DesktopUpdater from "@/plugins/desktopUpdater";
import { Button } from "@/ui/button";
import { Checkbox } from "@/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/ui/dialog";
import { Label } from "@/ui/label";

interface NativeUpdateRequiredDialogProps {
  open: boolean;
  /** The server version that requires a newer native app than the one installed. */
  version: string;
  /** The app version it needs, which names the release holding the download. */
  minNativeVersion?: string;
  onClose: () => void;
}

/** The new app for this device, from the release the bundle's floor names. */
/** Where this device gets a newer app: a download link, or (iOS) the App Store alone. */
const describeKey = (platform: string, fromPlay: boolean) =>
  platform === "electron"
    ? "version.nativeUpdateRequiredDescriptionDesktop"
    : platform === "ios"
      ? "version.nativeUpdateRequiredDescriptionIos"
      : fromPlay
        ? "version.nativeUpdateRequiredDescriptionPlay"
        : "version.nativeUpdateRequiredDescription";

const downloadUrl = (minNativeVersion: string | undefined, fromPlay: boolean): string => {
  if (fromPlay) return PLAY_STORE_URL;
  if (!minNativeVersion) return RELEASES_URL;
  if (Capacitor.getPlatform() !== "electron") return androidApkUrl(minNativeVersion);
  const os = detectDesktopOs();
  return os ? desktopInstallerUrl(minNativeVersion, os) : RELEASES_URL;
};

/**
 * Shown on native when the server's web bundle requires a newer native shell (APK/IPA, or the
 * desktop app) than the one installed — an OTA update can't add native code, so the user must update the app
 * itself. See {@link useNativeUpdate}.
 */
export const NativeUpdateRequiredDialog = ({
  open,
  version,
  minNativeVersion,
  onClose,
}: NativeUpdateRequiredDialogProps) => {
  const { t } = useTranslation("communities");
  const platform = Capacitor.getPlatform();
  // An iPhone app updates through the App Store and nowhere else, so it offers no download.
  const offersDownload = platform !== "ios";
  // A desktop app that can replace itself offers to, and to keep doing so.
  const [canUpdate, setCanUpdate] = useState(false);
  const [always, setAlways] = useState(true);
  const [updating, setUpdating] = useState(false);
  const [failed, setFailed] = useState(false);
  // A Play install updates from Play; an APK, or an app too old to say, takes the next APK.
  // Unknown (null) until an Android app has said, and nothing is offered until then.
  const [fromPlay, setFromPlay] = useState<boolean | null>(platform === "android" ? null : false);

  // Each prompt starts afresh: a failure belongs to the release it was for.
  useEffect(() => {
    if (!open) return;
    setFailed(false);
    setUpdating(false);
    if (minNativeVersion) void desktopCanUpdate().then(setCanUpdate);
    if (platform === "android") {
      setFromPlay(null);
      void AppEnvironment.get()
        .then(({ installer }) => setFromPlay(installer === PLAY_STORE_INSTALLER))
        .catch(() => setFromPlay(false));
    }
  }, [open, minNativeVersion, platform]);

  const updateNow = async () => {
    if (!minNativeVersion) return;
    setAutoUpdateConsent(always);
    setUpdating(true);
    setFailed(false);
    try {
      await DesktopUpdater.download({ version: minNativeVersion });
      await DesktopUpdater.install();
    } catch {
      setFailed(true);
      setUpdating(false);
    }
  };

  const download = (
    <Button asChild>
      <a
        href={downloadUrl(minNativeVersion, fromPlay === true)}
        target="_blank"
        rel="noopener noreferrer"
      >
        <Download className="h-4 w-4" aria-hidden="true" />
        {t("version.nativeUpdateDownload")}
      </a>
    </Button>
  );

  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{t("version.nativeUpdateRequiredTitle")}</DialogTitle>
          <DialogDescription>
            {t(describeKey(platform, fromPlay === true), { version })}
          </DialogDescription>
        </DialogHeader>
        {canUpdate ? (
          <div className="flex items-center gap-2">
            <Checkbox
              id="always-update"
              checked={always}
              onCheckedChange={(next) => setAlways(next === true)}
              disabled={updating}
            />
            <Label htmlFor="always-update" className="font-normal">
              {t("version.alwaysUpdate")}
            </Label>
          </div>
        ) : null}
        {failed ? <p className="text-destructive text-sm">{t("version.updateFailed")}</p> : null}
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={updating}>
            {canUpdate ? t("version.notNow") : t("version.nativeUpdateRequiredAcknowledge")}
          </Button>
          {canUpdate && !failed ? (
            <Button onClick={() => void updateNow()} disabled={updating}>
              {updating ? t("version.updating") : t("version.updateNow")}
            </Button>
          ) : offersDownload && fromPlay !== null ? (
            download
          ) : null}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};
