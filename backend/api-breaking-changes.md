# Accepted API breaking changes

`scripts/ci/api-compat` compares this tree's OpenAPI spec with the last
release's and fails on a change that breaks a client written against that
release, unless the change is listed here. Each entry is the method, path and
message the check printed, under a `## After <release>` heading naming the
release it breaks from. Once the next release ships, its entries no longer
matter and can be deleted.

## After 0.77.1

### A summary is streamed

A file's summary arrives as it is written, as JSON lines (`AIStreamEvent`:
`cut`, then `text` pieces, or an `error` code part-way), rather than as one
`{summary}` object at the end.

- POST /api/v1/c/{community_id}/files/{file_id}/ai/summary removed the media type `application/json` for the response with the status `200`

## After 0.76.0

### New values in a response's enums

- GET /api/v1/c/{community_id}/marketplace/listings added the new `term_full` enum value to the `items/items/unavailable/anyOf[subschema #1: ListingUnavailable]/reason` response property for the response status `200`
- GET /api/v1/c/{community_id}/marketplace/listings/by-uid/{uid} added the new `term_full` enum value to the `unavailable/anyOf[subschema #1: ListingUnavailable]/reason` response property for the response status `200`
- GET /api/v1/c/{community_id}/marketplace/listings/{public_id} added the new `term_full` enum value to the `unavailable/anyOf[subschema #1: ListingUnavailable]/reason` response property for the response status `200`
- GET /api/v1/marketplace/local/mine added the new `term_full` enum value to the `items/unavailable/anyOf[subschema #1: ListingUnavailable]/reason` response property for the response status `200`
- GET /api/v1/notifications/ added the new `community_pause_reminder` enum value to the `notifications/items/type` response property for the response status `200`
- GET /api/v1/notifications/{notification_id}/alert added the new `community_pause_reminder` enum value to the `notification/type` response property for the response status `200`
- POST /api/v1/notifications/{notification_id}/read added the new `community_pause_reminder` enum value to the `type` response property for the response status `200`
- POST /api/v1/notifications/{notification_id}/unread added the new `community_pause_reminder` enum value to the `type` response property for the response status `200`
- POST /api/v1/auth/register added the new `billing.control` enum value to the `capabilities/items/` response property for the response status `201`
- POST /api/v1/auth/register added the new `billing.directory` enum value to the `capabilities/items/` response property for the response status `201`
- GET /api/v1/me added the new `billing.control` enum value to the `capabilities/items/` response property for the response status `200`
- GET /api/v1/me added the new `billing.directory` enum value to the `capabilities/items/` response property for the response status `200`
- PATCH /api/v1/me added the new `billing.control` enum value to the `capabilities/items/` response property for the response status `200`
- PATCH /api/v1/me added the new `billing.directory` enum value to the `capabilities/items/` response property for the response status `200`
- POST /api/v1/me/age-confirmation added the new `billing.control` enum value to the `capabilities/items/` response property for the response status `200`
- POST /api/v1/me/age-confirmation added the new `billing.directory` enum value to the `capabilities/items/` response property for the response status `200`
- PUT /api/v1/me/avatar added the new `billing.control` enum value to the `capabilities/items/` response property for the response status `200`
- PUT /api/v1/me/avatar added the new `billing.directory` enum value to the `capabilities/items/` response property for the response status `200`
- POST /api/v1/me/legal-acceptance added the new `billing.control` enum value to the `capabilities/items/` response property for the response status `200`
- POST /api/v1/me/legal-acceptance added the new `billing.directory` enum value to the `capabilities/items/` response property for the response status `200`
- PATCH /api/v1/me/username added the new `billing.control` enum value to the `capabilities/items/` response property for the response status `200`
- PATCH /api/v1/me/username added the new `billing.directory` enum value to the `capabilities/items/` response property for the response status `200`
- GET /api/v1/operator/users added the new `billing.control` enum value to the `items/items/capabilities/items/` response property for the response status `200`
- GET /api/v1/operator/users added the new `billing.directory` enum value to the `items/items/capabilities/items/` response property for the response status `200`
- DELETE /api/v1/operator/users/{user_id}/age-block added the new `billing.control` enum value to the `capabilities/items/` response property for the response status `200`
- DELETE /api/v1/operator/users/{user_id}/age-block added the new `billing.directory` enum value to the `capabilities/items/` response property for the response status `200`
- DELETE /api/v1/operator/users/{user_id}/api-keys added the new `billing.control` enum value to the `capabilities/items/` response property for the response status `200`
- DELETE /api/v1/operator/users/{user_id}/api-keys added the new `billing.directory` enum value to the `capabilities/items/` response property for the response status `200`
- PATCH /api/v1/operator/users/{user_id}/platform-role added the new `billing.control` enum value to the `capabilities/items/` response property for the response status `200`
- PATCH /api/v1/operator/users/{user_id}/platform-role added the new `billing.directory` enum value to the `capabilities/items/` response property for the response status `200`
- DELETE /api/v1/operator/users/{user_id}/profile/{field} added the new `billing.control` enum value to the `capabilities/items/` response property for the response status `200`
- DELETE /api/v1/operator/users/{user_id}/profile/{field} added the new `billing.directory` enum value to the `capabilities/items/` response property for the response status `200`
- POST /api/v1/operator/users/{user_id}/reactivate added the new `billing.control` enum value to the `capabilities/items/` response property for the response status `200`
- POST /api/v1/operator/users/{user_id}/reactivate added the new `billing.directory` enum value to the `capabilities/items/` response property for the response status `200`
- POST /api/v1/operator/users/{user_id}/restore added the new `billing.control` enum value to the `capabilities/items/` response property for the response status `200`
- POST /api/v1/operator/users/{user_id}/restore added the new `billing.directory` enum value to the `capabilities/items/` response property for the response status `200`
- DELETE /api/v1/operator/users/{user_id}/sessions added the new `billing.control` enum value to the `capabilities/items/` response property for the response status `200`
- DELETE /api/v1/operator/users/{user_id}/sessions added the new `billing.directory` enum value to the `capabilities/items/` response property for the response status `200`
- DELETE /api/v1/operator/users/{user_id}/sign-in-lock added the new `billing.control` enum value to the `capabilities/items/` response property for the response status `200`
- DELETE /api/v1/operator/users/{user_id}/sign-in-lock added the new `billing.directory` enum value to the `capabilities/items/` response property for the response status `200`
- POST /api/v1/operator/users/{user_id}/suspension added the new `billing.control` enum value to the `capabilities/items/` response property for the response status `200`
- POST /api/v1/operator/users/{user_id}/suspension added the new `billing.directory` enum value to the `capabilities/items/` response property for the response status `200`
- PATCH /api/v1/operator/users/{user_id}/username added the new `billing.control` enum value to the `capabilities/items/` response property for the response status `200`
- PATCH /api/v1/operator/users/{user_id}/username added the new `billing.directory` enum value to the `capabilities/items/` response property for the response status `200`
- GET /api/v1/c/{community_id}/settings/ai/connections added the new `deepseek` enum value to the `items/provider` response property for the response status `200`
- GET /api/v1/c/{community_id}/settings/ai/connections added the new `gemini` enum value to the `items/provider` response property for the response status `200`
- GET /api/v1/c/{community_id}/settings/ai/connections added the new `groq` enum value to the `items/provider` response property for the response status `200`
- GET /api/v1/c/{community_id}/settings/ai/connections added the new `openrouter` enum value to the `items/provider` response property for the response status `200`
- GET /api/v1/c/{community_id}/settings/ai/connections added the new `together` enum value to the `items/provider` response property for the response status `200`
- GET /api/v1/c/{community_id}/settings/ai/connections added the new `xai` enum value to the `items/provider` response property for the response status `200`
- POST /api/v1/c/{community_id}/settings/ai/connections added the new `deepseek` enum value to the `provider` response property for the response status `200`
- POST /api/v1/c/{community_id}/settings/ai/connections added the new `gemini` enum value to the `provider` response property for the response status `200`
- POST /api/v1/c/{community_id}/settings/ai/connections added the new `groq` enum value to the `provider` response property for the response status `200`
- POST /api/v1/c/{community_id}/settings/ai/connections added the new `openrouter` enum value to the `provider` response property for the response status `200`
- POST /api/v1/c/{community_id}/settings/ai/connections added the new `together` enum value to the `provider` response property for the response status `200`
- POST /api/v1/c/{community_id}/settings/ai/connections added the new `xai` enum value to the `provider` response property for the response status `200`
- PUT /api/v1/c/{community_id}/settings/ai/connections/{connection_id} added the new `deepseek` enum value to the `provider` response property for the response status `200`
- PUT /api/v1/c/{community_id}/settings/ai/connections/{connection_id} added the new `gemini` enum value to the `provider` response property for the response status `200`
- PUT /api/v1/c/{community_id}/settings/ai/connections/{connection_id} added the new `groq` enum value to the `provider` response property for the response status `200`
- PUT /api/v1/c/{community_id}/settings/ai/connections/{connection_id} added the new `openrouter` enum value to the `provider` response property for the response status `200`
- PUT /api/v1/c/{community_id}/settings/ai/connections/{connection_id} added the new `together` enum value to the `provider` response property for the response status `200`
- PUT /api/v1/c/{community_id}/settings/ai/connections/{connection_id} added the new `xai` enum value to the `provider` response property for the response status `200`
- GET /api/v1/c/{community_id}/settings/ai/resolved added the new `deepseek` enum value to the `provider/anyOf[subschema #1: AIProvider]/` response property for the response status `200`
- GET /api/v1/c/{community_id}/settings/ai/resolved added the new `gemini` enum value to the `provider/anyOf[subschema #1: AIProvider]/` response property for the response status `200`
- GET /api/v1/c/{community_id}/settings/ai/resolved added the new `groq` enum value to the `provider/anyOf[subschema #1: AIProvider]/` response property for the response status `200`
- GET /api/v1/c/{community_id}/settings/ai/resolved added the new `openrouter` enum value to the `provider/anyOf[subschema #1: AIProvider]/` response property for the response status `200`
- GET /api/v1/c/{community_id}/settings/ai/resolved added the new `together` enum value to the `provider/anyOf[subschema #1: AIProvider]/` response property for the response status `200`
- GET /api/v1/c/{community_id}/settings/ai/resolved added the new `xai` enum value to the `provider/anyOf[subschema #1: AIProvider]/` response property for the response status `200`
- GET /api/v1/settings/ai/platform/connections added the new `deepseek` enum value to the `items/provider` response property for the response status `200`
- GET /api/v1/settings/ai/platform/connections added the new `gemini` enum value to the `items/provider` response property for the response status `200`
- GET /api/v1/settings/ai/platform/connections added the new `groq` enum value to the `items/provider` response property for the response status `200`
- GET /api/v1/settings/ai/platform/connections added the new `openrouter` enum value to the `items/provider` response property for the response status `200`
- GET /api/v1/settings/ai/platform/connections added the new `together` enum value to the `items/provider` response property for the response status `200`
- GET /api/v1/settings/ai/platform/connections added the new `xai` enum value to the `items/provider` response property for the response status `200`
- POST /api/v1/settings/ai/platform/connections added the new `deepseek` enum value to the `provider` response property for the response status `200`
- POST /api/v1/settings/ai/platform/connections added the new `gemini` enum value to the `provider` response property for the response status `200`
- POST /api/v1/settings/ai/platform/connections added the new `groq` enum value to the `provider` response property for the response status `200`
- POST /api/v1/settings/ai/platform/connections added the new `openrouter` enum value to the `provider` response property for the response status `200`
- POST /api/v1/settings/ai/platform/connections added the new `together` enum value to the `provider` response property for the response status `200`
- POST /api/v1/settings/ai/platform/connections added the new `xai` enum value to the `provider` response property for the response status `200`
- PUT /api/v1/settings/ai/platform/connections/{connection_id} added the new `deepseek` enum value to the `provider` response property for the response status `200`
- PUT /api/v1/settings/ai/platform/connections/{connection_id} added the new `gemini` enum value to the `provider` response property for the response status `200`
- PUT /api/v1/settings/ai/platform/connections/{connection_id} added the new `groq` enum value to the `provider` response property for the response status `200`
- PUT /api/v1/settings/ai/platform/connections/{connection_id} added the new `openrouter` enum value to the `provider` response property for the response status `200`
- PUT /api/v1/settings/ai/platform/connections/{connection_id} added the new `together` enum value to the `provider` response property for the response status `200`
- PUT /api/v1/settings/ai/platform/connections/{connection_id} added the new `xai` enum value to the `provider` response property for the response status `200`
- POST /api/v1/auth/register added the new `access.request_any` enum value to the `capabilities/items/` response property for the response status `201`
- GET /api/v1/me added the new `access.request_any` enum value to the `capabilities/items/` response property for the response status `200`
- PATCH /api/v1/me added the new `access.request_any` enum value to the `capabilities/items/` response property for the response status `200`
- POST /api/v1/me/age-confirmation added the new `access.request_any` enum value to the `capabilities/items/` response property for the response status `200`
- PUT /api/v1/me/avatar added the new `access.request_any` enum value to the `capabilities/items/` response property for the response status `200`
- POST /api/v1/me/legal-acceptance added the new `access.request_any` enum value to the `capabilities/items/` response property for the response status `200`
- PATCH /api/v1/me/username added the new `access.request_any` enum value to the `capabilities/items/` response property for the response status `200`
- GET /api/v1/operator/users added the new `access.request_any` enum value to the `items/items/capabilities/items/` response property for the response status `200`
- DELETE /api/v1/operator/users/{user_id}/age-block added the new `access.request_any` enum value to the `capabilities/items/` response property for the response status `200`
- DELETE /api/v1/operator/users/{user_id}/api-keys added the new `access.request_any` enum value to the `capabilities/items/` response property for the response status `200`
- PATCH /api/v1/operator/users/{user_id}/platform-role added the new `access.request_any` enum value to the `capabilities/items/` response property for the response status `200`
- DELETE /api/v1/operator/users/{user_id}/profile/{field} added the new `access.request_any` enum value to the `capabilities/items/` response property for the response status `200`
- POST /api/v1/operator/users/{user_id}/reactivate added the new `access.request_any` enum value to the `capabilities/items/` response property for the response status `200`
- POST /api/v1/operator/users/{user_id}/restore added the new `access.request_any` enum value to the `capabilities/items/` response property for the response status `200`
- DELETE /api/v1/operator/users/{user_id}/sessions added the new `access.request_any` enum value to the `capabilities/items/` response property for the response status `200`
- DELETE /api/v1/operator/users/{user_id}/sign-in-lock added the new `access.request_any` enum value to the `capabilities/items/` response property for the response status `200`
- POST /api/v1/operator/users/{user_id}/suspension added the new `access.request_any` enum value to the `capabilities/items/` response property for the response status `200`
- PATCH /api/v1/operator/users/{user_id}/username added the new `access.request_any` enum value to the `capabilities/items/` response property for the response status `200`

