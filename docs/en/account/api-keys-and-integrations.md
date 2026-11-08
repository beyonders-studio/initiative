---
icon: lucide/key-round
---

# API keys & integrations

Most people never need this page, and that's a fine way to live. It's for connecting Initiative to a script, another tool or an AI assistant. An **API key** lets software act as you, within the limits you give it.

!!! tip "Treat an API key like a password"
    Anybody holding your key can do what it allows, as you. Keep it out of shared chats and public code, and delete the ones you've stopped using rather than leaving them lying around being technically valid.

## Make an API key

1. Open **My Settings › Security**.
2. Under **API keys**, select **New API key**.
3. Type a **Key name** you'll recognize later, like `weekly-report-script`.
4. Under **Community access**, pick the one community the key needs, or leave **All my communities**.
5. Set an **Expiration (optional)** for anything temporary.
6. Tick **Read-only** unless the key has to change things.
7. Select **Generate API key**.
8. Select **Copy**, then **Done**.

The key is shown once, at step 8. Lost it already? No drama: delete it and make another. A read-only key limited to one community is the safest kind there is: it can't change anything, and it can't see any other group's data.

A community missing from **Community access** doesn't accept your personal keys. Its superadmin can switch [API access](../security/community-security.md#api-access) off for a member, where the community has its own security standard.

![The Generate an API key dialog, with Key name, Community access, Expiration and Read-only](../images/account/api-key.png)

## Check your keys

**My Settings › Security › API keys** lists each key with the first characters of its secret (never the whole thing), when it was made, when it was last used and when it expires. Labels say what it can reach:

| Label | Meaning |
|---|---|
| **Full access** | Reads and writes in every community you're in |
| **Read-only** | Reads only |
| **Community:** and a name | Only that community |
| **Subscription link** | A calendar feed link (below) |
| **Expired** | Past its expiration date |
| **Disabled** | Switched off for good (below) |

**Last used** updates at most once an hour, so a key used a minute ago may say an earlier time.

## Delete a key

1. In **My Settings › Security**, select **Delete** beside the key.
2. Select **Delete** to confirm.

Anything that uses the key stops working straight away. Keys can only be made and deleted from a signed-in browser or app, never with another API key.

## Why a key says Disabled

A key is switched off, and stays on your list marked **Disabled**, when:

