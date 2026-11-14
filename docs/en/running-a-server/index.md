---
icon: lucide/server-cog
---

# Running a server

These pages are for whoever runs Initiative for their group: the person who installs it, keeps it current, and gets the message when it's down. If you only use Initiative, skip the whole section with a clear conscience. [Using Initiative](../guides/index.md) has everything you need.

You don't need to be a server expert. The usual setup is one Docker Compose file and three values in a text file. Everything past [Installation](installation.md) is here for the day you need it, and nobody is checking whether you've read it.

Rather not run a server at all? See [Self-host or let us host it](../self-host-or-hosted.md).

## The pages

<div class="grid cards" markdown>

-   :material-download-box-outline: __Installation__

    Docker Compose, the database connection, and which image to follow.

    [:octicons-arrow-right-24: Installation](installation.md)

-   :material-package-variant: __Native server packages__

    Run it on Debian or Alpine without Docker.

    [:octicons-arrow-right-24: Native server packages](native-packages.md)

-   :material-tune: __Configuration__

    Every environment variable, and the settings under **Settings → Platform**.

    [:octicons-arrow-right-24: Configuration](configuration.md)

-   :material-account-key-outline: __Single sign-on__

    Connect an OIDC identity provider.

    [:octicons-arrow-right-24: Single sign-on](single-sign-on.md)

-   :material-email-outline: __Email__

    Outgoing mail for sign-in codes, password resets and digests.

    [:octicons-arrow-right-24: Email](email.md)

-   :material-cellphone-message: __Push notifications__

    Notifications on phones and in the desktop app.

    [:octicons-arrow-right-24: Push notifications](push-notifications.md)

-   :material-database-outline: __File & object storage__

    Local disk or an S3-compatible bucket, plus encryption and upload scanning.

    [:octicons-arrow-right-24: Object storage](object-storage.md)

-   :material-puzzle-outline: __Running plug-ins__

    The Initiative registry, and what each plug-in needs from you.

    [:octicons-arrow-right-24: Running plug-ins](plugins.md)

-   :material-package-variant-plus: __Publishing your own listings__

    Add your own projects, home layouts and plug-ins to the marketplace.

    [:octicons-arrow-right-24: Publishing listings](publishing-listings.md)

-   :material-shield-crown-outline: __Platform roles__

    Server-wide roles, capabilities and break-glass access.

    [:octicons-arrow-right-24: Platform roles](platform-roles.md)

-   :material-bullhorn-outline: __Announcements__

    Tell everyone on your server something they have to act on.

    [:octicons-arrow-right-24: Announcements](announcements.md)

-   :material-backup-restore: __Backups & updates__

    Back up, restore, update, and read a start that failed.

    [:octicons-arrow-right-24: Backups & updates](backups-and-updates.md)

-   :material-chart-line: __Logs & monitoring__

    The two log streams, Prometheus metrics and health checks.

    [:octicons-arrow-right-24: Logs & monitoring](configuration.md#logs)

-   :material-book-edit-outline: __Maintaining these docs__

    Build, preview and publish this help center.

    [:octicons-arrow-right-24: Maintaining these docs](maintaining-these-docs.md)

</div>

## The first account is the owner

The first person to register on a new server becomes its **owner**, the one account that can change server-wide settings. Make sure that's you, and not the enthusiastic colleague who wandered past while it was booting. See [Platform roles](platform-roles.md).