### A task's type is a field

Task types make the type a field a layout can place (`type`, in every list of a
task's fields) and give the field catalogue a control for it (`task_type`). A
client drawing a layout or a filter meets a field or control it does not know,
as it does a plug-in's.

- GET /api/v1/c/{community_id}/layouts/ added the new `type` enum value to the `layouts/items/oneOf[subschema #1: ListLayoutRead]/definition/card/anyOf[subschema #1: CardPart]/children/items/oneOf[subschema #2: StackPart]/children/items/oneOf[subschema #3: FieldPart]/props/field/anyOf[subschema #1: TaskFieldId]/` response property for the response status `200`
- GET /api/v1/c/{community_id}/layouts/ added the new `type` enum value to the `layouts/items/oneOf[subschema #1: ListLayoutRead]/definition/card/anyOf[subschema #1: CardPart]/children/items/oneOf[subschema #3: FieldPart]/props/field/anyOf[subschema #1: TaskFieldId]/` response property for the response status `200`
- GET /api/v1/c/{community_id}/layouts/ added the new `type` enum value to the `layouts/items/oneOf[subschema #1: ListLayoutRead]/definition/columns/anyOf[subschema #1]/items/anyOf[subschema #1: TaskColumnFieldId]/` response property for the response status `200`
- GET /api/v1/c/{community_id}/layouts/ added the new `type` enum value to the `layouts/items/oneOf[subschema #2: DetailLayoutRead]/definition/header/anyOf[subschema #1]/items/oneOf[subschema #1: DetailStackPart]/children/items/oneOf[subschema #2: SectionPart]/children/items/oneOf[subschema #3: DetailFieldPart]/props/field/anyOf[subschema #1: TaskDetailFieldId]/` response property for the response status `200`
- GET /api/v1/c/{community_id}/layouts/ added the new `type` enum value to the `layouts/items/oneOf[subschema #2: DetailLayoutRead]/definition/header/anyOf[subschema #1]/items/oneOf[subschema #1: DetailStackPart]/children/items/oneOf[subschema #3: DetailFieldPart]/props/field/anyOf[subschema #1: TaskDetailFieldId]/` response property for the response status `200`
- GET /api/v1/c/{community_id}/layouts/ added the new `type` enum value to the `layouts/items/oneOf[subschema #2: DetailLayoutRead]/definition/header/anyOf[subschema #1]/items/oneOf[subschema #2: SectionPart]/children/items/oneOf[subschema #3: DetailFieldPart]/props/field/anyOf[subschema #1: TaskDetailFieldId]/` response property for the response status `200`
- GET /api/v1/c/{community_id}/layouts/ added the new `type` enum value to the `layouts/items/oneOf[subschema #2: DetailLayoutRead]/definition/header/anyOf[subschema #1]/items/oneOf[subschema #3: DetailFieldPart]/props/field/anyOf[subschema #1: TaskDetailFieldId]/` response property for the response status `200`
- GET /api/v1/c/{community_id}/layouts/ added the new `type` enum value to the `layouts/items/oneOf[subschema #2: DetailLayoutRead]/definition/main/anyOf[subschema #1]/items/oneOf[subschema #1: DetailStackPart]/children/items/oneOf[subschema #2: SectionPart]/children/items/oneOf[subschema #3: DetailFieldPart]/props/field/anyOf[subschema #1: TaskDetailFieldId]/` response property for the response status `200`
- GET /api/v1/c/{community_id}/layouts/ added the new `type` enum value to the `layouts/items/oneOf[subschema #2: DetailLayoutRead]/definition/main/anyOf[subschema #1]/items/oneOf[subschema #1: DetailStackPart]/children/items/oneOf[subschema #3: DetailFieldPart]/props/field/anyOf[subschema #1: TaskDetailFieldId]/` response property for the response status `200`
- GET /api/v1/c/{community_id}/layouts/ added the new `type` enum value to the `layouts/items/oneOf[subschema #2: DetailLayoutRead]/definition/main/anyOf[subschema #1]/items/oneOf[subschema #2: SectionPart]/children/items/oneOf[subschema #3: DetailFieldPart]/props/field/anyOf[subschema #1: TaskDetailFieldId]/` response property for the response status `200`
- GET /api/v1/c/{community_id}/layouts/ added the new `type` enum value to the `layouts/items/oneOf[subschema #2: DetailLayoutRead]/definition/main/anyOf[subschema #1]/items/oneOf[subschema #3: DetailFieldPart]/props/field/anyOf[subschema #1: TaskDetailFieldId]/` response property for the response status `200`
- GET /api/v1/c/{community_id}/layouts/ added the new `type` enum value to the `layouts/items/oneOf[subschema #2: DetailLayoutRead]/definition/side/anyOf[subschema #1]/items/oneOf[subschema #1: DetailStackPart]/children/items/oneOf[subschema #2: SectionPart]/children/items/oneOf[subschema #3: DetailFieldPart]/props/field/anyOf[subschema #1: TaskDetailFieldId]/` response property for the response status `200`
- GET /api/v1/c/{community_id}/layouts/ added the new `type` enum value to the `layouts/items/oneOf[subschema #2: DetailLayoutRead]/definition/side/anyOf[subschema #1]/items/oneOf[subschema #1: DetailStackPart]/children/items/oneOf[subschema #3: DetailFieldPart]/props/field/anyOf[subschema #1: TaskDetailFieldId]/` response property for the response status `200`
- GET /api/v1/c/{community_id}/layouts/ added the new `type` enum value to the `layouts/items/oneOf[subschema #2: DetailLayoutRead]/definition/side/anyOf[subschema #1]/items/oneOf[subschema #2: SectionPart]/children/items/oneOf[subschema #3: DetailFieldPart]/props/field/anyOf[subschema #1: TaskDetailFieldId]/` response property for the response status `200`
- GET /api/v1/c/{community_id}/layouts/ added the new `type` enum value to the `layouts/items/oneOf[subschema #2: DetailLayoutRead]/definition/side/anyOf[subschema #1]/items/oneOf[subschema #3: DetailFieldPart]/props/field/anyOf[subschema #1: TaskDetailFieldId]/` response property for the response status `200`
- PUT /api/v1/c/{community_id}/layouts/ added the new `type` enum value to the `layouts/items/oneOf[subschema #1: ListLayoutRead]/definition/card/anyOf[subschema #1: CardPart]/children/items/oneOf[subschema #2: StackPart]/children/items/oneOf[subschema #3: FieldPart]/props/field/anyOf[subschema #1: TaskFieldId]/` response property for the response status `200`
- PUT /api/v1/c/{community_id}/layouts/ added the new `type` enum value to the `layouts/items/oneOf[subschema #1: ListLayoutRead]/definition/card/anyOf[subschema #1: CardPart]/children/items/oneOf[subschema #3: FieldPart]/props/field/anyOf[subschema #1: TaskFieldId]/` response property for the response status `200`
- PUT /api/v1/c/{community_id}/layouts/ added the new `type` enum value to the `layouts/items/oneOf[subschema #1: ListLayoutRead]/definition/columns/anyOf[subschema #1]/items/anyOf[subschema #1: TaskColumnFieldId]/` response property for the response status `200`
- PUT /api/v1/c/{community_id}/layouts/ added the new `type` enum value to the `layouts/items/oneOf[subschema #2: DetailLayoutRead]/definition/header/anyOf[subschema #1]/items/oneOf[subschema #1: DetailStackPart]/children/items/oneOf[subschema #2: SectionPart]/children/items/oneOf[subschema #3: DetailFieldPart]/props/field/anyOf[subschema #1: TaskDetailFieldId]/` response property for the response status `200`
- PUT /api/v1/c/{community_id}/layouts/ added the new `type` enum value to the `layouts/items/oneOf[subschema #2: DetailLayoutRead]/definition/header/anyOf[subschema #1]/items/oneOf[subschema #1: DetailStackPart]/children/items/oneOf[subschema #3: DetailFieldPart]/props/field/anyOf[subschema #1: TaskDetailFieldId]/` response property for the response status `200`
- PUT /api/v1/c/{community_id}/layouts/ added the new `type` enum value to the `layouts/items/oneOf[subschema #2: DetailLayoutRead]/definition/header/anyOf[subschema #1]/items/oneOf[subschema #2: SectionPart]/children/items/oneOf[subschema #3: DetailFieldPart]/props/field/anyOf[subschema #1: TaskDetailFieldId]/` response property for the response status `200`
- PUT /api/v1/c/{community_id}/layouts/ added the new `type` enum value to the `layouts/items/oneOf[subschema #2: DetailLayoutRead]/definition/header/anyOf[subschema #1]/items/oneOf[subschema #3: DetailFieldPart]/props/field/anyOf[subschema #1: TaskDetailFieldId]/` response property for the response status `200`
- PUT /api/v1/c/{community_id}/layouts/ added the new `type` enum value to the `layouts/items/oneOf[subschema #2: DetailLayoutRead]/definition/main/anyOf[subschema #1]/items/oneOf[subschema #1: DetailStackPart]/children/items/oneOf[subschema #2: SectionPart]/children/items/oneOf[subschema #3: DetailFieldPart]/props/field/anyOf[subschema #1: TaskDetailFieldId]/` response property for the response status `200`
- PUT /api/v1/c/{community_id}/layouts/ added the new `type` enum value to the `layouts/items/oneOf[subschema #2: DetailLayoutRead]/definition/main/anyOf[subschema #1]/items/oneOf[subschema #1: DetailStackPart]/children/items/oneOf[subschema #3: DetailFieldPart]/props/field/anyOf[subschema #1: TaskDetailFieldId]/` response property for the response status `200`
- PUT /api/v1/c/{community_id}/layouts/ added the new `type` enum value to the `layouts/items/oneOf[subschema #2: DetailLayoutRead]/definition/main/anyOf[subschema #1]/items/oneOf[subschema #2: SectionPart]/children/items/oneOf[subschema #3: DetailFieldPart]/props/field/anyOf[subschema #1: TaskDetailFieldId]/` response property for the response status `200`
- PUT /api/v1/c/{community_id}/layouts/ added the new `type` enum value to the `layouts/items/oneOf[subschema #2: DetailLayoutRead]/definition/main/anyOf[subschema #1]/items/oneOf[subschema #3: DetailFieldPart]/props/field/anyOf[subschema #1: TaskDetailFieldId]/` response property for the response status `200`
- PUT /api/v1/c/{community_id}/layouts/ added the new `type` enum value to the `layouts/items/oneOf[subschema #2: DetailLayoutRead]/definition/side/anyOf[subschema #1]/items/oneOf[subschema #1: DetailStackPart]/children/items/oneOf[subschema #2: SectionPart]/children/items/oneOf[subschema #3: DetailFieldPart]/props/field/anyOf[subschema #1: TaskDetailFieldId]/` response property for the response status `200`
- PUT /api/v1/c/{community_id}/layouts/ added the new `type` enum value to the `layouts/items/oneOf[subschema #2: DetailLayoutRead]/definition/side/anyOf[subschema #1]/items/oneOf[subschema #1: DetailStackPart]/children/items/oneOf[subschema #3: DetailFieldPart]/props/field/anyOf[subschema #1: TaskDetailFieldId]/` response property for the response status `200`
- PUT /api/v1/c/{community_id}/layouts/ added the new `type` enum value to the `layouts/items/oneOf[subschema #2: DetailLayoutRead]/definition/side/anyOf[subschema #1]/items/oneOf[subschema #2: SectionPart]/children/items/oneOf[subschema #3: DetailFieldPart]/props/field/anyOf[subschema #1: TaskDetailFieldId]/` response property for the response status `200`
- PUT /api/v1/c/{community_id}/layouts/ added the new `type` enum value to the `layouts/items/oneOf[subschema #2: DetailLayoutRead]/definition/side/anyOf[subschema #1]/items/oneOf[subschema #3: DetailFieldPart]/props/field/anyOf[subschema #1: TaskDetailFieldId]/` response property for the response status `200`
- PUT /api/v1/c/{community_id}/layouts/default added the new `type` enum value to the `layouts/items/oneOf[subschema #1: ListLayoutRead]/definition/card/anyOf[subschema #1: CardPart]/children/items/oneOf[subschema #2: StackPart]/children/items/oneOf[subschema #3: FieldPart]/props/field/anyOf[subschema #1: TaskFieldId]/` response property for the response status `200`
- PUT /api/v1/c/{community_id}/layouts/default added the new `type` enum value to the `layouts/items/oneOf[subschema #1: ListLayoutRead]/definition/card/anyOf[subschema #1: CardPart]/children/items/oneOf[subschema #3: FieldPart]/props/field/anyOf[subschema #1: TaskFieldId]/` response property for the response status `200`
- PUT /api/v1/c/{community_id}/layouts/default added the new `type` enum value to the `layouts/items/oneOf[subschema #1: ListLayoutRead]/definition/columns/anyOf[subschema #1]/items/anyOf[subschema #1: TaskColumnFieldId]/` response property for the response status `200`
- PUT /api/v1/c/{community_id}/layouts/default added the new `type` enum value to the `layouts/items/oneOf[subschema #2: DetailLayoutRead]/definition/header/anyOf[subschema #1]/items/oneOf[subschema #1: DetailStackPart]/children/items/oneOf[subschema #2: SectionPart]/children/items/oneOf[subschema #3: DetailFieldPart]/props/field/anyOf[subschema #1: TaskDetailFieldId]/` response property for the response status `200`
- PUT /api/v1/c/{community_id}/layouts/default added the new `type` enum value to the `layouts/items/oneOf[subschema #2: DetailLayoutRead]/definition/header/anyOf[subschema #1]/items/oneOf[subschema #1: DetailStackPart]/children/items/oneOf[subschema #3: DetailFieldPart]/props/field/anyOf[subschema #1: TaskDetailFieldId]/` response property for the response status `200`
- PUT /api/v1/c/{community_id}/layouts/default added the new `type` enum value to the `layouts/items/oneOf[subschema #2: DetailLayoutRead]/definition/header/anyOf[subschema #1]/items/oneOf[subschema #2: SectionPart]/children/items/oneOf[subschema #3: DetailFieldPart]/props/field/anyOf[subschema #1: TaskDetailFieldId]/` response property for the response status `200`
- PUT /api/v1/c/{community_id}/layouts/default added the new `type` enum value to the `layouts/items/oneOf[subschema #2: DetailLayoutRead]/definition/header/anyOf[subschema #1]/items/oneOf[subschema #3: DetailFieldPart]/props/field/anyOf[subschema #1: TaskDetailFieldId]/` response property for the response status `200`
- PUT /api/v1/c/{community_id}/layouts/default added the new `type` enum value to the `layouts/items/oneOf[subschema #2: DetailLayoutRead]/definition/main/anyOf[subschema #1]/items/oneOf[subschema #1: DetailStackPart]/children/items/oneOf[subschema #2: SectionPart]/children/items/oneOf[subschema #3: DetailFieldPart]/props/field/anyOf[subschema #1: TaskDetailFieldId]/` response property for the response status `200`
- PUT /api/v1/c/{community_id}/layouts/default added the new `type` enum value to the `layouts/items/oneOf[subschema #2: DetailLayoutRead]/definition/main/anyOf[subschema #1]/items/oneOf[subschema #1: DetailStackPart]/children/items/oneOf[subschema #3: DetailFieldPart]/props/field/anyOf[subschema #1: TaskDetailFieldId]/` response property for the response status `200`
- PUT /api/v1/c/{community_id}/layouts/default added the new `type` enum value to the `layouts/items/oneOf[subschema #2: DetailLayoutRead]/definition/main/anyOf[subschema #1]/items/oneOf[subschema #2: SectionPart]/children/items/oneOf[subschema #3: DetailFieldPart]/props/field/anyOf[subschema #1: TaskDetailFieldId]/` response property for the response status `200`
- PUT /api/v1/c/{community_id}/layouts/default added the new `type` enum value to the `layouts/items/oneOf[subschema #2: DetailLayoutRead]/definition/main/anyOf[subschema #1]/items/oneOf[subschema #3: DetailFieldPart]/props/field/anyOf[subschema #1: TaskDetailFieldId]/` response property for the response status `200`
- PUT /api/v1/c/{community_id}/layouts/default added the new `type` enum value to the `layouts/items/oneOf[subschema #2: DetailLayoutRead]/definition/side/anyOf[subschema #1]/items/oneOf[subschema #1: DetailStackPart]/children/items/oneOf[subschema #2: SectionPart]/children/items/oneOf[subschema #3: DetailFieldPart]/props/field/anyOf[subschema #1: TaskDetailFieldId]/` response property for the response status `200`
- PUT /api/v1/c/{community_id}/layouts/default added the new `type` enum value to the `layouts/items/oneOf[subschema #2: DetailLayoutRead]/definition/side/anyOf[subschema #1]/items/oneOf[subschema #1: DetailStackPart]/children/items/oneOf[subschema #3: DetailFieldPart]/props/field/anyOf[subschema #1: TaskDetailFieldId]/` response property for the response status `200`
- PUT /api/v1/c/{community_id}/layouts/default added the new `type` enum value to the `layouts/items/oneOf[subschema #2: DetailLayoutRead]/definition/side/anyOf[subschema #1]/items/oneOf[subschema #2: SectionPart]/children/items/oneOf[subschema #3: DetailFieldPart]/props/field/anyOf[subschema #1: TaskDetailFieldId]/` response property for the response status `200`
- PUT /api/v1/c/{community_id}/layouts/default added the new `type` enum value to the `layouts/items/oneOf[subschema #2: DetailLayoutRead]/definition/side/anyOf[subschema #1]/items/oneOf[subschema #3: DetailFieldPart]/props/field/anyOf[subschema #1: TaskDetailFieldId]/` response property for the response status `200`
- GET /api/v1/c/{community_id}/layouts/initiative added the new `type` enum value to the `items/layouts/items/oneOf[subschema #1: ListLayoutRead]/definition/card/anyOf[subschema #1: CardPart]/children/items/oneOf[subschema #2: StackPart]/children/items/oneOf[subschema #3: FieldPart]/props/field/anyOf[subschema #1: TaskFieldId]/` response property for the response status `200`
- GET /api/v1/c/{community_id}/layouts/initiative added the new `type` enum value to the `items/layouts/items/oneOf[subschema #1: ListLayoutRead]/definition/card/anyOf[subschema #1: CardPart]/children/items/oneOf[subschema #3: FieldPart]/props/field/anyOf[subschema #1: TaskFieldId]/` response property for the response status `200`
- GET /api/v1/c/{community_id}/layouts/initiative added the new `type` enum value to the `items/layouts/items/oneOf[subschema #1: ListLayoutRead]/definition/columns/anyOf[subschema #1]/items/anyOf[subschema #1: TaskColumnFieldId]/` response property for the response status `200`
- GET /api/v1/c/{community_id}/layouts/initiative added the new `type` enum value to the `items/layouts/items/oneOf[subschema #2: DetailLayoutRead]/definition/header/anyOf[subschema #1]/items/oneOf[subschema #1: DetailStackPart]/children/items/oneOf[subschema #2: SectionPart]/children/items/oneOf[subschema #3: DetailFieldPart]/props/field/anyOf[subschema #1: TaskDetailFieldId]/` response property for the response status `200`
- GET /api/v1/c/{community_id}/layouts/initiative added the new `type` enum value to the `items/layouts/items/oneOf[subschema #2: DetailLayoutRead]/definition/header/anyOf[subschema #1]/items/oneOf[subschema #1: DetailStackPart]/children/items/oneOf[subschema #3: DetailFieldPart]/props/field/anyOf[subschema #1: TaskDetailFieldId]/` response property for the response status `200`
- GET /api/v1/c/{community_id}/layouts/initiative added the new `type` enum value to the `items/layouts/items/oneOf[subschema #2: DetailLayoutRead]/definition/header/anyOf[subschema #1]/items/oneOf[subschema #2: SectionPart]/children/items/oneOf[subschema #3: DetailFieldPart]/props/field/anyOf[subschema #1: TaskDetailFieldId]/` response property for the response status `200`
- GET /api/v1/c/{community_id}/layouts/initiative added the new `type` enum value to the `items/layouts/items/oneOf[subschema #2: DetailLayoutRead]/definition/header/anyOf[subschema #1]/items/oneOf[subschema #3: DetailFieldPart]/props/field/anyOf[subschema #1: TaskDetailFieldId]/` response property for the response status `200`
- GET /api/v1/c/{community_id}/layouts/initiative added the new `type` enum value to the `items/layouts/items/oneOf[subschema #2: DetailLayoutRead]/definition/main/anyOf[subschema #1]/items/oneOf[subschema #1: DetailStackPart]/children/items/oneOf[subschema #2: SectionPart]/children/items/oneOf[subschema #3: DetailFieldPart]/props/field/anyOf[subschema #1: TaskDetailFieldId]/` response property for the response status `200`
- GET /api/v1/c/{community_id}/layouts/initiative added the new `type` enum value to the `items/layouts/items/oneOf[subschema #2: DetailLayoutRead]/definition/main/anyOf[subschema #1]/items/oneOf[subschema #1: DetailStackPart]/children/items/oneOf[subschema #3: DetailFieldPart]/props/field/anyOf[subschema #1: TaskDetailFieldId]/` response property for the response status `200`
- GET /api/v1/c/{community_id}/layouts/initiative added the new `type` enum value to the `items/layouts/items/oneOf[subschema #2: DetailLayoutRead]/definition/main/anyOf[subschema #1]/items/oneOf[subschema #2: SectionPart]/children/items/oneOf[subschema #3: DetailFieldPart]/props/field/anyOf[subschema #1: TaskDetailFieldId]/` response property for the response status `200`
- GET /api/v1/c/{community_id}/layouts/initiative added the new `type` enum value to the `items/layouts/items/oneOf[subschema #2: DetailLayoutRead]/definition/main/anyOf[subschema #1]/items/oneOf[subschema #3: DetailFieldPart]/props/field/anyOf[subschema #1: TaskDetailFieldId]/` response property for the response status `200`
- GET /api/v1/c/{community_id}/layouts/initiative added the new `type` enum value to the `items/layouts/items/oneOf[subschema #2: DetailLayoutRead]/definition/side/anyOf[subschema #1]/items/oneOf[subschema #1: DetailStackPart]/children/items/oneOf[subschema #2: SectionPart]/children/items/oneOf[subschema #3: DetailFieldPart]/props/field/anyOf[subschema #1: TaskDetailFieldId]/` response property for the response status `200`
- GET /api/v1/c/{community_id}/layouts/initiative added the new `type` enum value to the `items/layouts/items/oneOf[subschema #2: DetailLayoutRead]/definition/side/anyOf[subschema #1]/items/oneOf[subschema #1: DetailStackPart]/children/items/oneOf[subschema #3: DetailFieldPart]/props/field/anyOf[subschema #1: TaskDetailFieldId]/` response property for the response status `200`
- GET /api/v1/c/{community_id}/layouts/initiative added the new `type` enum value to the `items/layouts/items/oneOf[subschema #2: DetailLayoutRead]/definition/side/anyOf[subschema #1]/items/oneOf[subschema #2: SectionPart]/children/items/oneOf[subschema #3: DetailFieldPart]/props/field/anyOf[subschema #1: TaskDetailFieldId]/` response property for the response status `200`
- GET /api/v1/c/{community_id}/layouts/initiative added the new `type` enum value to the `items/layouts/items/oneOf[subschema #2: DetailLayoutRead]/definition/side/anyOf[subschema #1]/items/oneOf[subschema #3: DetailFieldPart]/props/field/anyOf[subschema #1: TaskDetailFieldId]/` response property for the response status `200`
- DELETE /api/v1/c/{community_id}/layouts/{kind} added the new `type` enum value to the `layouts/items/oneOf[subschema #1: ListLayoutRead]/definition/card/anyOf[subschema #1: CardPart]/children/items/oneOf[subschema #2: StackPart]/children/items/oneOf[subschema #3: FieldPart]/props/field/anyOf[subschema #1: TaskFieldId]/` response property for the response status `200`
- DELETE /api/v1/c/{community_id}/layouts/{kind} added the new `type` enum value to the `layouts/items/oneOf[subschema #1: ListLayoutRead]/definition/card/anyOf[subschema #1: CardPart]/children/items/oneOf[subschema #3: FieldPart]/props/field/anyOf[subschema #1: TaskFieldId]/` response property for the response status `200`
- DELETE /api/v1/c/{community_id}/layouts/{kind} added the new `type` enum value to the `layouts/items/oneOf[subschema #1: ListLayoutRead]/definition/columns/anyOf[subschema #1]/items/anyOf[subschema #1: TaskColumnFieldId]/` response property for the response status `200`
- DELETE /api/v1/c/{community_id}/layouts/{kind} added the new `type` enum value to the `layouts/items/oneOf[subschema #2: DetailLayoutRead]/definition/header/anyOf[subschema #1]/items/oneOf[subschema #1: DetailStackPart]/children/items/oneOf[subschema #2: SectionPart]/children/items/oneOf[subschema #3: DetailFieldPart]/props/field/anyOf[subschema #1: TaskDetailFieldId]/` response property for the response status `200`
- DELETE /api/v1/c/{community_id}/layouts/{kind} added the new `type` enum value to the `layouts/items/oneOf[subschema #2: DetailLayoutRead]/definition/header/anyOf[subschema #1]/items/oneOf[subschema #1: DetailStackPart]/children/items/oneOf[subschema #3: DetailFieldPart]/props/field/anyOf[subschema #1: TaskDetailFieldId]/` response property for the response status `200`
- DELETE /api/v1/c/{community_id}/layouts/{kind} added the new `type` enum value to the `layouts/items/oneOf[subschema #2: DetailLayoutRead]/definition/header/anyOf[subschema #1]/items/oneOf[subschema #2: SectionPart]/children/items/oneOf[subschema #3: DetailFieldPart]/props/field/anyOf[subschema #1: TaskDetailFieldId]/` response property for the response status `200`
- DELETE /api/v1/c/{community_id}/layouts/{kind} added the new `type` enum value to the `layouts/items/oneOf[subschema #2: DetailLayoutRead]/definition/header/anyOf[subschema #1]/items/oneOf[subschema #3: DetailFieldPart]/props/field/anyOf[subschema #1: TaskDetailFieldId]/` response property for the response status `200`
- DELETE /api/v1/c/{community_id}/layouts/{kind} added the new `type` enum value to the `layouts/items/oneOf[subschema #2: DetailLayoutRead]/definition/main/anyOf[subschema #1]/items/oneOf[subschema #1: DetailStackPart]/children/items/oneOf[subschema #2: SectionPart]/children/items/oneOf[subschema #3: DetailFieldPart]/props/field/anyOf[subschema #1: TaskDetailFieldId]/` response property for the response status `200`
- DELETE /api/v1/c/{community_id}/layouts/{kind} added the new `type` enum value to the `layouts/items/oneOf[subschema #2: DetailLayoutRead]/definition/main/anyOf[subschema #1]/items/oneOf[subschema #1: DetailStackPart]/children/items/oneOf[subschema #3: DetailFieldPart]/props/field/anyOf[subschema #1: TaskDetailFieldId]/` response property for the response status `200`
- DELETE /api/v1/c/{community_id}/layouts/{kind} added the new `type` enum value to the `layouts/items/oneOf[subschema #2: DetailLayoutRead]/definition/main/anyOf[subschema #1]/items/oneOf[subschema #2: SectionPart]/children/items/oneOf[subschema #3: DetailFieldPart]/props/field/anyOf[subschema #1: TaskDetailFieldId]/` response property for the response status `200`
- DELETE /api/v1/c/{community_id}/layouts/{kind} added the new `type` enum value to the `layouts/items/oneOf[subschema #2: DetailLayoutRead]/definition/main/anyOf[subschema #1]/items/oneOf[subschema #3: DetailFieldPart]/props/field/anyOf[subschema #1: TaskDetailFieldId]/` response property for the response status `200`
- DELETE /api/v1/c/{community_id}/layouts/{kind} added the new `type` enum value to the `layouts/items/oneOf[subschema #2: DetailLayoutRead]/definition/side/anyOf[subschema #1]/items/oneOf[subschema #1: DetailStackPart]/children/items/oneOf[subschema #2: SectionPart]/children/items/oneOf[subschema #3: DetailFieldPart]/props/field/anyOf[subschema #1: TaskDetailFieldId]/` response property for the response status `200`
- DELETE /api/v1/c/{community_id}/layouts/{kind} added the new `type` enum value to the `layouts/items/oneOf[subschema #2: DetailLayoutRead]/definition/side/anyOf[subschema #1]/items/oneOf[subschema #1: DetailStackPart]/children/items/oneOf[subschema #3: DetailFieldPart]/props/field/anyOf[subschema #1: TaskDetailFieldId]/` response property for the response status `200`
- DELETE /api/v1/c/{community_id}/layouts/{kind} added the new `type` enum value to the `layouts/items/oneOf[subschema #2: DetailLayoutRead]/definition/side/anyOf[subschema #1]/items/oneOf[subschema #2: SectionPart]/children/items/oneOf[subschema #3: DetailFieldPart]/props/field/anyOf[subschema #1: TaskDetailFieldId]/` response property for the response status `200`
- DELETE /api/v1/c/{community_id}/layouts/{kind} added the new `type` enum value to the `layouts/items/oneOf[subschema #2: DetailLayoutRead]/definition/side/anyOf[subschema #1]/items/oneOf[subschema #3: DetailFieldPart]/props/field/anyOf[subschema #1: TaskDetailFieldId]/` response property for the response status `200`
- GET /api/v1/fields/{dataset} added the new `task_type` enum value to the `fields/items/kind` response property for the response status `200`

### Groupings name the field they group by

A list layout's groupings name a field of what it lists (`task_status_id`,
`tag_ids`, `date_group`, `assignee_ids`, …) or `property:<id>`, rather than one
of five ids of their own; migration `20261020_0529` rewrites every stored
layout.