- you change, reset or remove your password, or set one with a recovery code;
- you select **Sign out everywhere** after a [This wasn't me](sign-in-and-security.md#this-wasnt-me) email;
- a member of the platform's staff revokes your keys.

A disabled key never comes back on, so make a new one. **Sign out everywhere else** and turning off two-factor authentication leave keys alone.

Some situations stop a key working without disabling it, and it works again when they end:

- your account is suspended or deactivated;
- your server requires a second factor and you haven't [set one up](two-factor-authentication.md), because a key can't type a code;
- a community has switched off your API access, or asks for a second factor or its own sign-in provider each session, which a key can't answer.

## Calendar subscription links

When you [subscribe to a calendar](../guides/calendar.md#subscribe-from-another-calendar-app) from another calendar app, Initiative makes a read-only key that only works for that one calendar's feed, labeled **Subscription link**. To replace the link, select **Get a new link** beside it; the old link stops working. **Delete** removes it, and leaving the community removes it too.

## Connect an AI assistant

Initiative can talk to AI assistants through the **Model Context Protocol** (MCP), so an assistant can do things like "list my projects" or "add a task to the Auth project". It uses one of your API keys, and the same access rules as everything else apply: an assistant reaches only what you could reach.

- It's off unless whoever runs your server turns it on.
- With a **Read-only** key, the assistant can read but every change it tries is refused.
- With a full-access key, it can create and edit things, move a task between statuses, tick off checklist items and link two things together. It can't delete or archive anything, change who something is shared with, or run Initiative's AI features.

A read-only key limited to one community is the right call for most assistants. Reach for a full-access key only when you want the assistant making changes, and keep your assistant asking before each one.

??? techspec "MCP: connecting a client"
    **Enabling.** The server mounts MCP only when `ENABLE_MCP=true` (default `false`). The endpoint is `<APP_URL>/api/v1/mcp/` (`/api/v1/mcp` works too, without a redirect), over streamable HTTP. With MCP off, the path answers like any other unknown API path.

    **Authentication.** `Authorization: Bearer <ppk_ key>` on every request. There is no OAuth flow. Each tool call is an in-process request to the real API route with your header forwarded, so the route's own authentication and row-level security apply, and nothing is privileged. A tool call without a key gets `401`.

    With Claude Code, for example:

    ```bash
    claude mcp add --transport http initiative \
      https://initiative.example.com/api/v1/mcp/ \
      --header "Authorization: Bearer ppk_your_key_here"
    ```

    **Tools: read (55).**

    | Area | Tools |
    |---|---|
    | Communities | `list_communities` |
    | Initiatives | `list_initiatives`, `list_initiative_directory`, `get_initiative`, `get_initiative_defaults`, `list_initiative_roles`, `get_initiative_members`, `search_initiative_members`, `list_initiative_task_statuses` |
    | Search and counts | `search_community`, `get_tool_counts`, `get_tool_counts_by_initiative` |
    | Projects and tasks | `list_projects`, `read_project`, `list_task_statuses`, `list_task_types`, `list_task_type_gallery`, `list_column_limits`, `list_tasks`, `list_task_groups`, `list_my_tasks`, `read_task`, `read_task_case` |
    | Comments | `list_comments`, `read_comment` |
    | Files | `list_files`, `read_file`, `list_file_versions` |
    | Collections | `list_collections`, `read_collection`, `list_collection_files`, `list_collection_shapes`, `get_collection_file_metadata`, `get_collection_files_timeline` |
    | Counters | `list_counter_groups`, `read_counter_group`, `read_counter` |
    | Calendars | `list_calendars`, `read_calendar`, `read_calendar_event`, `list_calendar_entries`, `list_my_calendar_entries` |
    | Dashboards | `list_dashboards`, `read_dashboard`, `load_dashboard_data` |
    | Posts | `list_posts`, `read_post`, `get_post_timeline` |
    | Wikis | `list_wikis`, `read_wiki`, `list_wiki_pages`, `read_wiki_page` |
    | Contacts | `list_contacts`, `read_contact` |
    | Links | `list_relationships` |

    **Tools: write (31).**

    | Area | Tools |
    |---|---|
    | Projects and tasks | `create_project`, `update_project`, `create_task`, `update_task`, `move_task`, `toggle_checklist_item` |
    | Comments | `create_comment`, `update_comment` |
    | Files | `create_file`, `update_file` |
    | Counters | `create_counter_group`, `update_counter_group`, `add_counter`, `update_counter`, `set_counter_count`, `step_counter` |
    | Calendars | `create_calendar`, `update_calendar`, `create_calendar_event`, `update_calendar_event` |
    | Dashboards | `create_dashboard`, `update_dashboard` |
    | Posts | `create_post`, `update_post` |
    | Wikis | `create_wiki`, `update_wiki`, `create_wiki_page`, `update_wiki_page` |
    | Contacts | `create_contact`, `update_contact` |
    | Links | `create_relationship` |

    Every tool is listed whatever the key. A read-only key's write calls are refused with `403 USER_API_KEY_READ_ONLY`. Tools carry no `readOnlyHint` or `destructiveHint` annotations, so confirming writes is the client's job. Deleting, archiving, restoring, reordering, bulk edits, duplicating, sharing and grants, tags and properties, collection writes, imports, downloads, exports and AI generation are not exposed.

    Lists page at 20 items by default, 50 at most. `list_my_tasks` with no `conditions` returns open tasks only.

## Get told when something changes (webhooks)

A webhook tells another service when something changes in a community: a task moved, an event was added, a file went in the trash. You give Initiative an address, it sends a short note there after each change, and your service reads the details back with an API key.

Webhooks are set up through the API, with a key that isn't **Read-only**; a read-only key can list them.

- **They belong to the community**, not to whoever made them, and keep running after that person leaves.
- **Anyone in an initiative** can set one up for that initiative, and change or remove it. A webhook covering the whole community is for its admins, or a custom role given the **Webhooks** job.
- **The note says what changed, never what it now says**: which item, and which fields. Your service reads the item back through the API, where it sees exactly what its key may see.
- **A delivery your service doesn't accept is tried again** for a little under two hours, and later changes wait behind it so everything arrives in order. After the last try it's set aside and counted in `dead_letter_count`. Anything above zero means the receiving end wants a look.

??? techspec "Webhooks: subscriptions, events and deliveries"
    **Endpoints**, under `/api/v1/c/{community_id}/webhooks/subscriptions`:

    | Request | Body | Answer |
    |---|---|---|
    | `POST /` | `target_url` (required), `event_types` (required, at least one), `fields` (optional, at least one if given), `initiative_id` (optional) | `201` with the subscription and `hmac_secret` |
    | `GET /` | | Every subscription you can reach |
    | `PATCH /{id}` | Any of `target_url`, `event_types`, `fields`, `active` | The subscription |
    | `DELETE /{id}` | | `204` |

    A subscription reads back as `id`, `community_ref`, `initiative_id`, `created_by_ref`, `target_url`, `event_types`, `fields`, `active`, `dead_letter_count`, `created_at` and `updated_at`. `hmac_secret` (64 characters) is returned once, on create. Lost it? Delete the subscription and make a new one.

    `initiative_id` narrows a subscription to one initiative; any member of that initiative, or a community admin, can create, change and remove it, whoever made it. Left out, the subscription covers the community, and only holders of the **Webhooks** admin job see or change it. `PATCH` with `"active": false` pauses deliveries without deleting; `true` resumes them. There is no limit on how many a community holds, and no webhook screen in the app.

    **Target URL.** `https` only, a host name, no `user:password@`, at most 2048 characters. Every address the host resolves to must be public and routable. It's checked on create, on `PATCH`, and again before every delivery, and the connection goes to the address that passed.

    **Event types** are `<resource>.created`, `<resource>.updated` and `<resource>.deleted`, for these resources: `calendar_events`, `calendars`, `collections`, `comments`, `contacts`, `counter_groups`, `counters`, `dashboards`, `files`, `initiatives`, `plugins`, `posts`, `projects`, `tags`, `tasks`, `wiki_pages`, `wikis`. Moving something to the trash sends `deleted`, and restoring it sends `created`. Posts send nothing until published, and wiki pages nothing while they're drafts. Changes to parts of a resource arrive as an `updated` on it: task statuses and types as `projects` with `statuses` or `types`, initiative roles and members as `initiatives` with `roles` or `members`, poll votes as `posts` with `poll`.

    A plug-in installed in the community can declare events of its own, named `plugin.<plug-in public id>.<event>`.

    **`fields`** narrows `updated` events to changes in those names; `created` and `deleted` always arrive. A name must belong to one of the subscription's resources:

    ??? techspec "Field names by resource"
        | Resource | Fields |
        |---|---|
        | `calendar_events` | `all_day`, `answers`, `attachments`, `attendees`, `calendar_id`, `created_by`, `deleted_at`, `deleted_by`, `dependencies`, `description`, `end_at`, `held_at`, `hold_id`, `id`, `location`, `original_start`, `overridden_fields`, `parts`, `plugin_values`, `properties`, `purge_at`, `recurrence`, `recurrence_shift`, `recurrence_until`, `references`, `relationships`, `rsvp_open`, `series_id`, `start_at`, `tags`, `title` |
        | `calendars` | `archived_at`, `attachments`, `color`, `comments_enabled`, `comments_locked_at`, `created_by`, `deleted_at`, `deleted_by`, `dependencies`, `description`, `held_at`, `hold_id`, `id`, `initiative_id`, `listing_uid`, `listing_version`, `name`, `parts`, `plugin_values`, `properties`, `purge_at`, `references`, `relationships`, `sharing`, `tags` |
        | `collections` | `archived_at`, `attachments`, `comments_enabled`, `comments_locked_at`, `cover_file_id`, `created_by`, `deleted_at`, `deleted_by`, `dependencies`, `description`, `files`, `held_at`, `hold_id`, `id`, `initiative_id`, `layouts`, `name`, `parts`, `plugin_values`, `properties`, `purge_at`, `references`, `relationships`, `tags` |
        | `comments` | `audience`, `calendar_id`, `collection_id`, `contact_id`, `content`, `counter_group_id`, `created_by`, `dashboard_id`, `deleted_at`, `deleted_by`, `file_id`, `held_at`, `hold_id`, `id`, `imported_author_name`, `parent_comment_id`, `post_id`, `project_id`, `purge_at`, `reactions`, `removal_id`, `removed_at`, `removed_reason`, `system_kind`, `task_id`, `wiki_id`, `wiki_page_id` |
        | `contacts` | `addresses`, `archived_at`, `attachments`, `comments_enabled`, `comments_locked_at`, `created_by`, `deleted_at`, `deleted_by`, `dependencies`, `emails`, `held_at`, `hold_id`, `id`, `initiative_id`, `is_organization`, `listing_uid`, `listing_version`, `name`, `parts`, `phones`, `plugin_values`, `properties`, `purge_at`, `references`, `relationships`, `sharing`, `tags`, `websites` |
        | `counter_groups` | `archived_at`, `attachments`, `comments_enabled`, `comments_locked_at`, `created_by`, `deleted_at`, `deleted_by`, `dependencies`, `description`, `held_at`, `hold_id`, `id`, `initiative_id`, `layouts`, `listing_uid`, `listing_version`, `name`, `parts`, `plugin_values`, `properties`, `purge_at`, `references`, `relationships`, `sharing`, `tags` |
        | `counters` | `attachments`, `color`, `count`, `counter_group_id`, `created_by`, `deleted_at`, `deleted_by`, `dependencies`, `held_at`, `hold_id`, `id`, `initial_count`, `max`, `min`, `name`, `parts`, `plugin_values`, `position`, `properties`, `purge_at`, `references`, `relationships`, `step`, `tags`, `view_mode` |
        | `dashboards` | `archived_at`, `attachments`, `comments_enabled`, `comments_locked_at`, `config`, `created_by`, `definition`, `deleted_at`, `deleted_by`, `dependencies`, `description`, `held_at`, `hold_id`, `id`, `initiative_id`, `listing_uid`, `listing_version`, `name`, `parts`, `plugin_values`, `properties`, `purge_at`, `references`, `relationships`, `sharing`, `tags`, `view_mode` |
        | `files` | `added_to_collection`, `archived_at`, `attachments`, `comments_enabled`, `comments_locked_at`, `content`, `created_by`, `current_version_id`, `deleted_at`, `deleted_by`, `dependencies`, `featured_image_url`, `file_type`, `held_at`, `hold_id`, `id`, `initiative_id`, `is_template`, `listing_uid`, `listing_version`, `name`, `parts`, `plugin_values`, `properties`, `purge_at`, `references`, `relationships`, `removed_from_collection`, `sharing`, `tags`, `versions`, `yjs_state`, `yjs_updated_at` |
        | `initiatives` | `archived_at`, `auto_join`, `calendars_enabled`, `color`, `contacts_enabled`, `counter_groups_enabled`, `created_by`, `dashboards_enabled`, `deleted_at`, `deleted_by`, `description`, `files_enabled`, `id`, `join_policy`, `keep_content_in`, `layouts`, `members`, `name`, `posts_enabled`, `projects_enabled`, `properties`, `purge_at`, `roles`, `wikis_enabled` |
        | `plugins` | `auto_update`, `config`, `config_state`, `config_state_detail`, `connection_refs`, `created_by`, `declined_version`, `definition`, `enabled`, `granted_scopes`, `id`, `listing_uid`, `listing_version`, `name`, `pending_version`, `plugin_kind`, `secret_fields`, `setting_aliases`, `settings` |
        | `posts` | `archived_at`, `attachments`, `body`, `comments_enabled`, `comments_locked_at`, `created_by`, `deleted_at`, `deleted_by`, `dependencies`, `held_at`, `hold_id`, `id`, `initiative_id`, `listing_uid`, `listing_version`, `name`, `parts`, `pin_expires_at`, `pinned_at`, `pinned_by`, `plugin_values`, `poll`, `properties`, `published_at`, `purge_at`, `reactions`, `reactions_enabled`, `reads`, `references`, `relationships`, `scheduled_for`, `sharing`, `tags` |
        | `projects` | `archived_at`, `attachments`, `comments_enabled`, `comments_locked_at`, `created_by`, `deleted_at`, `deleted_by`, `dependencies`, `description`, `end_date`, `held_at`, `hold_id`, `icon`, `id`, `initiative_id`, `is_template`, `layouts`, `listing_uid`, `listing_version`, `name`, `parts`, `pinned_at`, `plugin_values`, `properties`, `purge_at`, `references`, `relationships`, `sharing`, `start_date`, `statuses`, `tags`, `types` |
        | `tags` | `attachments`, `color`, `created_by`, `deleted_at`, `deleted_by`, `dependencies`, `held_at`, `hold_id`, `id`, `name`, `parts`, `purge_at`, `references`, `relationships`, `tags` |
        | `tasks` | `archived_at`, `assignees`, `attachments`, `checklist`, `comments_locked_at`, `completed_at`, `created_by`, `deleted_at`, `deleted_by`, `dependencies`, `description`, `due_date`, `held_at`, `hold_id`, `id`, `parts`, `plugin_values`, `position`, `priority`, `project_id`, `properties`, `purge_at`, `recurrence`, `recurrence_anchor`, `recurrence_anchor_count`, `recurrence_carry`, `recurrence_limit`, `recurrence_occurrence_count`, `recurrence_shift`, `recurrence_strategy`, `recurrence_until`, `references`, `relationships`, `series_id`, `start_date`, `tags`, `task_status_id`, `task_type_id`, `title` |
        | `wiki_pages` | `attachments`, `comments_locked_at`, `content`, `created_by`, `deleted_at`, `deleted_by`, `dependencies`, `held_at`, `hold_id`, `id`, `is_draft`, `parent_page_id`, `parts`, `plugin_values`, `position`, `properties`, `purge_at`, `references`, `relationships`, `slug`, `tags`, `title`, `wiki_id`, `yjs_state`, `yjs_updated_at` |
        | `wikis` | `accent_color`, `archived_at`, `attachments`, `comments_enabled`, `comments_locked_at`, `contents_depth`, `created_by`, `deleted_at`, `deleted_by`, `dependencies`, `description`, `file_positions`, `held_at`, `hold_id`, `home_page_id`, `id`, `initiative_id`, `listing_uid`, `listing_version`, `name`, `page_order`, `parts`, `plugin_values`, `properties`, `purge_at`, `reading_width`, `references`, `relationships`, `sharing`, `show_connections`, `show_updated_at`, `tags`, `template_page_id` |

    **Errors.**

    | Code | Status | When |
    |---|---|---|
    | `WEBHOOK_INVALID_TARGET_URL` | `400` | Not an `https` URL with a host, carries a user name or password, or the host doesn't resolve |
    | `WEBHOOK_PRIVATE_TARGET_URL` | `400` | The host resolves to an address that isn't public |
    | `WEBHOOK_UNKNOWN_EVENT_TYPE` | `400` | An event type that doesn't exist |
    | `WEBHOOK_UNKNOWN_FIELD` | `400` | A field none of the chosen resources has |
    | `WEBHOOK_SUBSCRIPTION_NOT_FOUND` | `404` | No subscription by that id that you can reach |
    | `USER_API_KEY_READ_ONLY` | `403` | A write with a read-only key |

    A malformed body (an empty `event_types`, say) gets `422`.

    **A delivery** is a `POST` of one JSON envelope for each transaction that touched the subscription:

    ```json
    {
      "event_id": "5f0c3c1e-8a7b-5f43-9a0e-2a8f6d1b9c41",
      "subscription_id": 4,
      "community_ref": "…",
      "actor_ref": "…",
      "actor_plugin": null,
      "occurred_at": "2026-10-16T09:12:44.120931+00:00",
      "changes": [
        {
          "event_type": "tasks.updated",
          "initiative_id": 2,
          "resource": {"type": "tasks", "id": 381},
          "parents": [{"type": "projects", "id": 17}],
          "action": "updated",
          "changed": ["task_status_id", "tags"]
        }
      ]
    }
    ```

    The body is compact JSON (no spaces). `community_ref` and `actor_ref` are names for the community and the person made for this subscription, not account ids; `actor_ref` is `null` for a change the system made. `actor_plugin` is the public id of the plug-in that made the change, if one did. `parents` runs innermost first, and `changed` is empty for `created` and `deleted`. A plug-in's own event carries `event_type`, `initiative_id`, `plugin` and `payload`.

    **Headers.**

    | Header | Value |
    |---|---|
    | `Content-Type` | `application/json` |
    | `User-Agent` | `initiative-webhooks/1` |
    | `X-Initiative-Event-ID` | The envelope's `event_id`, the same on every retry. Skip one you've already handled. |
    | `X-Initiative-Timestamp` | Unix seconds when this attempt was signed. |
    | `X-Initiative-Signature` | `sha256=` and the lowercase hex HMAC-SHA256 of `<timestamp>.<raw body>`, keyed with `hmac_secret` as UTF-8. |

    Check the signature over the body exactly as received, compare in constant time, and turn away a timestamp more than about 5 minutes old:

    ```python
    import hashlib
    import hmac
    import time

    def verify(secret: str, timestamp: str, signature: str, body: bytes) -> bool:
        if abs(time.time() - int(timestamp)) > 300:
            return False
        mac = hmac.new(secret.encode("utf-8"), digestmod=hashlib.sha256)
        mac.update(timestamp.encode("utf-8") + b"." + body)
        return hmac.compare_digest("sha256=" + mac.hexdigest(), signature)
    ```

    **Delivery rules.** Only a `2xx` answer counts; redirects aren't followed. Each attempt has 3 seconds to connect, 5 to read and 15 end to end, and at most 1 MiB of the answer is read. After a failure the waits are 5 seconds, 30 seconds, 2 minutes, 10 minutes, 30 minutes and 1 hour; the seventh failed attempt sets the batch aside for good, adds it to `dead_letter_count`, and lets the deliveries behind it through. Nothing switches the subscription off or notifies anybody. Per subscription, transactions go out oldest first, up to 50 a pass, and a failing one holds back the rest until it's delivered or set aside. Changes are kept for 7 days, which also bounds what `dead_letter_count` can see.

## Rate limits

API requests share the server's general limit, which is 100 requests a minute by default. A request made with an API key is counted against the address it came from. A few routes have tighter limits of their own; a calendar feed, for one, allows 30 requests a minute.
