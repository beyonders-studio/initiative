import type { PluginListenerHandle } from "@capacitor/core";
import { Capacitor } from "@capacitor/core";
import { type PermissionStatus, PushNotifications } from "@capacitor/push-notifications";
import { useRouter } from "@tanstack/react-router";
import { useEffect, useState } from "react";

import { useAuth } from "@/hooks/useAuth";
import { useNotificationStreamConnected } from "@/hooks/useNotificationStream";
import { useNotifications } from "@/hooks/useNotifications";
import { useServer } from "@/hooks/useServer";
import { syncFirebaseProject } from "@/lib/firebaseProject";
import { type ApnsEnvironment, registerDeviceForPush } from "@/lib/pushRegistration";
import { returnPath } from "@/lib/returnPath";
import FirebaseRuntime from "@/plugins/firebaseRuntime";

export type PermissionState = PermissionStatus["receive"];

interface UsePushNotificationsReturn {
  permissionStatus: PermissionState;
  requestPermission: () => Promise<void>;
  isSupported: boolean;
}

export const usePushNotifications = (): UsePushNotificationsReturn => {
  const { user } = useAuth();
  const { isNativePlatform, serverUrl } = useServer();
  // Push reaches the phone apps; the desktop app has none.
  const pushPlatform = isNativePlatform && Capacitor.getPlatform() !== "electron";
  const router = useRouter();
  const [permissionStatus, setPermissionStatus] = useState<PermissionState>("prompt");
  const [fcmEnabled, setFcmEnabled] = useState<boolean>(false);

  useEffect(() => {
    if (!pushPlatform || !user) {
      return;
    }

    let registrationListener: PluginListenerHandle;
    let registrationErrorListener: PluginListenerHandle;
    let pushReceivedListener: PluginListenerHandle;
    let pushActionListener: PluginListenerHandle;
    let apnsEnvironment: ApnsEnvironment | undefined;

    const setupListeners = async () => {
      try {
        // Initialize Firebase with runtime configuration from backend
        if (!serverUrl) {
          console.log("No server URL configured, skipping push notification setup");
          return;
        }

        try {
          await syncFirebaseProject(serverUrl);
          const initResult = await FirebaseRuntime.initialize({ serverUrl });

          if (!initResult.success) {
            console.log(
              "Firebase initialization skipped:",
              initResult.message || "FCM not configured on backend"
            );
            setFcmEnabled(false);
            return;
          }

          console.log("Firebase initialized successfully for push notifications");
          apnsEnvironment = initResult.apnsEnvironment;
          setFcmEnabled(true);
        } catch (err) {
          console.error("Failed to initialize Firebase:", err);
          setFcmEnabled(false);
          return;
        }

        // Check current permission status
        const permissions = await PushNotifications.checkPermissions();
        setPermissionStatus(permissions.receive);

        // Register listeners
        registrationListener = await PushNotifications.addListener(
          "registration",
          async (token) => {
            const platform = Capacitor.getPlatform();
            if (platform !== "ios" && platform !== "android") return;
            // The server is told the token itself, or the push relay's handle
            // for it where the server sends this platform's pushes through
            // the relay.
            try {
              await registerDeviceForPush({
                serverUrl,
                token: token.value,
                platform,
                apnsEnvironment,
              });
            } catch (err) {
              console.error("Failed to register push token with backend:", err);
            }
          }
        );

        registrationErrorListener = await PushNotifications.addListener(
          "registrationError",
          (error) => {
            console.error("Push registration error:", error);
          }
        );

        pushReceivedListener = await PushNotifications.addListener(
          "pushNotificationReceived",
          () => {
            // The system displays a notification that arrives in the foreground.
          }
        );

        pushActionListener = await PushNotifications.addListener(
          "pushNotificationActionPerformed",
          (notification) => {
            // Handle notification tap (navigate to target)
            const data = notification.notification.data;
            // A path in this app, or nowhere.
            const targetPath = returnPath(data.target_path as string | undefined);
            if (targetPath) {
              const communityId = data.community_id as string | undefined;
              if (communityId) {
                router.navigate({
                  to: "/navigate",
                  search: { community_id: communityId, target: targetPath },
                });
              } else {
                // Cross-community notifications (e.g. the overdue digest) name an
                // app-level route with no community to switch into.
                router.navigate({ to: targetPath });
              }
            }
          }
        );

        // Register if already granted
        if (permissions.receive === "granted") {
          try {
            await PushNotifications.register();
          } catch (err) {
            console.error("Failed to register for push notifications:", err);
            // Don't crash the app if registration fails (e.g., in emulator or if FCM not configured)
          }
        }
      } catch (err) {
        console.error("Failed to setup push notifications:", err);
        // Don't crash the app if setup fails
      }
    };

    void setupListeners().catch((err) => {
      console.error("Failed to setup push notification listeners:", err);
      // Don't crash the app if setup fails
    });

    return () => {
      // Cleanup listeners
      void registrationListener?.remove();
      void registrationErrorListener?.remove();
      void pushReceivedListener?.remove();
      void pushActionListener?.remove();
    };
  }, [user, pushPlatform, serverUrl, router]);

  const requestPermission = async () => {
    if (!pushPlatform) {
      console.warn("Push notifications not supported on this platform");
      return;
    }

    if (!serverUrl) {
      console.warn("No server URL configured, cannot enable push notifications");
      return;
    }

    // Initialize Firebase if not already done
    if (!fcmEnabled) {
      try {
        await syncFirebaseProject(serverUrl);
        const initResult = await FirebaseRuntime.initialize({ serverUrl });

        if (!initResult.success) {
          console.warn(
            "Firebase initialization failed:",
            initResult.message || "FCM not configured on backend"
          );
          return;
        }

        setFcmEnabled(true);
        console.log("Firebase initialized successfully");
      } catch (err) {
        console.error("Failed to initialize Firebase:", err);
        return;
      }
    }

    try {
      const result = await PushNotifications.requestPermissions();
      setPermissionStatus(result.receive);

      if (result.receive === "granted") {
        try {
          await PushNotifications.register();
        } catch (err) {
          console.error("Failed to register for push notifications:", err);
          // Don't crash the app if registration fails (e.g., in emulator or if FCM not configured)
        }
      }
    } catch (err) {
      console.error("Failed to request push notification permissions:", err);
      // Don't crash the app if permission request fails
    }
  };

  return {
    permissionStatus,
    requestPermission,
    isSupported: pushPlatform && fcmEnabled,
  };
};

/**
 * Empties the phone's notification tray once the bell has nothing unread,
 * which takes the number off the app icon too: an iPhone shows the count the
 * last push carried until the tray is cleared, and an Android launcher counts
 * what is in the tray.
 */
export const usePushTray = () => {
  const phone = ["ios", "android"].includes(Capacitor.getPlatform());
  const streamConnected = useNotificationStreamConnected();
  const { data, dataUpdatedAt } = useNotifications({
    enabled: phone,
    refetchInterval: streamConnected ? false : 30_000,
  });
  const unread = data?.unread_count;

  // Every fetch that says zero, not only the change to it: a count read on
  // another device leaves the cache at zero while the tray filled.
  useEffect(() => {
    if (phone && dataUpdatedAt && unread === 0) {
      void PushNotifications.removeAllDeliveredNotifications().catch(() => {});
    }
  }, [phone, dataUpdatedAt, unread]);

  // Signing out takes the count with it.
  useEffect(() => {
    if (!phone) {
      return;
    }
    return () => {
      void PushNotifications.removeAllDeliveredNotifications().catch(() => {});
    };
  }, [phone]);
};