- PUT /api/v1/c/{community_id}/layouts/ removed `#/components/schemas/TaskGroupingId` from the `oneOf[subschema #1: ListLayoutWrite]/definition/group_by` request property `anyOf` list
- PUT /api/v1/c/{community_id}/layouts/ removed `#/components/schemas/TaskGroupingId, subschema #2` from the `oneOf[subschema #1: ListLayoutWrite]/definition/groupings/anyOf[subschema #1]/items/field` request property `anyOf` list
- PUT /api/v1/c/{community_id}/layouts/ the `oneOf[subschema #1: ListLayoutWrite]/definition/groupings/anyOf[subschema #1]/items/field` request property `type` changed from `any` to `string`

### A project draws a Gantt

A project's lists are `table`, `board`, `gantt` and `calendar`, each shown or
hidden (`hidden` on its layout), as shipped every one shown.

- GET /api/v1/c/{community_id}/layouts/ added the new `gantt` enum value to the `layouts/items/oneOf[subschema #1: ListLayoutRead]/kind` response property for the response status `200`
- PUT /api/v1/c/{community_id}/layouts/ added the new `gantt` enum value to the `layouts/items/oneOf[subschema #1: ListLayoutRead]/kind` response property for the response status `200`
- PUT /api/v1/c/{community_id}/layouts/default added the new `gantt` enum value to the `layouts/items/oneOf[subschema #1: ListLayoutRead]/kind` response property for the response status `200`
- GET /api/v1/c/{community_id}/layouts/initiative added the new `gantt` enum value to the `items/layouts/items/oneOf[subschema #1: ListLayoutRead]/kind` response property for the response status `200`
- DELETE /api/v1/c/{community_id}/layouts/{kind} added the new `gantt` enum value to the `layouts/items/oneOf[subschema #1: ListLayoutRead]/kind` response property for the response status `200`

