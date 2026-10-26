---
icon: lucide/key-round
---

# API keys & integrations

Most people will never need this page, and that is a completely respectable way to live.

But if you want to connect Initiative to a script, another tool, or an AI assistant, **API keys** are how. A key is a long-lived credential that lets software act on your behalf, within limits you set.

!!! tip "Treat an API key like a password"
    Anybody holding your key can do what it allows, as you. So don't paste one into a public chat, don't email it to yourself, and delete the ones you've stopped using rather than leaving them lying around being technically valid.

## Creating one

1. **My Settings → Security**, and choose **New API key** under **API keys**. The rest happens in a dialog.
2. Give it a clear **name** — `weekly-report-script`, so future-you remembers what it's for.
3. Choose its limits (below).
4. Generate it, and **copy it right now** — it's shown exactly once. Lost it already? No drama at all: delete it and make another.

![Generating an API key](../images/account/api-key.png)

## Choosing limits

Each option narrows what a key can reach. Use the tightest set that still does the job:

| Option | What it does | Recommendation |
|---|---|---|
| **Read-only** | Reads data, never creates, changes, or deletes. | **On**, unless you specifically need writes. |
| **Community access** | Limits the key to a single community instead of all of yours. | Pin it to the **one** it needs. |
| **Expiration** | The key stops working after a date. | Set one for anything temporary. |

A read-only key pinned to a single community is the safest default going: it can't change anything, and it can't see any other group's data.

## Managing keys

**API keys** lists each key's name, a short prefix (never the whole key), its scope, when it was last used, and when it expires. **Delete** asks first, then revokes it. Resetting your password revokes all of them at once, which is the fast way to shut everything down.

