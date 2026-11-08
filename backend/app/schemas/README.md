# `app/schemas/` — Pydantic payloads, split by tenancy boundary

These are the request/response schemas. They are organized to mirror the
**schema-per-guild** boundary used in [`models/`](../models/README.md),
[`services/`](../services/README.md), and the API
(`api/v1/tenant_endpoints/` vs `platform_endpoints/`). The split is by **the kind
of resource a payload serializes**, so a reader can tell at a glance whether a
schema describes per-guild content or shared/platform data.

| Folder | Serializes payloads for | Examples |
|---|---|---|
| `tenant/` | per-guild content (lives in `guild_<id>` schemas) | project, task, file, counter, calendar_event, comment, initiative, property, tag, import/export, stats over guild content |
| `platform/` | shared/public-schema resources | auth, user, guild, settings, operator, access_grant, notification, push, token, view preferences |
| *root* (here) | generic, used by both sides | `base.py` (sanitized base model), `query.py` (filter/sort/pagination), `ai_generation.py`, `ai_settings.py` (which AI connection a community uses) |

## Rules

- A schema's folder follows the **data it represents**, matching the model/service
  split — keep them aligned (a `tenant/` schema pairs with a `tenant/` model).
- The `Guild` roster payloads are **`platform/`** (the guild entity is a `public`
  table); only per-guild *content* payloads are `tenant/`.
- Don't mix guild and platform payloads in one file. Generic mixins/utilities that
  genuinely serve both stay at the root.
- Class **names are unchanged** by this layout — moving a file does not change the
  generated OpenAPI/Orval output. After editing schema *content*, still regenerate
  the frontend types (see root `CLAUDE.md` "Generated API Types").