### Members bring no AI key

A connection's key is its owner's, and members configure nothing: the member
key, preference and test routes, the seat's list and revoke of member keys,
and `GET /me/ai` are gone, and a connection no longer carries
`allow_member_keys`.

- GET /api/v1/c/{community_id}/settings/ai/connections removed the required property `items/allow_member_keys` from the response with the `200` status
- POST /api/v1/c/{community_id}/settings/ai/connections removed the required property `allow_member_keys` from the response with the `200` status
- PUT /api/v1/c/{community_id}/settings/ai/connections/{connection_id} removed the required property `allow_member_keys` from the response with the `200` status
- GET /api/v1/c/{community_id}/settings/ai/me api path removed without deprecation
- PUT /api/v1/c/{community_id}/settings/ai/me/key api path removed without deprecation
- DELETE /api/v1/c/{community_id}/settings/ai/me/key/{scope}/{connection_id} api path removed without deprecation
- PUT /api/v1/c/{community_id}/settings/ai/me/pref api path removed without deprecation
- POST /api/v1/c/{community_id}/settings/ai/me/test api path removed without deprecation
- GET /api/v1/c/{community_id}/settings/ai/members/keys api path removed without deprecation
- DELETE /api/v1/c/{community_id}/settings/ai/members/{user_id}/keys/{connection_id} api path removed without deprecation
- GET /api/v1/me/ai api path removed without deprecation
- GET /api/v1/settings/ai/platform/connections removed the required property `items/allow_member_keys` from the response with the `200` status
- POST /api/v1/settings/ai/platform/connections removed the required property `allow_member_keys` from the response with the `200` status
- PUT /api/v1/settings/ai/platform/connections/{connection_id} removed the required property `allow_member_keys` from the response with the `200` status