A key marked **Disabled** has been switched off for you: a moderator revoked it, or you pressed [This wasn't me](profile-and-preferences.md#this-wasnt-me) in one of your account emails. It stays on your list so you can see what happened. It won't come back on, so make a new one.

## Connecting an AI assistant (MCP)

Initiative can expose a small surface to AI assistants through the **Model Context Protocol (MCP)**, so an assistant can do things like *"list my projects"* or *"add a task to the Auth project"* — using your API key, bound by exactly the same access rules as everything else.

Worth knowing:

- It's **off unless whoever runs your server turns it on**.
- Every action runs **as you**, scoped by your key. An assistant reaches only what *you* could reach.
- The surface is **curated** — any key can read the communities it can reach, the initiatives you belong to and every kind of tool they hold (projects and tasks, files, wikis, queues, counters, calendars, catalogs, notices and dashboards), the comments on any of them, and what any of them is linked to. It can also run the same **search** the app's own search page runs, ranked across the lot.
- A **full-access** key can create and edit those same things, link two of them together, move a task between statuses, and tick a checklist item off. It can say who a new thing is shared with as it creates it, but never change who an existing one is shared with. Deleting (a link included), archiving, bulk edits and AI generation are never exposed, and a read-only key can't write at all.

!!! tip "Read-only, single-community, for assistants"
    That's the right call for most uses. Only reach for a full-access key if you actually want the assistant making changes — and each change is confirmed in the assistant before it runs.

??? techspec "For the technically minded — connecting a client"
    With MCP enabled (whoever runs the server sets `ENABLE_MCP=true`), the server is at `<your-server>/api/v1/mcp/`. Register it with your client using your API key as a bearer token — with Claude Code, for example:

    ```bash
    claude mcp add --transport http initiative \
      https://your-server/api/v1/mcp/ \
      --header "Authorization: Bearer ppk_your_key_here"
    ```

    The exposed tools are route-backed: each call goes through the normal API with your authentication and the same row-level-security access rules, so there's no ambient privilege. Running the server? See [Configuration](../running-a-server/configuration.md).

## Webhooks

A **webhook** tells another service when something changes: a task moved, an event was added, a file went in the trash. You give Initiative an address, it sends a short note there each time, and your service fetches the details with an API key.

Webhooks are set up through the API, with a key that isn't **Read-only**. A read-only key can list them.

- **They belong to the community**, not to whoever made them, and keep running after that person leaves. Anyone in an initiative can set one up for that initiative, and change or remove it. One covering the whole community is for its admins.
- **The note says what changed, never what it now says.** Which item, and which fields. Your service reads the item back through the API, where it sees exactly what its key is allowed to.
- **A delivery your service doesn't accept is tried again**, for a little under two hours, and later changes wait behind it so everything arrives in order. After the last try it's set aside and counted in `dead_letter_count`. Anything above zero means the receiving end wants a look.

??? techspec "For the technically minded — subscriptions, deliveries and signatures"
    **Endpoints**, under `/api/v1/c/{community_id}/webhooks/subscriptions`:

    | | |
    |---|---|
    | `POST` | `{target_url, event_types, fields?, initiative_id?}`. Answers `201` with the subscription and `hmac_secret`. |
    | `GET` | Every subscription you can reach, each with `dead_letter_count`. |
    | `PATCH /{id}` | Any of `target_url`, `event_types`, `fields`, `active`. |
    | `DELETE /{id}` | Removes it. |

    `hmac_secret` is returned **once**, on create. Lost it? Delete the subscription and make a new one. `initiative_id` narrows it to one initiative; left out, it covers the community. `target_url` must be `https` and resolve to a public address (`WEBHOOK_INVALID_TARGET_URL`, `WEBHOOK_PRIVATE_TARGET_URL`).

    **Event types** are `<resource>.created`, `.updated` and `.deleted`. Resources include `tasks`, `projects`, `files`, `wikis`, `wiki_pages`, `calendars`, `calendar_events`, `queues`, `queue_items`, `counter_groups`, `counters`, `catalogs`, `catalog_items`, `posts`, `dashboards`, `comments`, `tags`, `initiatives` and `plugins`. Moving something to the trash sends `deleted`, and restoring it sends `created`. A plug-in in the community can declare events of its own, named `plugin.<plug-in id>.<event>`. An unknown name is refused with `WEBHOOK_UNKNOWN_EVENT_TYPE`.

    **`fields`** narrows `updated` events to changes in those names: a resource's own fields, plus what changes beside it, such as `tags`, `assignees`, `checklist`, `attachments` or `properties` on a task. It doesn't apply to `created` or `deleted`. A name none of the chosen events can report is refused with `WEBHOOK_UNKNOWN_FIELD`.

    **A delivery** is a `POST` of one JSON envelope per transaction:

    ```json
    {
      "event_id": "…",
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

    `community_ref` and `actor_ref` are names for the community and the person made for this subscription, not account ids; `GET` shows the same `community_ref`. `actor_plugin` names the plug-in that made the change, if one did. A plug-in's own event carries `plugin` and `payload` in place of `resource`.

    **Headers and signature:**

    | Header | |
    |---|---|
    | `X-Initiative-Event-ID` | The same on every retry of a batch. Use it to skip one you've already handled. |
    | `X-Initiative-Timestamp` | Unix seconds. |
    | `X-Initiative-Signature` | `sha256=` and the hex HMAC-SHA256 of `<timestamp>.<raw body>`, keyed with `hmac_secret`. |

    Compute the signature over the body exactly as received, compare in constant time, and turn away a timestamp more than a few minutes old.

    **Delivery** counts only a `2xx`; redirects aren't followed. Each attempt has 15 seconds end to end. The waits between attempts are 5 seconds, 30 seconds, 2 minutes, 10 minutes, 30 minutes and 1 hour; after the seventh failed attempt the batch is dead-lettered and not sent again. `PATCH` with `"active": false` stops a subscription's deliveries without deleting it.

## Related

- [Profile & preferences](profile-and-preferences.md) — the rest of your account.
- [Security & privacy](../security/index.md) — how access is enforced.
- [Configuration](../running-a-server/configuration.md) — for whoever runs the server, enabling MCP.
