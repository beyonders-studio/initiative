import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { toast } from "@/lib/mascotToast";

const TOAST_ID = "app-update-ready";

interface UpdateReadyToastProps {
  open: boolean;
  version: string;
  /** The reader closed the toast without reloading. */
  onClose: () => void;
  /**
   * Override the reload action. Defaults to a plain page reload (web); the
   * native OTA flow swaps in the downloaded Capacitor bundle first, and
   * resolves only if that did not reload, so the toast comes back.
   */
  onReload?: () => void | Promise<void>;
}

/**
 * "A newer version is ready" — a toast that stays until answered.
 *
 * It asks for nothing more than a reload: the old version keeps working, so
 * it covers nothing. What changed is shown once the new version is running
 * (``UpdatedNotice``), when every item in it is something the reader can use.
 */
export const UpdateReadyToast = ({ open, version, onClose, onReload }: UpdateReadyToastProps) => {
  const { t } = useTranslation("common");
  // Bumped when a reload did not happen, so a still-open prompt shows again.
  const [attempt, setAttempt] = useState(0);
  // Set when the toast closes for a reason other than the reader closing it.
  const closingRef = useRef(false);
  const handlers = useRef({ onClose, onReload });
  handlers.current = { onClose, onReload };

  useEffect(() => {
    if (!open || !version) {
      return;
    }
    closingRef.current = false;
    toast.info(t("appUpdate.ready", { version }), {
      id: TOAST_ID,
      duration: Number.POSITIVE_INFINITY,
      action: {
        label: t("appUpdate.reload"),
        onClick: () => {
          closingRef.current = true;
          const reload = handlers.current.onReload;
          if (!reload) {
            window.location.reload();
            return;
          }
          void Promise.resolve(reload()).finally(() => setAttempt((n) => n + 1));
        },
      },
      onClose: () => {
        if (!closingRef.current) {
          handlers.current.onClose();
        }
      },
    });
    return () => {
      closingRef.current = true;
      toast.dismiss(TOAST_ID);
    };
    // attempt re-shows the prompt after a reload that did not happen.
  }, [open, version, t, attempt]);

  return null;
};
