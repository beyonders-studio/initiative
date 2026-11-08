package studio.beyonders.initiative;

import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.content.Context;
import android.os.Build;
import android.util.Log;

/**
 * Manages notification channels for different types of push notifications.
 * Android O (API 26) and above require notification channels for all notifications.
 *
 * A channel is what the user sees (and can mute) in the OS notification
 * settings, so related notification types share one rather than getting a row
 * each. The backend picks the channel per notification and sends its id in the
 * FCM payload — see PUSH_CHANNELS in backend/app/services/platform/
 * push_notifications.py, which must stay in sync with the ids created here.
 * A notification naming a channel this app never created lands in Firebase's
 * own fallback channel instead, so a new channel id needs a native release.
 *
 * Channel ids are permanent: renaming one orphans whatever the user configured
 * on the old channel, so change the display name, not the id.
 */
public class NotificationChannelManager {
    private static final String TAG = "NotificationChannels";

    // Channel IDs - must match the backend's PUSH_CHANNELS values exactly
    public static final String CHANNEL_TASK_ASSIGNMENT = "task_assignment";
    // Both digests, Overdue tasks and Coming up. The id is the first digest's,
    // kept so an installed app goes on receiving both.
    public static final String CHANNEL_DIGESTS = "overdue_tasks";
    public static final String CHANNEL_INITIATIVE_ADDED = "initiative_added";
    public static final String CHANNEL_PROJECT_ADDED = "project_added";
    public static final String CHANNEL_USER_PENDING_APPROVAL = "user_pending_approval";
    public static final String CHANNEL_MENTION = "mention";
    public static final String CHANNEL_COMMENTS = "comments";
    public static final String CHANNEL_CALENDAR_EVENTS = "calendar_events";
    public static final String CHANNEL_EVENT_REMINDER = "event_reminder";
    public static final String CHANNEL_ACCESS_GRANTS = "access_grants";
    public static final String CHANNEL_MESSAGES = "messages";
    public static final String CHANNEL_POSTS = "posts";
    public static final String CHANNEL_DEFAULT = "default";

    /**
     * Create all notification channels.
     * Safe to call multiple times - channels are only created once.
     *
     * @param context Application context
     */
    public static void createNotificationChannels(Context context) {
        // Channels only needed on Android O (API 26) and above
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) {
            return;
        }

        NotificationManager notificationManager =
            (NotificationManager) context.getSystemService(Context.NOTIFICATION_SERVICE);

        if (notificationManager == null) {
            Log.e(TAG, "NotificationManager not available");
            return;
        }

        // 1. Task Assignment Channel
        createChannel(
            notificationManager,
            CHANNEL_TASK_ASSIGNMENT,
            "Task Assignments",
            "Notifications when you're assigned to a task",
            NotificationManager.IMPORTANCE_HIGH
        );

        // 2. Digests Channel
        createChannel(
            notificationManager,
            CHANNEL_DIGESTS,
            "Digests",
            "Your scheduled summaries",
            NotificationManager.IMPORTANCE_DEFAULT
        );

        // 3. Initiative Added Channel
        createChannel(
            notificationManager,
            CHANNEL_INITIATIVE_ADDED,
            "Initiative Invites",
            "Notifications when you're added to an initiative",
            NotificationManager.IMPORTANCE_DEFAULT
        );

        // 4. Project Added Channel
        createChannel(
            notificationManager,
            CHANNEL_PROJECT_ADDED,
            "New Projects",
            "Notifications when projects are created in your initiatives",
            NotificationManager.IMPORTANCE_DEFAULT
        );

        // 5. User Pending Approval Channel
        createChannel(
            notificationManager,
            CHANNEL_USER_PENDING_APPROVAL,
            "User Approvals",
            "Notifications when new users request access",
            NotificationManager.IMPORTANCE_DEFAULT
        );

        // 6. Mentions Channel
        createChannel(
            notificationManager,
            CHANNEL_MENTION,
            "Mentions",
            "Notifications when someone mentions you",
            NotificationManager.IMPORTANCE_HIGH
        );

        // 7. Comments Channel
        createChannel(
            notificationManager,
            CHANNEL_COMMENTS,
            "Comments",
            "Notifications when someone comments on or replies to your work",
            NotificationManager.IMPORTANCE_DEFAULT
        );

        // 8. Calendar Events Channel
        createChannel(
            notificationManager,
            CHANNEL_CALENDAR_EVENTS,
            "Calendar Events",
            "Invitations, updates, cancellations, and RSVPs for events",
            NotificationManager.IMPORTANCE_DEFAULT
        );

        // 9. Event Reminders Channel
        createChannel(
            notificationManager,
            CHANNEL_EVENT_REMINDER,
            "Event Reminders",
            "Reminders ahead of events you're attending",
            NotificationManager.IMPORTANCE_HIGH
        );

        // 10. Access Grants Channel
        createChannel(
            notificationManager,
            CHANNEL_ACCESS_GRANTS,
            "Access Requests",
            "Updates on requests for temporary access to a guild",
            NotificationManager.IMPORTANCE_DEFAULT
        );

        // 11. Direct Messages Channel
        createChannel(
            notificationManager,
            CHANNEL_MESSAGES,
            "Direct Messages",
            "Someone sent you a direct message",
            NotificationManager.IMPORTANCE_HIGH
        );

        // 12. Posts Channel
        createChannel(
            notificationManager,
            CHANNEL_POSTS,
            "Posts",
            "Notices posted to a board you can see",
            NotificationManager.IMPORTANCE_DEFAULT
        );

        // 13. Default Channel (fallback)
        createChannel(
            notificationManager,
            CHANNEL_DEFAULT,
            "General Notifications",
            "General app notifications",
            NotificationManager.IMPORTANCE_DEFAULT
        );

        Log.i(TAG, "Notification channels created successfully");
    }

    private static void createChannel(
        NotificationManager notificationManager,
        String id,
        String name,
        String description,
        int importance
    ) {
        NotificationChannel channel = new NotificationChannel(id, name, importance);
        channel.setDescription(description);
        channel.enableVibration(true);
        channel.setShowBadge(true);
        notificationManager.createNotificationChannel(channel);
    }
}
