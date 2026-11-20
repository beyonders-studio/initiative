# Accepted API breaking changes

`scripts/ci/api-compat` compares this tree's OpenAPI spec with the last
release's and fails on a change that breaks a client written against that
release, unless the change is listed here. Each entry is the method, path and
message the check printed, under a `## After <release>` heading naming the
release it breaks from. Once the next release ships, its entries no longer
matter and can be deleted.

## After 0.79.2

### A universal route takes any kind its community has

The universal routes (archive, trash, comments, tags, links, sharing,
properties, personal items, search, export and tool counts) take and answer a
kind as a string, in place of an enum of the built-in kinds: a community's
tool plug-ins bring kinds of their own. A kind the community does not have is
404 `NOT_FOUND`, where a value outside the enum was 422.

- POST /api/v1/c/{community_id}/archive/{entity_type}/{entity_id} removed the enum value `calendar` from the `path` request parameter `entity_type`
- POST /api/v1/c/{community_id}/archive/{entity_type}/{entity_id} removed the enum value `collection` from the `path` request parameter `entity_type`
- POST /api/v1/c/{community_id}/archive/{entity_type}/{entity_id} removed the enum value `contact` from the `path` request parameter `entity_type`
- POST /api/v1/c/{community_id}/archive/{entity_type}/{entity_id} removed the enum value `counter_group` from the `path` request parameter `entity_type`
- POST /api/v1/c/{community_id}/archive/{entity_type}/{entity_id} removed the enum value `dashboard` from the `path` request parameter `entity_type`
- POST /api/v1/c/{community_id}/archive/{entity_type}/{entity_id} removed the enum value `file` from the `path` request parameter `entity_type`
- POST /api/v1/c/{community_id}/archive/{entity_type}/{entity_id} removed the enum value `initiative` from the `path` request parameter `entity_type`
- POST /api/v1/c/{community_id}/archive/{entity_type}/{entity_id} removed the enum value `post` from the `path` request parameter `entity_type`
- POST /api/v1/c/{community_id}/archive/{entity_type}/{entity_id} removed the enum value `project` from the `path` request parameter `entity_type`
- POST /api/v1/c/{community_id}/archive/{entity_type}/{entity_id} removed the enum value `task` from the `path` request parameter `entity_type`
- POST /api/v1/c/{community_id}/archive/{entity_type}/{entity_id} removed the enum value `wiki` from the `path` request parameter `entity_type`
- GET /api/v1/c/{community_id}/exports/{tool} removed the enum value `calendar` from the `path` request parameter `tool`
- GET /api/v1/c/{community_id}/exports/{tool} removed the enum value `contact` from the `path` request parameter `tool`
- GET /api/v1/c/{community_id}/exports/{tool} removed the enum value `counter_group` from the `path` request parameter `tool`
- GET /api/v1/c/{community_id}/exports/{tool} removed the enum value `dashboard` from the `path` request parameter `tool`
- GET /api/v1/c/{community_id}/exports/{tool} removed the enum value `file` from the `path` request parameter `tool`
- GET /api/v1/c/{community_id}/exports/{tool} removed the enum value `post` from the `path` request parameter `tool`
- GET /api/v1/c/{community_id}/exports/{tool} removed the enum value `project` from the `path` request parameter `tool`
- GET /api/v1/c/{community_id}/exports/{tool} removed the enum value `wiki` from the `path` request parameter `tool`
- DELETE /api/v1/c/{community_id}/personal-items/bookmark/{tool}/{entity_id} removed the enum value `calendar` from the `path` request parameter `tool`
- DELETE /api/v1/c/{community_id}/personal-items/bookmark/{tool}/{entity_id} removed the enum value `contact` from the `path` request parameter `tool`
- DELETE /api/v1/c/{community_id}/personal-items/bookmark/{tool}/{entity_id} removed the enum value `counter_group` from the `path` request parameter `tool`
- DELETE /api/v1/c/{community_id}/personal-items/bookmark/{tool}/{entity_id} removed the enum value `dashboard` from the `path` request parameter `tool`
- DELETE /api/v1/c/{community_id}/personal-items/bookmark/{tool}/{entity_id} removed the enum value `file` from the `path` request parameter `tool`
- DELETE /api/v1/c/{community_id}/personal-items/bookmark/{tool}/{entity_id} removed the enum value `post` from the `path` request parameter `tool`
- DELETE /api/v1/c/{community_id}/personal-items/bookmark/{tool}/{entity_id} removed the enum value `project` from the `path` request parameter `tool`
- DELETE /api/v1/c/{community_id}/personal-items/bookmark/{tool}/{entity_id} removed the enum value `wiki` from the `path` request parameter `tool`
- PUT /api/v1/c/{community_id}/personal-items/bookmark/{tool}/{entity_id} removed the enum value `calendar` from the `path` request parameter `tool`
- PUT /api/v1/c/{community_id}/personal-items/bookmark/{tool}/{entity_id} removed the enum value `contact` from the `path` request parameter `tool`
- PUT /api/v1/c/{community_id}/personal-items/bookmark/{tool}/{entity_id} removed the enum value `counter_group` from the `path` request parameter `tool`
- PUT /api/v1/c/{community_id}/personal-items/bookmark/{tool}/{entity_id} removed the enum value `dashboard` from the `path` request parameter `tool`
- PUT /api/v1/c/{community_id}/personal-items/bookmark/{tool}/{entity_id} removed the enum value `file` from the `path` request parameter `tool`
- PUT /api/v1/c/{community_id}/personal-items/bookmark/{tool}/{entity_id} removed the enum value `post` from the `path` request parameter `tool`
- PUT /api/v1/c/{community_id}/personal-items/bookmark/{tool}/{entity_id} removed the enum value `project` from the `path` request parameter `tool`
- PUT /api/v1/c/{community_id}/personal-items/bookmark/{tool}/{entity_id} removed the enum value `wiki` from the `path` request parameter `tool`
- DELETE /api/v1/c/{community_id}/personal-items/subscribe/{kind}/{entity_id} removed the enum value `calendar_event` from the `path` request parameter `kind`
- DELETE /api/v1/c/{community_id}/personal-items/subscribe/{kind}/{entity_id} removed the enum value `calendar` from the `path` request parameter `kind`
- DELETE /api/v1/c/{community_id}/personal-items/subscribe/{kind}/{entity_id} removed the enum value `collection` from the `path` request parameter `kind`
- DELETE /api/v1/c/{community_id}/personal-items/subscribe/{kind}/{entity_id} removed the enum value `contact` from the `path` request parameter `kind`
- DELETE /api/v1/c/{community_id}/personal-items/subscribe/{kind}/{entity_id} removed the enum value `counter_group` from the `path` request parameter `kind`
- DELETE /api/v1/c/{community_id}/personal-items/subscribe/{kind}/{entity_id} removed the enum value `counter` from the `path` request parameter `kind`
- DELETE /api/v1/c/{community_id}/personal-items/subscribe/{kind}/{entity_id} removed the enum value `dashboard` from the `path` request parameter `kind`
- DELETE /api/v1/c/{community_id}/personal-items/subscribe/{kind}/{entity_id} removed the enum value `file` from the `path` request parameter `kind`
- DELETE /api/v1/c/{community_id}/personal-items/subscribe/{kind}/{entity_id} removed the enum value `post` from the `path` request parameter `kind`
- DELETE /api/v1/c/{community_id}/personal-items/subscribe/{kind}/{entity_id} removed the enum value `project` from the `path` request parameter `kind`
- DELETE /api/v1/c/{community_id}/personal-items/subscribe/{kind}/{entity_id} removed the enum value `task` from the `path` request parameter `kind`
- DELETE /api/v1/c/{community_id}/personal-items/subscribe/{kind}/{entity_id} removed the enum value `wiki_page` from the `path` request parameter `kind`
- DELETE /api/v1/c/{community_id}/personal-items/subscribe/{kind}/{entity_id} removed the enum value `wiki` from the `path` request parameter `kind`
- PUT /api/v1/c/{community_id}/personal-items/subscribe/{kind}/{entity_id} removed the enum value `calendar_event` from the `path` request parameter `kind`
- PUT /api/v1/c/{community_id}/personal-items/subscribe/{kind}/{entity_id} removed the enum value `calendar` from the `path` request parameter `kind`
- PUT /api/v1/c/{community_id}/personal-items/subscribe/{kind}/{entity_id} removed the enum value `collection` from the `path` request parameter `kind`
- PUT /api/v1/c/{community_id}/personal-items/subscribe/{kind}/{entity_id} removed the enum value `contact` from the `path` request parameter `kind`
- PUT /api/v1/c/{community_id}/personal-items/subscribe/{kind}/{entity_id} removed the enum value `counter_group` from the `path` request parameter `kind`
- PUT /api/v1/c/{community_id}/personal-items/subscribe/{kind}/{entity_id} removed the enum value `counter` from the `path` request parameter `kind`
- PUT /api/v1/c/{community_id}/personal-items/subscribe/{kind}/{entity_id} removed the enum value `dashboard` from the `path` request parameter `kind`
- PUT /api/v1/c/{community_id}/personal-items/subscribe/{kind}/{entity_id} removed the enum value `file` from the `path` request parameter `kind`
- PUT /api/v1/c/{community_id}/personal-items/subscribe/{kind}/{entity_id} removed the enum value `post` from the `path` request parameter `kind`
- PUT /api/v1/c/{community_id}/personal-items/subscribe/{kind}/{entity_id} removed the enum value `project` from the `path` request parameter `kind`
- PUT /api/v1/c/{community_id}/personal-items/subscribe/{kind}/{entity_id} removed the enum value `task` from the `path` request parameter `kind`
- PUT /api/v1/c/{community_id}/personal-items/subscribe/{kind}/{entity_id} removed the enum value `wiki_page` from the `path` request parameter `kind`
- PUT /api/v1/c/{community_id}/personal-items/subscribe/{kind}/{entity_id} removed the enum value `wiki` from the `path` request parameter `kind`
- DELETE /api/v1/c/{community_id}/personal-items/view/{kind}/{entity_id} removed the enum value `calendar_event` from the `path` request parameter `kind`
- DELETE /api/v1/c/{community_id}/personal-items/view/{kind}/{entity_id} removed the enum value `calendar` from the `path` request parameter `kind`
- DELETE /api/v1/c/{community_id}/personal-items/view/{kind}/{entity_id} removed the enum value `collection` from the `path` request parameter `kind`
- DELETE /api/v1/c/{community_id}/personal-items/view/{kind}/{entity_id} removed the enum value `contact` from the `path` request parameter `kind`
- DELETE /api/v1/c/{community_id}/personal-items/view/{kind}/{entity_id} removed the enum value `counter_group` from the `path` request parameter `kind`
- DELETE /api/v1/c/{community_id}/personal-items/view/{kind}/{entity_id} removed the enum value `counter` from the `path` request parameter `kind`
- DELETE /api/v1/c/{community_id}/personal-items/view/{kind}/{entity_id} removed the enum value `dashboard` from the `path` request parameter `kind`
- DELETE /api/v1/c/{community_id}/personal-items/view/{kind}/{entity_id} removed the enum value `file` from the `path` request parameter `kind`
- DELETE /api/v1/c/{community_id}/personal-items/view/{kind}/{entity_id} removed the enum value `post` from the `path` request parameter `kind`
- DELETE /api/v1/c/{community_id}/personal-items/view/{kind}/{entity_id} removed the enum value `project` from the `path` request parameter `kind`
- DELETE /api/v1/c/{community_id}/personal-items/view/{kind}/{entity_id} removed the enum value `task` from the `path` request parameter `kind`
- DELETE /api/v1/c/{community_id}/personal-items/view/{kind}/{entity_id} removed the enum value `wiki_page` from the `path` request parameter `kind`
- DELETE /api/v1/c/{community_id}/personal-items/view/{kind}/{entity_id} removed the enum value `wiki` from the `path` request parameter `kind`
- PUT /api/v1/c/{community_id}/personal-items/view/{kind}/{entity_id} removed the enum value `calendar_event` from the `path` request parameter `kind`
- PUT /api/v1/c/{community_id}/personal-items/view/{kind}/{entity_id} removed the enum value `calendar` from the `path` request parameter `kind`
- PUT /api/v1/c/{community_id}/personal-items/view/{kind}/{entity_id} removed the enum value `collection` from the `path` request parameter `kind`
- PUT /api/v1/c/{community_id}/personal-items/view/{kind}/{entity_id} removed the enum value `contact` from the `path` request parameter `kind`
- PUT /api/v1/c/{community_id}/personal-items/view/{kind}/{entity_id} removed the enum value `counter_group` from the `path` request parameter `kind`
- PUT /api/v1/c/{community_id}/personal-items/view/{kind}/{entity_id} removed the enum value `counter` from the `path` request parameter `kind`
- PUT /api/v1/c/{community_id}/personal-items/view/{kind}/{entity_id} removed the enum value `dashboard` from the `path` request parameter `kind`
- PUT /api/v1/c/{community_id}/personal-items/view/{kind}/{entity_id} removed the enum value `file` from the `path` request parameter `kind`
- PUT /api/v1/c/{community_id}/personal-items/view/{kind}/{entity_id} removed the enum value `post` from the `path` request parameter `kind`
- PUT /api/v1/c/{community_id}/personal-items/view/{kind}/{entity_id} removed the enum value `project` from the `path` request parameter `kind`
- PUT /api/v1/c/{community_id}/personal-items/view/{kind}/{entity_id} removed the enum value `task` from the `path` request parameter `kind`
- PUT /api/v1/c/{community_id}/personal-items/view/{kind}/{entity_id} removed the enum value `wiki_page` from the `path` request parameter `kind`
- PUT /api/v1/c/{community_id}/personal-items/view/{kind}/{entity_id} removed the enum value `wiki` from the `path` request parameter `kind`
- GET /api/v1/c/{community_id}/personal-items/{kind}/{entity_id} removed the enum value `calendar_event` from the `path` request parameter `kind`
- GET /api/v1/c/{community_id}/personal-items/{kind}/{entity_id} removed the enum value `calendar` from the `path` request parameter `kind`
- GET /api/v1/c/{community_id}/personal-items/{kind}/{entity_id} removed the enum value `collection` from the `path` request parameter `kind`
- GET /api/v1/c/{community_id}/personal-items/{kind}/{entity_id} removed the enum value `contact` from the `path` request parameter `kind`
- GET /api/v1/c/{community_id}/personal-items/{kind}/{entity_id} removed the enum value `counter_group` from the `path` request parameter `kind`
- GET /api/v1/c/{community_id}/personal-items/{kind}/{entity_id} removed the enum value `counter` from the `path` request parameter `kind`
- GET /api/v1/c/{community_id}/personal-items/{kind}/{entity_id} removed the enum value `dashboard` from the `path` request parameter `kind`
- GET /api/v1/c/{community_id}/personal-items/{kind}/{entity_id} removed the enum value `file` from the `path` request parameter `kind`
- GET /api/v1/c/{community_id}/personal-items/{kind}/{entity_id} removed the enum value `post` from the `path` request parameter `kind`
- GET /api/v1/c/{community_id}/personal-items/{kind}/{entity_id} removed the enum value `project` from the `path` request parameter `kind`
- GET /api/v1/c/{community_id}/personal-items/{kind}/{entity_id} removed the enum value `task` from the `path` request parameter `kind`
- GET /api/v1/c/{community_id}/personal-items/{kind}/{entity_id} removed the enum value `wiki_page` from the `path` request parameter `kind`
- GET /api/v1/c/{community_id}/personal-items/{kind}/{entity_id} removed the enum value `wiki` from the `path` request parameter `kind`
- PUT /api/v1/c/{community_id}/properties/{target}/{entity_id} removed the enum value `calendar_event` from the `path` request parameter `target`
- PUT /api/v1/c/{community_id}/properties/{target}/{entity_id} removed the enum value `calendar` from the `path` request parameter `target`
- PUT /api/v1/c/{community_id}/properties/{target}/{entity_id} removed the enum value `collection` from the `path` request parameter `target`
- PUT /api/v1/c/{community_id}/properties/{target}/{entity_id} removed the enum value `contact` from the `path` request parameter `target`
- PUT /api/v1/c/{community_id}/properties/{target}/{entity_id} removed the enum value `counter_group` from the `path` request parameter `target`
- PUT /api/v1/c/{community_id}/properties/{target}/{entity_id} removed the enum value `counter` from the `path` request parameter `target`
- PUT /api/v1/c/{community_id}/properties/{target}/{entity_id} removed the enum value `dashboard` from the `path` request parameter `target`
- PUT /api/v1/c/{community_id}/properties/{target}/{entity_id} removed the enum value `file` from the `path` request parameter `target`
- PUT /api/v1/c/{community_id}/properties/{target}/{entity_id} removed the enum value `post` from the `path` request parameter `target`
- PUT /api/v1/c/{community_id}/properties/{target}/{entity_id} removed the enum value `project` from the `path` request parameter `target`
- PUT /api/v1/c/{community_id}/properties/{target}/{entity_id} removed the enum value `task` from the `path` request parameter `target`
- PUT /api/v1/c/{community_id}/properties/{target}/{entity_id} removed the enum value `wiki_page` from the `path` request parameter `target`
- PUT /api/v1/c/{community_id}/properties/{target}/{entity_id} removed the enum value `wiki` from the `path` request parameter `target`
- GET /api/v1/c/{community_id}/relationships/ added `subschema #1` to the `items/other/tool` response property `anyOf` list for the response status `200`
- POST /api/v1/c/{community_id}/relationships/ added `subschema #1` to the `other/tool` response property `anyOf` list for the response status `201`
- POST /api/v1/c/{community_id}/relationships/ removed the enum value `calendar_event` of the request property `source/type`
- POST /api/v1/c/{community_id}/relationships/ removed the enum value `calendar_event` of the request property `target/type`
- POST /api/v1/c/{community_id}/relationships/ removed the enum value `calendar` of the request property `source/type`
- POST /api/v1/c/{community_id}/relationships/ removed the enum value `calendar` of the request property `target/type`
- POST /api/v1/c/{community_id}/relationships/ removed the enum value `collection` of the request property `source/type`
- POST /api/v1/c/{community_id}/relationships/ removed the enum value `collection` of the request property `target/type`
- POST /api/v1/c/{community_id}/relationships/ removed the enum value `contact` of the request property `source/type`
- POST /api/v1/c/{community_id}/relationships/ removed the enum value `contact` of the request property `target/type`
- POST /api/v1/c/{community_id}/relationships/ removed the enum value `counter_group` of the request property `source/type`
- POST /api/v1/c/{community_id}/relationships/ removed the enum value `counter_group` of the request property `target/type`
- POST /api/v1/c/{community_id}/relationships/ removed the enum value `counter` of the request property `source/type`
- POST /api/v1/c/{community_id}/relationships/ removed the enum value `counter` of the request property `target/type`
- POST /api/v1/c/{community_id}/relationships/ removed the enum value `dashboard` of the request property `source/type`
- POST /api/v1/c/{community_id}/relationships/ removed the enum value `dashboard` of the request property `target/type`
- POST /api/v1/c/{community_id}/relationships/ removed the enum value `file` of the request property `source/type`
- POST /api/v1/c/{community_id}/relationships/ removed the enum value `file` of the request property `target/type`
- POST /api/v1/c/{community_id}/relationships/ removed the enum value `post` of the request property `source/type`
- POST /api/v1/c/{community_id}/relationships/ removed the enum value `post` of the request property `target/type`
- POST /api/v1/c/{community_id}/relationships/ removed the enum value `project` of the request property `source/type`
- POST /api/v1/c/{community_id}/relationships/ removed the enum value `project` of the request property `target/type`
- POST /api/v1/c/{community_id}/relationships/ removed the enum value `tag` of the request property `source/type`
- POST /api/v1/c/{community_id}/relationships/ removed the enum value `tag` of the request property `target/type`
- POST /api/v1/c/{community_id}/relationships/ removed the enum value `task` of the request property `source/type`
- POST /api/v1/c/{community_id}/relationships/ removed the enum value `task` of the request property `target/type`
- POST /api/v1/c/{community_id}/relationships/ removed the enum value `user` of the request property `source/type`
- POST /api/v1/c/{community_id}/relationships/ removed the enum value `user` of the request property `target/type`
- POST /api/v1/c/{community_id}/relationships/ removed the enum value `wiki_page` of the request property `source/type`
- POST /api/v1/c/{community_id}/relationships/ removed the enum value `wiki_page` of the request property `target/type`
- POST /api/v1/c/{community_id}/relationships/ removed the enum value `wiki` of the request property `source/type`
- POST /api/v1/c/{community_id}/relationships/ removed the enum value `wiki` of the request property `target/type`
- PUT /api/v1/c/{community_id}/relationships/ added `subschema #1` to the `items/other/tool` response property `anyOf` list for the response status `200`
- PUT /api/v1/c/{community_id}/relationships/ removed the enum value `calendar_event` from the `query` request parameter `other_type`
- PUT /api/v1/c/{community_id}/relationships/ removed the enum value `calendar` from the `query` request parameter `other_type`
- PUT /api/v1/c/{community_id}/relationships/ removed the enum value `collection` from the `query` request parameter `other_type`
- PUT /api/v1/c/{community_id}/relationships/ removed the enum value `contact` from the `query` request parameter `other_type`
- PUT /api/v1/c/{community_id}/relationships/ removed the enum value `counter_group` from the `query` request parameter `other_type`
- PUT /api/v1/c/{community_id}/relationships/ removed the enum value `counter` from the `query` request parameter `other_type`
- PUT /api/v1/c/{community_id}/relationships/ removed the enum value `dashboard` from the `query` request parameter `other_type`
- PUT /api/v1/c/{community_id}/relationships/ removed the enum value `file` from the `query` request parameter `other_type`
- PUT /api/v1/c/{community_id}/relationships/ removed the enum value `post` from the `query` request parameter `other_type`
- PUT /api/v1/c/{community_id}/relationships/ removed the enum value `project` from the `query` request parameter `other_type`
- PUT /api/v1/c/{community_id}/relationships/ removed the enum value `tag` from the `query` request parameter `other_type`
- PUT /api/v1/c/{community_id}/relationships/ removed the enum value `task` from the `query` request parameter `other_type`
- PUT /api/v1/c/{community_id}/relationships/ removed the enum value `user` from the `query` request parameter `other_type`
- PUT /api/v1/c/{community_id}/relationships/ removed the enum value `wiki_page` from the `query` request parameter `other_type`
- PUT /api/v1/c/{community_id}/relationships/ removed the enum value `wiki` from the `query` request parameter `other_type`
- GET /api/v1/c/{community_id}/relationships/neighbourhood added `subschema #1` to the `nodes/items/end/tool` response property `anyOf` list for the response status `200`
- PUT /api/v1/c/{community_id}/resource-grants/bulk removed the enum value `calendar` of the request property `items/items/resource_type`
- PUT /api/v1/c/{community_id}/resource-grants/bulk removed the enum value `contact` of the request property `items/items/resource_type`
- PUT /api/v1/c/{community_id}/resource-grants/bulk removed the enum value `counter_group` of the request property `items/items/resource_type`
- PUT /api/v1/c/{community_id}/resource-grants/bulk removed the enum value `dashboard` of the request property `items/items/resource_type`
- PUT /api/v1/c/{community_id}/resource-grants/bulk removed the enum value `file` of the request property `items/items/resource_type`
- PUT /api/v1/c/{community_id}/resource-grants/bulk removed the enum value `post` of the request property `items/items/resource_type`
- PUT /api/v1/c/{community_id}/resource-grants/bulk removed the enum value `project` of the request property `items/items/resource_type`
- PUT /api/v1/c/{community_id}/resource-grants/bulk removed the enum value `wiki` of the request property `items/items/resource_type`
- GET /api/v1/c/{community_id}/search/ added `subschema #1` to the `items/items/tool` response property `anyOf` list for the response status `200`
- GET /api/v1/c/{community_id}/search/ removed the enum value `calendar_event` from the property `anyOf[subschema #1]/items/` of the `query` request parameter `types`
- GET /api/v1/c/{community_id}/search/ removed the enum value `calendar` from the property `anyOf[subschema #1]/items/` of the `query` request parameter `types`
- GET /api/v1/c/{community_id}/search/ removed the enum value `collection` from the property `anyOf[subschema #1]/items/` of the `query` request parameter `types`
- GET /api/v1/c/{community_id}/search/ removed the enum value `comment` from the property `anyOf[subschema #1]/items/` of the `query` request parameter `types`
- GET /api/v1/c/{community_id}/search/ removed the enum value `contact` from the property `anyOf[subschema #1]/items/` of the `query` request parameter `types`
- GET /api/v1/c/{community_id}/search/ removed the enum value `counter_group` from the property `anyOf[subschema #1]/items/` of the `query` request parameter `types`
- GET /api/v1/c/{community_id}/search/ removed the enum value `counter` from the property `anyOf[subschema #1]/items/` of the `query` request parameter `types`
- GET /api/v1/c/{community_id}/search/ removed the enum value `dashboard` from the property `anyOf[subschema #1]/items/` of the `query` request parameter `types`
- GET /api/v1/c/{community_id}/search/ removed the enum value `file` from the property `anyOf[subschema #1]/items/` of the `query` request parameter `types`
- GET /api/v1/c/{community_id}/search/ removed the enum value `post` from the property `anyOf[subschema #1]/items/` of the `query` request parameter `types`
- GET /api/v1/c/{community_id}/search/ removed the enum value `project` from the property `anyOf[subschema #1]/items/` of the `query` request parameter `types`
- GET /api/v1/c/{community_id}/search/ removed the enum value `tag` from the property `anyOf[subschema #1]/items/` of the `query` request parameter `types`
- GET /api/v1/c/{community_id}/search/ removed the enum value `task` from the property `anyOf[subschema #1]/items/` of the `query` request parameter `types`
- GET /api/v1/c/{community_id}/search/ removed the enum value `wiki_page` from the property `anyOf[subschema #1]/items/` of the `query` request parameter `types`
- GET /api/v1/c/{community_id}/search/ removed the enum value `wiki` from the property `anyOf[subschema #1]/items/` of the `query` request parameter `types`
- GET /api/v1/c/{community_id}/search/recent added `subschema #1` to the `items/tool` response property `anyOf` list for the response status `200`
- GET /api/v1/c/{community_id}/search/recent removed the enum value `calendar_event` from the property `anyOf[subschema #1]/items/` of the `query` request parameter `types`
- GET /api/v1/c/{community_id}/search/recent removed the enum value `calendar` from the property `anyOf[subschema #1]/items/` of the `query` request parameter `types`
- GET /api/v1/c/{community_id}/search/recent removed the enum value `collection` from the property `anyOf[subschema #1]/items/` of the `query` request parameter `types`
- GET /api/v1/c/{community_id}/search/recent removed the enum value `comment` from the property `anyOf[subschema #1]/items/` of the `query` request parameter `types`
- GET /api/v1/c/{community_id}/search/recent removed the enum value `contact` from the property `anyOf[subschema #1]/items/` of the `query` request parameter `types`
- GET /api/v1/c/{community_id}/search/recent removed the enum value `counter_group` from the property `anyOf[subschema #1]/items/` of the `query` request parameter `types`
- GET /api/v1/c/{community_id}/search/recent removed the enum value `counter` from the property `anyOf[subschema #1]/items/` of the `query` request parameter `types`
- GET /api/v1/c/{community_id}/search/recent removed the enum value `dashboard` from the property `anyOf[subschema #1]/items/` of the `query` request parameter `types`
- GET /api/v1/c/{community_id}/search/recent removed the enum value `file` from the property `anyOf[subschema #1]/items/` of the `query` request parameter `types`
- GET /api/v1/c/{community_id}/search/recent removed the enum value `post` from the property `anyOf[subschema #1]/items/` of the `query` request parameter `types`
- GET /api/v1/c/{community_id}/search/recent removed the enum value `project` from the property `anyOf[subschema #1]/items/` of the `query` request parameter `types`
- GET /api/v1/c/{community_id}/search/recent removed the enum value `tag` from the property `anyOf[subschema #1]/items/` of the `query` request parameter `types`
- GET /api/v1/c/{community_id}/search/recent removed the enum value `task` from the property `anyOf[subschema #1]/items/` of the `query` request parameter `types`
- GET /api/v1/c/{community_id}/search/recent removed the enum value `wiki_page` from the property `anyOf[subschema #1]/items/` of the `query` request parameter `types`
- GET /api/v1/c/{community_id}/search/recent removed the enum value `wiki` from the property `anyOf[subschema #1]/items/` of the `query` request parameter `types`
- GET /api/v1/c/{community_id}/search/suggest added `subschema #1` to the `items/tool` response property `anyOf` list for the response status `200`
- GET /api/v1/c/{community_id}/search/suggest removed the enum value `calendar_event` from the property `anyOf[subschema #1]/items/` of the `query` request parameter `types`
- GET /api/v1/c/{community_id}/search/suggest removed the enum value `calendar` from the property `anyOf[subschema #1]/items/` of the `query` request parameter `types`
- GET /api/v1/c/{community_id}/search/suggest removed the enum value `collection` from the property `anyOf[subschema #1]/items/` of the `query` request parameter `types`
- GET /api/v1/c/{community_id}/search/suggest removed the enum value `comment` from the property `anyOf[subschema #1]/items/` of the `query` request parameter `types`
- GET /api/v1/c/{community_id}/search/suggest removed the enum value `contact` from the property `anyOf[subschema #1]/items/` of the `query` request parameter `types`
- GET /api/v1/c/{community_id}/search/suggest removed the enum value `counter_group` from the property `anyOf[subschema #1]/items/` of the `query` request parameter `types`
- GET /api/v1/c/{community_id}/search/suggest removed the enum value `counter` from the property `anyOf[subschema #1]/items/` of the `query` request parameter `types`
- GET /api/v1/c/{community_id}/search/suggest removed the enum value `dashboard` from the property `anyOf[subschema #1]/items/` of the `query` request parameter `types`
- GET /api/v1/c/{community_id}/search/suggest removed the enum value `file` from the property `anyOf[subschema #1]/items/` of the `query` request parameter `types`
- GET /api/v1/c/{community_id}/search/suggest removed the enum value `post` from the property `anyOf[subschema #1]/items/` of the `query` request parameter `types`
- GET /api/v1/c/{community_id}/search/suggest removed the enum value `project` from the property `anyOf[subschema #1]/items/` of the `query` request parameter `types`
- GET /api/v1/c/{community_id}/search/suggest removed the enum value `tag` from the property `anyOf[subschema #1]/items/` of the `query` request parameter `types`
- GET /api/v1/c/{community_id}/search/suggest removed the enum value `task` from the property `anyOf[subschema #1]/items/` of the `query` request parameter `types`
- GET /api/v1/c/{community_id}/search/suggest removed the enum value `wiki_page` from the property `anyOf[subschema #1]/items/` of the `query` request parameter `types`
- GET /api/v1/c/{community_id}/search/suggest removed the enum value `wiki` from the property `anyOf[subschema #1]/items/` of the `query` request parameter `types`
- POST /api/v1/c/{community_id}/tags/bulk removed the enum value `calendar_event` of the request property `target_type`
- POST /api/v1/c/{community_id}/tags/bulk removed the enum value `calendar` of the request property `target_type`
- POST /api/v1/c/{community_id}/tags/bulk removed the enum value `collection` of the request property `target_type`
- POST /api/v1/c/{community_id}/tags/bulk removed the enum value `contact` of the request property `target_type`
- POST /api/v1/c/{community_id}/tags/bulk removed the enum value `counter_group` of the request property `target_type`
- POST /api/v1/c/{community_id}/tags/bulk removed the enum value `dashboard` of the request property `target_type`
- POST /api/v1/c/{community_id}/tags/bulk removed the enum value `file` of the request property `target_type`
- POST /api/v1/c/{community_id}/tags/bulk removed the enum value `post` of the request property `target_type`
- POST /api/v1/c/{community_id}/tags/bulk removed the enum value `project` of the request property `target_type`
- POST /api/v1/c/{community_id}/tags/bulk removed the enum value `task` of the request property `target_type`
- POST /api/v1/c/{community_id}/tags/bulk removed the enum value `wiki_page` of the request property `target_type`
- POST /api/v1/c/{community_id}/tags/bulk removed the enum value `wiki` of the request property `target_type`
- GET /api/v1/c/{community_id}/tags/{tag_id}/entities added `subschema #1` to the `items/items/tool` response property `anyOf` list for the response status `200`
- GET /api/v1/c/{community_id}/tags/{tag_id}/entities removed the enum value `calendar_event` from the `query` request parameter `kind`
- GET /api/v1/c/{community_id}/tags/{tag_id}/entities removed the enum value `calendar` from the `query` request parameter `kind`
- GET /api/v1/c/{community_id}/tags/{tag_id}/entities removed the enum value `collection` from the `query` request parameter `kind`
- GET /api/v1/c/{community_id}/tags/{tag_id}/entities removed the enum value `contact` from the `query` request parameter `kind`
- GET /api/v1/c/{community_id}/tags/{tag_id}/entities removed the enum value `counter_group` from the `query` request parameter `kind`
- GET /api/v1/c/{community_id}/tags/{tag_id}/entities removed the enum value `dashboard` from the `query` request parameter `kind`
- GET /api/v1/c/{community_id}/tags/{tag_id}/entities removed the enum value `file` from the `query` request parameter `kind`
- GET /api/v1/c/{community_id}/tags/{tag_id}/entities removed the enum value `post` from the `query` request parameter `kind`
- GET /api/v1/c/{community_id}/tags/{tag_id}/entities removed the enum value `project` from the `query` request parameter `kind`
- GET /api/v1/c/{community_id}/tags/{tag_id}/entities removed the enum value `task` from the `query` request parameter `kind`
- GET /api/v1/c/{community_id}/tags/{tag_id}/entities removed the enum value `wiki_page` from the `query` request parameter `kind`
- GET /api/v1/c/{community_id}/tags/{tag_id}/entities removed the enum value `wiki` from the `query` request parameter `kind`
- GET /api/v1/c/{community_id}/tools/counts/by-initiative removed 'propertyNames' constraint from the `counts` response property for the status `200`
- GET /api/v1/c/{community_id}/tools/{tool}/counts removed the enum value `calendar` from the `path` request parameter `tool`
- GET /api/v1/c/{community_id}/tools/{tool}/counts removed the enum value `contact` from the `path` request parameter `tool`
- GET /api/v1/c/{community_id}/tools/{tool}/counts removed the enum value `counter_group` from the `path` request parameter `tool`
- GET /api/v1/c/{community_id}/tools/{tool}/counts removed the enum value `dashboard` from the `path` request parameter `tool`
- GET /api/v1/c/{community_id}/tools/{tool}/counts removed the enum value `file` from the `path` request parameter `tool`
- GET /api/v1/c/{community_id}/tools/{tool}/counts removed the enum value `post` from the `path` request parameter `tool`
- GET /api/v1/c/{community_id}/tools/{tool}/counts removed the enum value `project` from the `path` request parameter `tool`
- GET /api/v1/c/{community_id}/tools/{tool}/counts removed the enum value `wiki` from the `path` request parameter `tool`
- PUT /api/v1/c/{community_id}/tools/{tool}/{tool_id}/comments removed the enum value `calendar` from the `path` request parameter `tool`
- PUT /api/v1/c/{community_id}/tools/{tool}/{tool_id}/comments removed the enum value `contact` from the `path` request parameter `tool`
- PUT /api/v1/c/{community_id}/tools/{tool}/{tool_id}/comments removed the enum value `counter_group` from the `path` request parameter `tool`
- PUT /api/v1/c/{community_id}/tools/{tool}/{tool_id}/comments removed the enum value `dashboard` from the `path` request parameter `tool`
- PUT /api/v1/c/{community_id}/tools/{tool}/{tool_id}/comments removed the enum value `file` from the `path` request parameter `tool`
- PUT /api/v1/c/{community_id}/tools/{tool}/{tool_id}/comments removed the enum value `post` from the `path` request parameter `tool`
- PUT /api/v1/c/{community_id}/tools/{tool}/{tool_id}/comments removed the enum value `project` from the `path` request parameter `tool`
- PUT /api/v1/c/{community_id}/tools/{tool}/{tool_id}/comments removed the enum value `wiki` from the `path` request parameter `tool`
- PUT /api/v1/c/{community_id}/tools/{tool}/{tool_id}/tags removed the enum value `calendar` from the `path` request parameter `tool`
- PUT /api/v1/c/{community_id}/tools/{tool}/{tool_id}/tags removed the enum value `contact` from the `path` request parameter `tool`
- PUT /api/v1/c/{community_id}/tools/{tool}/{tool_id}/tags removed the enum value `counter_group` from the `path` request parameter `tool`
- PUT /api/v1/c/{community_id}/tools/{tool}/{tool_id}/tags removed the enum value `dashboard` from the `path` request parameter `tool`
- PUT /api/v1/c/{community_id}/tools/{tool}/{tool_id}/tags removed the enum value `file` from the `path` request parameter `tool`
- PUT /api/v1/c/{community_id}/tools/{tool}/{tool_id}/tags removed the enum value `post` from the `path` request parameter `tool`
- PUT /api/v1/c/{community_id}/tools/{tool}/{tool_id}/tags removed the enum value `project` from the `path` request parameter `tool`
- PUT /api/v1/c/{community_id}/tools/{tool}/{tool_id}/tags removed the enum value `wiki` from the `path` request parameter `tool`
- DELETE /api/v1/c/{community_id}/trash/{entity_type}/{entity_id}/purge removed the enum value `calendar_event` from the `path` request parameter `entity_type`
- DELETE /api/v1/c/{community_id}/trash/{entity_type}/{entity_id}/purge removed the enum value `calendar` from the `path` request parameter `entity_type`
- DELETE /api/v1/c/{community_id}/trash/{entity_type}/{entity_id}/purge removed the enum value `collection` from the `path` request parameter `entity_type`
- DELETE /api/v1/c/{community_id}/trash/{entity_type}/{entity_id}/purge removed the enum value `comment` from the `path` request parameter `entity_type`
- DELETE /api/v1/c/{community_id}/trash/{entity_type}/{entity_id}/purge removed the enum value `contact` from the `path` request parameter `entity_type`
- DELETE /api/v1/c/{community_id}/trash/{entity_type}/{entity_id}/purge removed the enum value `counter_group` from the `path` request parameter `entity_type`
- DELETE /api/v1/c/{community_id}/trash/{entity_type}/{entity_id}/purge removed the enum value `counter` from the `path` request parameter `entity_type`
- DELETE /api/v1/c/{community_id}/trash/{entity_type}/{entity_id}/purge removed the enum value `dashboard` from the `path` request parameter `entity_type`
- DELETE /api/v1/c/{community_id}/trash/{entity_type}/{entity_id}/purge removed the enum value `file` from the `path` request parameter `entity_type`
- DELETE /api/v1/c/{community_id}/trash/{entity_type}/{entity_id}/purge removed the enum value `initiative` from the `path` request parameter `entity_type`
- DELETE /api/v1/c/{community_id}/trash/{entity_type}/{entity_id}/purge removed the enum value `post` from the `path` request parameter `entity_type`
- DELETE /api/v1/c/{community_id}/trash/{entity_type}/{entity_id}/purge removed the enum value `project` from the `path` request parameter `entity_type`
- DELETE /api/v1/c/{community_id}/trash/{entity_type}/{entity_id}/purge removed the enum value `tag` from the `path` request parameter `entity_type`
- DELETE /api/v1/c/{community_id}/trash/{entity_type}/{entity_id}/purge removed the enum value `task` from the `path` request parameter `entity_type`
- DELETE /api/v1/c/{community_id}/trash/{entity_type}/{entity_id}/purge removed the enum value `wiki_page` from the `path` request parameter `entity_type`
- DELETE /api/v1/c/{community_id}/trash/{entity_type}/{entity_id}/purge removed the enum value `wiki` from the `path` request parameter `entity_type`
- POST /api/v1/c/{community_id}/trash/{entity_type}/{entity_id}/restore removed the enum value `calendar_event` from the `path` request parameter `entity_type`
- POST /api/v1/c/{community_id}/trash/{entity_type}/{entity_id}/restore removed the enum value `calendar` from the `path` request parameter `entity_type`
- POST /api/v1/c/{community_id}/trash/{entity_type}/{entity_id}/restore removed the enum value `collection` from the `path` request parameter `entity_type`
- POST /api/v1/c/{community_id}/trash/{entity_type}/{entity_id}/restore removed the enum value `comment` from the `path` request parameter `entity_type`
- POST /api/v1/c/{community_id}/trash/{entity_type}/{entity_id}/restore removed the enum value `contact` from the `path` request parameter `entity_type`
- POST /api/v1/c/{community_id}/trash/{entity_type}/{entity_id}/restore removed the enum value `counter_group` from the `path` request parameter `entity_type`
- POST /api/v1/c/{community_id}/trash/{entity_type}/{entity_id}/restore removed the enum value `counter` from the `path` request parameter `entity_type`
- POST /api/v1/c/{community_id}/trash/{entity_type}/{entity_id}/restore removed the enum value `dashboard` from the `path` request parameter `entity_type`
- POST /api/v1/c/{community_id}/trash/{entity_type}/{entity_id}/restore removed the enum value `file` from the `path` request parameter `entity_type`
- POST /api/v1/c/{community_id}/trash/{entity_type}/{entity_id}/restore removed the enum value `initiative` from the `path` request parameter `entity_type`
- POST /api/v1/c/{community_id}/trash/{entity_type}/{entity_id}/restore removed the enum value `post` from the `path` request parameter `entity_type`
- POST /api/v1/c/{community_id}/trash/{entity_type}/{entity_id}/restore removed the enum value `project` from the `path` request parameter `entity_type`
- POST /api/v1/c/{community_id}/trash/{entity_type}/{entity_id}/restore removed the enum value `tag` from the `path` request parameter `entity_type`
- POST /api/v1/c/{community_id}/trash/{entity_type}/{entity_id}/restore removed the enum value `task` from the `path` request parameter `entity_type`
- POST /api/v1/c/{community_id}/trash/{entity_type}/{entity_id}/restore removed the enum value `wiki_page` from the `path` request parameter `entity_type`
- POST /api/v1/c/{community_id}/trash/{entity_type}/{entity_id}/restore removed the enum value `wiki` from the `path` request parameter `entity_type`
- POST /api/v1/c/{community_id}/unarchive/{entity_type}/{entity_id} removed the enum value `calendar` from the `path` request parameter `entity_type`
- POST /api/v1/c/{community_id}/unarchive/{entity_type}/{entity_id} removed the enum value `collection` from the `path` request parameter `entity_type`
- POST /api/v1/c/{community_id}/unarchive/{entity_type}/{entity_id} removed the enum value `contact` from the `path` request parameter `entity_type`
- POST /api/v1/c/{community_id}/unarchive/{entity_type}/{entity_id} removed the enum value `counter_group` from the `path` request parameter `entity_type`
- POST /api/v1/c/{community_id}/unarchive/{entity_type}/{entity_id} removed the enum value `dashboard` from the `path` request parameter `entity_type`
- POST /api/v1/c/{community_id}/unarchive/{entity_type}/{entity_id} removed the enum value `file` from the `path` request parameter `entity_type`
- POST /api/v1/c/{community_id}/unarchive/{entity_type}/{entity_id} removed the enum value `initiative` from the `path` request parameter `entity_type`
- POST /api/v1/c/{community_id}/unarchive/{entity_type}/{entity_id} removed the enum value `post` from the `path` request parameter `entity_type`
- POST /api/v1/c/{community_id}/unarchive/{entity_type}/{entity_id} removed the enum value `project` from the `path` request parameter `entity_type`
- POST /api/v1/c/{community_id}/unarchive/{entity_type}/{entity_id} removed the enum value `task` from the `path` request parameter `entity_type`
- POST /api/v1/c/{community_id}/unarchive/{entity_type}/{entity_id} removed the enum value `wiki` from the `path` request parameter `entity_type`

### A guest invite names any tool's row

The item a guest invite gives is a row of any of the community's tools, a
tool plug-in's among them, named by its kind as a string in place of the
`Tool` enum. A kind the community does not have is 404
`GUEST_GRANT_NOT_FOUND`, as a row it does not have was.

- GET /api/v1/communities/{community_id}/invites added `subschema #1` to the `items/grants/items/resource_type` response property `anyOf` list for the response status `200`
- POST /api/v1/communities/{community_id}/invites removed `#/components/schemas/Tool` from the `grants/items/resource_type` request property `anyOf` list
- POST /api/v1/communities/{community_id}/invites added `subschema #1` to the `grants/items/resource_type` response property `anyOf` list for the response status `201`

### An initiative's tool switches are one map

Each initiative's switch for each tool is a rule of the initiative's, read and
written as one `tools` map, `{tool: on}`, in place of a `<plural>_enabled`
field per tool: an initiative reads `tools`, and creating or changing one takes
`tools` with the tools it names.

- GET /api/v1/c/{community_id}/initiatives/ removed the required property `items/calendars_enabled` from the response with the `200` status
- GET /api/v1/c/{community_id}/initiatives/ removed the required property `items/contacts_enabled` from the response with the `200` status
- GET /api/v1/c/{community_id}/initiatives/ removed the required property `items/counter_groups_enabled` from the response with the `200` status
- GET /api/v1/c/{community_id}/initiatives/ removed the required property `items/dashboards_enabled` from the response with the `200` status
- GET /api/v1/c/{community_id}/initiatives/ removed the required property `items/files_enabled` from the response with the `200` status
- GET /api/v1/c/{community_id}/initiatives/ removed the required property `items/posts_enabled` from the response with the `200` status
- GET /api/v1/c/{community_id}/initiatives/ removed the required property `items/projects_enabled` from the response with the `200` status
- GET /api/v1/c/{community_id}/initiatives/ removed the required property `items/wikis_enabled` from the response with the `200` status
- GET /api/v1/c/{community_id}/initiatives/{initiative_id} removed the required property `calendars_enabled` from the response with the `200` status
- GET /api/v1/c/{community_id}/initiatives/{initiative_id} removed the required property `contacts_enabled` from the response with the `200` status
- GET /api/v1/c/{community_id}/initiatives/{initiative_id} removed the required property `counter_groups_enabled` from the response with the `200` status
- GET /api/v1/c/{community_id}/initiatives/{initiative_id} removed the required property `dashboards_enabled` from the response with the `200` status
- GET /api/v1/c/{community_id}/initiatives/{initiative_id} removed the required property `files_enabled` from the response with the `200` status
- GET /api/v1/c/{community_id}/initiatives/{initiative_id} removed the required property `posts_enabled` from the response with the `200` status
- GET /api/v1/c/{community_id}/initiatives/{initiative_id} removed the required property `projects_enabled` from the response with the `200` status
- GET /api/v1/c/{community_id}/initiatives/{initiative_id} removed the required property `wikis_enabled` from the response with the `200` status
- PATCH /api/v1/c/{community_id}/initiatives/{initiative_id} removed the required property `calendars_enabled` from the response with the `200` status
- PATCH /api/v1/c/{community_id}/initiatives/{initiative_id} removed the required property `contacts_enabled` from the response with the `200` status
- PATCH /api/v1/c/{community_id}/initiatives/{initiative_id} removed the required property `counter_groups_enabled` from the response with the `200` status
- PATCH /api/v1/c/{community_id}/initiatives/{initiative_id} removed the required property `dashboards_enabled` from the response with the `200` status
- PATCH /api/v1/c/{community_id}/initiatives/{initiative_id} removed the required property `files_enabled` from the response with the `200` status
- PATCH /api/v1/c/{community_id}/initiatives/{initiative_id} removed the required property `posts_enabled` from the response with the `200` status
- PATCH /api/v1/c/{community_id}/initiatives/{initiative_id} removed the required property `projects_enabled` from the response with the `200` status
- PATCH /api/v1/c/{community_id}/initiatives/{initiative_id} removed the required property `wikis_enabled` from the response with the `200` status
- PATCH /api/v1/c/{community_id}/initiatives/{initiative_id}/members/{user_id} removed the required property `calendars_enabled` from the response with the `200` status
- PATCH /api/v1/c/{community_id}/initiatives/{initiative_id}/members/{user_id} removed the required property `contacts_enabled` from the response with the `200` status
- PATCH /api/v1/c/{community_id}/initiatives/{initiative_id}/members/{user_id} removed the required property `counter_groups_enabled` from the response with the `200` status
- PATCH /api/v1/c/{community_id}/initiatives/{initiative_id}/members/{user_id} removed the required property `dashboards_enabled` from the response with the `200` status
- PATCH /api/v1/c/{community_id}/initiatives/{initiative_id}/members/{user_id} removed the required property `files_enabled` from the response with the `200` status
- PATCH /api/v1/c/{community_id}/initiatives/{initiative_id}/members/{user_id} removed the required property `posts_enabled` from the response with the `200` status
- PATCH /api/v1/c/{community_id}/initiatives/{initiative_id}/members/{user_id} removed the required property `projects_enabled` from the response with the `200` status
- PATCH /api/v1/c/{community_id}/initiatives/{initiative_id}/members/{user_id} removed the required property `wikis_enabled` from the response with the `200` status
- POST /api/v1/c/{community_id}/initiatives/ removed the required property `calendars_enabled` from the response with the `201` status
- POST /api/v1/c/{community_id}/initiatives/ removed the required property `contacts_enabled` from the response with the `201` status
- POST /api/v1/c/{community_id}/initiatives/ removed the required property `counter_groups_enabled` from the response with the `201` status
- POST /api/v1/c/{community_id}/initiatives/ removed the required property `dashboards_enabled` from the response with the `201` status
- POST /api/v1/c/{community_id}/initiatives/ removed the required property `files_enabled` from the response with the `201` status
- POST /api/v1/c/{community_id}/initiatives/ removed the required property `posts_enabled` from the response with the `201` status
- POST /api/v1/c/{community_id}/initiatives/ removed the required property `projects_enabled` from the response with the `201` status
- POST /api/v1/c/{community_id}/initiatives/ removed the required property `wikis_enabled` from the response with the `201` status
- POST /api/v1/c/{community_id}/initiatives/{initiative_id}/join removed the required property `calendars_enabled` from the response with the `200` status
- POST /api/v1/c/{community_id}/initiatives/{initiative_id}/join removed the required property `contacts_enabled` from the response with the `200` status
- POST /api/v1/c/{community_id}/initiatives/{initiative_id}/join removed the required property `counter_groups_enabled` from the response with the `200` status
- POST /api/v1/c/{community_id}/initiatives/{initiative_id}/join removed the required property `dashboards_enabled` from the response with the `200` status
- POST /api/v1/c/{community_id}/initiatives/{initiative_id}/join removed the required property `files_enabled` from the response with the `200` status
- POST /api/v1/c/{community_id}/initiatives/{initiative_id}/join removed the required property `posts_enabled` from the response with the `200` status
- POST /api/v1/c/{community_id}/initiatives/{initiative_id}/join removed the required property `projects_enabled` from the response with the `200` status
- POST /api/v1/c/{community_id}/initiatives/{initiative_id}/join removed the required property `wikis_enabled` from the response with the `200` status
- POST /api/v1/c/{community_id}/initiatives/{initiative_id}/members removed the required property `calendars_enabled` from the response with the `200` status
- POST /api/v1/c/{community_id}/initiatives/{initiative_id}/members removed the required property `contacts_enabled` from the response with the `200` status
- POST /api/v1/c/{community_id}/initiatives/{initiative_id}/members removed the required property `counter_groups_enabled` from the response with the `200` status
- POST /api/v1/c/{community_id}/initiatives/{initiative_id}/members removed the required property `dashboards_enabled` from the response with the `200` status
- POST /api/v1/c/{community_id}/initiatives/{initiative_id}/members removed the required property `files_enabled` from the response with the `200` status
- POST /api/v1/c/{community_id}/initiatives/{initiative_id}/members removed the required property `posts_enabled` from the response with the `200` status
- POST /api/v1/c/{community_id}/initiatives/{initiative_id}/members removed the required property `projects_enabled` from the response with the `200` status
- POST /api/v1/c/{community_id}/initiatives/{initiative_id}/members removed the required property `wikis_enabled` from the response with the `200` status

### A comment is said on its subject

A comment names what it is said on as `subject_type` and `subject_id` in
place of eleven `<kind>_id` fields: the thread is listed by them, a comment is
posted with them, and every comment read carries them.

- GET /api/v1/c/{community_id}/comments/ added the new required `query` request parameter `subject_id`
- GET /api/v1/c/{community_id}/comments/ added the new required `query` request parameter `subject_type`
- GET /api/v1/c/{community_id}/comments/ removed the required property `comments/items/calendar_id` from the response with the `200` status
- GET /api/v1/c/{community_id}/comments/ removed the required property `comments/items/collection_id` from the response with the `200` status
- GET /api/v1/c/{community_id}/comments/ removed the required property `comments/items/contact_id` from the response with the `200` status
- GET /api/v1/c/{community_id}/comments/ removed the required property `comments/items/counter_group_id` from the response with the `200` status
- GET /api/v1/c/{community_id}/comments/ removed the required property `comments/items/dashboard_id` from the response with the `200` status
- GET /api/v1/c/{community_id}/comments/ removed the required property `comments/items/file_id` from the response with the `200` status
- GET /api/v1/c/{community_id}/comments/ removed the required property `comments/items/post_id` from the response with the `200` status
- GET /api/v1/c/{community_id}/comments/ removed the required property `comments/items/project_id` from the response with the `200` status
- GET /api/v1/c/{community_id}/comments/ removed the required property `comments/items/task_id` from the response with the `200` status
- GET /api/v1/c/{community_id}/comments/ removed the required property `comments/items/wiki_id` from the response with the `200` status
- GET /api/v1/c/{community_id}/comments/ removed the required property `comments/items/wiki_page_id` from the response with the `200` status
- POST /api/v1/c/{community_id}/comments/ added the new required request property `subject_id`
- POST /api/v1/c/{community_id}/comments/ added the new required request property `subject_type`
- POST /api/v1/c/{community_id}/comments/ removed the required property `calendar_id` from the response with the `201` status
- POST /api/v1/c/{community_id}/comments/ removed the required property `collection_id` from the response with the `201` status
- POST /api/v1/c/{community_id}/comments/ removed the required property `contact_id` from the response with the `201` status
- POST /api/v1/c/{community_id}/comments/ removed the required property `counter_group_id` from the response with the `201` status
- POST /api/v1/c/{community_id}/comments/ removed the required property `dashboard_id` from the response with the `201` status
- POST /api/v1/c/{community_id}/comments/ removed the required property `file_id` from the response with the `201` status
- POST /api/v1/c/{community_id}/comments/ removed the required property `post_id` from the response with the `201` status
- POST /api/v1/c/{community_id}/comments/ removed the required property `project_id` from the response with the `201` status
- POST /api/v1/c/{community_id}/comments/ removed the required property `task_id` from the response with the `201` status
- POST /api/v1/c/{community_id}/comments/ removed the required property `wiki_id` from the response with the `201` status
- POST /api/v1/c/{community_id}/comments/ removed the required property `wiki_page_id` from the response with the `201` status
- GET /api/v1/c/{community_id}/comments/{comment_id} removed the required property `calendar_id` from the response with the `200` status
- GET /api/v1/c/{community_id}/comments/{comment_id} removed the required property `collection_id` from the response with the `200` status
- GET /api/v1/c/{community_id}/comments/{comment_id} removed the required property `contact_id` from the response with the `200` status
- GET /api/v1/c/{community_id}/comments/{comment_id} removed the required property `counter_group_id` from the response with the `200` status
- GET /api/v1/c/{community_id}/comments/{comment_id} removed the required property `dashboard_id` from the response with the `200` status
- GET /api/v1/c/{community_id}/comments/{comment_id} removed the required property `file_id` from the response with the `200` status
- GET /api/v1/c/{community_id}/comments/{comment_id} removed the required property `post_id` from the response with the `200` status
- GET /api/v1/c/{community_id}/comments/{comment_id} removed the required property `project_id` from the response with the `200` status
- GET /api/v1/c/{community_id}/comments/{comment_id} removed the required property `task_id` from the response with the `200` status
- GET /api/v1/c/{community_id}/comments/{comment_id} removed the required property `wiki_id` from the response with the `200` status
- GET /api/v1/c/{community_id}/comments/{comment_id} removed the required property `wiki_page_id` from the response with the `200` status
- PATCH /api/v1/c/{community_id}/comments/{comment_id} removed the required property `calendar_id` from the response with the `200` status
- PATCH /api/v1/c/{community_id}/comments/{comment_id} removed the required property `collection_id` from the response with the `200` status
- PATCH /api/v1/c/{community_id}/comments/{comment_id} removed the required property `contact_id` from the response with the `200` status
- PATCH /api/v1/c/{community_id}/comments/{comment_id} removed the required property `counter_group_id` from the response with the `200` status
- PATCH /api/v1/c/{community_id}/comments/{comment_id} removed the required property `dashboard_id` from the response with the `200` status
- PATCH /api/v1/c/{community_id}/comments/{comment_id} removed the required property `file_id` from the response with the `200` status
- PATCH /api/v1/c/{community_id}/comments/{comment_id} removed the required property `post_id` from the response with the `200` status
- PATCH /api/v1/c/{community_id}/comments/{comment_id} removed the required property `project_id` from the response with the `200` status
- PATCH /api/v1/c/{community_id}/comments/{comment_id} removed the required property `task_id` from the response with the `200` status
- PATCH /api/v1/c/{community_id}/comments/{comment_id} removed the required property `wiki_id` from the response with the `200` status
- PATCH /api/v1/c/{community_id}/comments/{comment_id} removed the required property `wiki_page_id` from the response with the `200` status

### The plug-in services list is paged

A deployment may run any number of plug-ins, so the owner's list of plug-in
services is searched and paged on the server: it answers one page, with its
total, and each plug-in is read on its own at
`GET /api/v1/plugin-services/{registration_id}`.

- GET /api/v1/plugin-services/ the response's body `type` changed from `array<object>` to `object` for status `200`

### Sending somebody something

`NotificationType` takes `item_sent`: somebody pointed the reader at a thing,
so every response carrying a notification's type may hold it.

- GET /api/v1/notifications/ added the new `item_sent` enum value to the `notifications/items/type` response property for the response status `200`
- GET /api/v1/notifications/{notification_id}/alert added the new `item_sent` enum value to the `notification/type` response property for the response status `200`
- POST /api/v1/notifications/{notification_id}/read added the new `item_sent` enum value to the `type` response property for the response status `200`
- POST /api/v1/notifications/{notification_id}/unread added the new `item_sent` enum value to the `type` response property for the response status `200`

### A layout draws what a tool plug-in declares

A list's layout can now hold what a tool plug-in's tables are drawn with: a
card's `tint`, an `items` part previewing a row's items, a look read off a
row's select field (`displays: {field: {from}}`), and a preset named in each
language. A layout read back may carry them, and a write takes them where the
tool's table holds the fields they name; every value it took before it still
takes.

- DELETE /api/v1/c/{community_id}/layouts/{kind} added `#/components/schemas/DisplayFrom, subschema #1` to the `layouts/items/oneOf[subschema #1: ListLayoutRead]/definition/displays/anyOf[subschema #1]/additionalProperties/` response property `anyOf` list for the response status `200`
- DELETE /api/v1/c/{community_id}/layouts/{kind} added `#/components/schemas/ItemsPart` to the `layouts/items/oneOf[subschema #1: ListLayoutRead]/definition/card/anyOf[subschema #1: CardPart]/children/items/` response property `oneOf` list for the response status `200`
- DELETE /api/v1/c/{community_id}/layouts/{kind} added `#/components/schemas/ItemsPart` to the `layouts/items/oneOf[subschema #1: ListLayoutRead]/definition/card/anyOf[subschema #1: CardPart]/children/items/oneOf[subschema #2: StackPart]/children/items/` response property `oneOf` list for the response status `200`
- DELETE /api/v1/c/{community_id}/layouts/{kind} response property `layouts/items/oneOf[subschema #1: ListLayoutRead]/definition/presets/anyOf[subschema #1]/items/name` list-of-types was widened by adding types `object` to media type `application/json` of response `200`
- DELETE /api/v1/c/{community_id}/layouts/{kind} the `layouts/items/oneOf[subschema #1: ListLayoutRead]/definition/displays/anyOf[subschema #1]/additionalProperties/` response's property `type` changed from `string` to `any` for status `200`
- GET /api/v1/c/{community_id}/layouts/ added `#/components/schemas/DisplayFrom, subschema #1` to the `layouts/items/oneOf[subschema #1: ListLayoutRead]/definition/displays/anyOf[subschema #1]/additionalProperties/` response property `anyOf` list for the response status `200`
- GET /api/v1/c/{community_id}/layouts/ added `#/components/schemas/ItemsPart` to the `layouts/items/oneOf[subschema #1: ListLayoutRead]/definition/card/anyOf[subschema #1: CardPart]/children/items/` response property `oneOf` list for the response status `200`
- GET /api/v1/c/{community_id}/layouts/ added `#/components/schemas/ItemsPart` to the `layouts/items/oneOf[subschema #1: ListLayoutRead]/definition/card/anyOf[subschema #1: CardPart]/children/items/oneOf[subschema #2: StackPart]/children/items/` response property `oneOf` list for the response status `200`
- GET /api/v1/c/{community_id}/layouts/ response property `layouts/items/oneOf[subschema #1: ListLayoutRead]/definition/presets/anyOf[subschema #1]/items/name` list-of-types was widened by adding types `object` to media type `application/json` of response `200`
- GET /api/v1/c/{community_id}/layouts/ the `layouts/items/oneOf[subschema #1: ListLayoutRead]/definition/displays/anyOf[subschema #1]/additionalProperties/` response's property `type` changed from `string` to `any` for status `200`
- GET /api/v1/c/{community_id}/layouts/initiative added `#/components/schemas/DisplayFrom, subschema #1` to the `items/layouts/items/oneOf[subschema #1: ListLayoutRead]/definition/displays/anyOf[subschema #1]/additionalProperties/` response property `anyOf` list for the response status `200`
- GET /api/v1/c/{community_id}/layouts/initiative added `#/components/schemas/ItemsPart` to the `items/layouts/items/oneOf[subschema #1: ListLayoutRead]/definition/card/anyOf[subschema #1: CardPart]/children/items/` response property `oneOf` list for the response status `200`
- GET /api/v1/c/{community_id}/layouts/initiative added `#/components/schemas/ItemsPart` to the `items/layouts/items/oneOf[subschema #1: ListLayoutRead]/definition/card/anyOf[subschema #1: CardPart]/children/items/oneOf[subschema #2: StackPart]/children/items/` response property `oneOf` list for the response status `200`
- GET /api/v1/c/{community_id}/layouts/initiative response property `items/layouts/items/oneOf[subschema #1: ListLayoutRead]/definition/presets/anyOf[subschema #1]/items/name` list-of-types was widened by adding types `object` to media type `application/json` of response `200`
- GET /api/v1/c/{community_id}/layouts/initiative the `items/layouts/items/oneOf[subschema #1: ListLayoutRead]/definition/displays/anyOf[subschema #1]/additionalProperties/` response's property `type` changed from `string` to `any` for status `200`
- PUT /api/v1/c/{community_id}/layouts/ added `#/components/schemas/DisplayFrom, subschema #1` to the `layouts/items/oneOf[subschema #1: ListLayoutRead]/definition/displays/anyOf[subschema #1]/additionalProperties/` response property `anyOf` list for the response status `200`
- PUT /api/v1/c/{community_id}/layouts/ added `#/components/schemas/ItemsPart` to the `layouts/items/oneOf[subschema #1: ListLayoutRead]/definition/card/anyOf[subschema #1: CardPart]/children/items/` response property `oneOf` list for the response status `200`
- PUT /api/v1/c/{community_id}/layouts/ added `#/components/schemas/ItemsPart` to the `layouts/items/oneOf[subschema #1: ListLayoutRead]/definition/card/anyOf[subschema #1: CardPart]/children/items/oneOf[subschema #2: StackPart]/children/items/` response property `oneOf` list for the response status `200`
- PUT /api/v1/c/{community_id}/layouts/ removed the enum value `bar` of the request property `oneOf[subschema #1: ListLayoutWrite]/definition/displays/anyOf[subschema #1]/additionalProperties/`
- PUT /api/v1/c/{community_id}/layouts/ removed the enum value `clock` of the request property `oneOf[subschema #1: ListLayoutWrite]/definition/displays/anyOf[subschema #1]/additionalProperties/`
- PUT /api/v1/c/{community_id}/layouts/ removed the enum value `number` of the request property `oneOf[subschema #1: ListLayoutWrite]/definition/displays/anyOf[subschema #1]/additionalProperties/`
- PUT /api/v1/c/{community_id}/layouts/ removed the enum value `stars` of the request property `oneOf[subschema #1: ListLayoutWrite]/definition/displays/anyOf[subschema #1]/additionalProperties/`
- PUT /api/v1/c/{community_id}/layouts/ response property `layouts/items/oneOf[subschema #1: ListLayoutRead]/definition/presets/anyOf[subschema #1]/items/name` list-of-types was widened by adding types `object` to media type `application/json` of response `200`
- PUT /api/v1/c/{community_id}/layouts/ the `layouts/items/oneOf[subschema #1: ListLayoutRead]/definition/displays/anyOf[subschema #1]/additionalProperties/` response's property `type` changed from `string` to `any` for status `200`
- PUT /api/v1/c/{community_id}/layouts/default added `#/components/schemas/DisplayFrom, subschema #1` to the `layouts/items/oneOf[subschema #1: ListLayoutRead]/definition/displays/anyOf[subschema #1]/additionalProperties/` response property `anyOf` list for the response status `200`
- PUT /api/v1/c/{community_id}/layouts/default added `#/components/schemas/ItemsPart` to the `layouts/items/oneOf[subschema #1: ListLayoutRead]/definition/card/anyOf[subschema #1: CardPart]/children/items/` response property `oneOf` list for the response status `200`
- PUT /api/v1/c/{community_id}/layouts/default added `#/components/schemas/ItemsPart` to the `layouts/items/oneOf[subschema #1: ListLayoutRead]/definition/card/anyOf[subschema #1: CardPart]/children/items/oneOf[subschema #2: StackPart]/children/items/` response property `oneOf` list for the response status `200`
- PUT /api/v1/c/{community_id}/layouts/default response property `layouts/items/oneOf[subschema #1: ListLayoutRead]/definition/presets/anyOf[subschema #1]/items/name` list-of-types was widened by adding types `object` to media type `application/json` of response `200`
- PUT /api/v1/c/{community_id}/layouts/default the `layouts/items/oneOf[subschema #1: ListLayoutRead]/definition/displays/anyOf[subschema #1]/additionalProperties/` response's property `type` changed from `string` to `any` for status `200`

### The field catalogue is read in a community

A dataset's fields and the query vocabulary are read inside a community, at
`/c/{community_id}/fields/{dataset}` and `/c/{community_id}/query/vocabulary`:
the datasets a statement may name are the community's tool set's, so a tool
plug-in's datasets are offered where it is installed. `dataset` is a string;
one the community does not have is 404 `QUERY_UNKNOWN_RELATION`, where a value
outside the enum was 422.

- GET /api/v1/fields/{dataset} api path removed without deprecation
- GET /api/v1/query/vocabulary api path removed without deprecation

### A plug-in's registration has no installation-sharing switch

Every community that connects the same vendor account holds its route, so a
registration no longer reads or takes `shared_routes`. It reads
`platform_connections` instead: the connections the platform can connect once
for every community.

- GET /api/v1/plugin-services/ removed the required property `items/shared_routes` from the response with the `200` status
- GET /api/v1/plugin-services/{registration_id} removed the required property `shared_routes` from the response with the `200` status
- POST /api/v1/plugin-services/ removed the required property `shared_routes` from the response with the `201` status
- PATCH /api/v1/plugin-services/{registration_id} removed the required property `shared_routes` from the response with the `200` status
- POST /api/v1/plugin-services/{registration_id}/connect removed the required property `shared_routes` from the response with the `200` status
- POST /api/v1/plugin-services/{registration_id}/vendor-setup/complete removed the required property `shared_routes` from the response with the `200` status

### An initiative's tools and role keys name any tool its community has

An initiative's `tools` switches, a role's `permissions` and the community's
initiative defaults (`tools`, `member_permissions`, `own_tools`,
`own_member_permissions`) are keyed by a string in place of the `Tool` and
`PermissionKey` enums: a tool plug-in's tool is switched by its kind and its
role keys are `<kind>:enabled` and `<kind>:create`. A kind or key the
community does not have is 422 `INITIATIVE_TOOL_UNKNOWN`.

- GET /api/v1/c/{community_id}/initiatives/defaults removed 'propertyNames' constraint from the `member_permissions` response property for the status `200`
- GET /api/v1/c/{community_id}/initiatives/defaults removed 'propertyNames' constraint from the `own_member_permissions` response property for the status `200`
- GET /api/v1/c/{community_id}/initiatives/defaults removed 'propertyNames' constraint from the `own_tools` response property for the status `200`
- GET /api/v1/c/{community_id}/initiatives/defaults removed 'propertyNames' constraint from the `tools` response property for the status `200`
- PATCH /api/v1/c/{community_id}/initiatives/defaults removed 'propertyNames' constraint from the `member_permissions` response property for the status `200`
- PATCH /api/v1/c/{community_id}/initiatives/defaults removed 'propertyNames' constraint from the `own_member_permissions` response property for the status `200`
- PATCH /api/v1/c/{community_id}/initiatives/defaults removed 'propertyNames' constraint from the `own_tools` response property for the status `200`
- PATCH /api/v1/c/{community_id}/initiatives/defaults removed 'propertyNames' constraint from the `tools` response property for the status `200`
- GET /api/v1/c/{community_id}/initiatives/{initiative_id}/roles removed 'propertyNames' constraint from the `items/permissions` response property for the status `200`
- POST /api/v1/c/{community_id}/initiatives/{initiative_id}/roles removed 'propertyNames' constraint from the `permissions` response property for the status `201`
- PATCH /api/v1/c/{community_id}/initiatives/{initiative_id}/roles/{role_id} removed 'propertyNames' constraint from the `permissions` response property for the status `200`

## After 0.79.0

### A plug-in is suspended, not switched off

The owner suspends a plug-in everywhere and lifts it: a plug-in service takes
`suspended` and reads `suspended_at` in place of `enabled`. Staff act on each
of a community's plug-ins from its row, which offers `plugins` among its
actions.

- GET /api/v1/plugin-services/ removed the required property `items/enabled` from the response with the `200` status
- POST /api/v1/plugin-services/ removed the required property `enabled` from the response with the `201` status
- PATCH /api/v1/plugin-services/{registration_id} removed the required property `enabled` from the response with the `200` status
- POST /api/v1/plugin-services/{registration_id}/connect removed the required property `enabled` from the response with the `200` status
- POST /api/v1/plugin-services/{registration_id}/vendor-setup/complete removed the required property `enabled` from the response with the `200` status
- GET /api/v1/settings/communities added the new `plugins` enum value to the `items/items/allowed_actions/items/` response property for the response status `200`
- PATCH /api/v1/settings/communities/{community_id} added the new `plugins` enum value to the `allowed_actions/items/` response property for the response status `200`
- POST /api/v1/settings/communities/{community_id}/restore added the new `plugins` enum value to the `allowed_actions/items/` response property for the response status `200`
- POST /api/v1/settings/communities/{community_id}/suspension added the new `plugins` enum value to the `allowed_actions/items/` response property for the response status `200`

### A plug-in says who can use it

Which communities a plug-in reaches comes from its manifest's
`availability`: a plug-in service reads `availability` and
`beta_communities` in place of `operations_only`, and takes
`beta_community_ids` for a beta plug-in.

- GET /api/v1/plugin-services/ removed the required property `items/operations_only` from the response with the `200` status
- POST /api/v1/plugin-services/ removed the required property `operations_only` from the response with the `201` status
- PATCH /api/v1/plugin-services/{registration_id} removed the required property `operations_only` from the response with the `200` status
- POST /api/v1/plugin-services/{registration_id}/connect removed the required property `operations_only` from the response with the `200` status
- POST /api/v1/plugin-services/{registration_id}/vendor-setup/complete removed the required property `operations_only` from the response with the `200` status

## After 0.78.0

### A plug-in answers to the community's roles

Who reaches a plug-in inside an initiative is the initiative's roles' answer,
held as they hold a tool's permissions, so a placement says only where the
plug-in works: the read carries `placed_initiative_ids` in place of
`placements`, and the route that set one placement's roles goes. What the
viewer meets on items is per initiative, as `item_access`, in place of
`item_initiatives`, `item_fields`, `item_parts` and `item_actions`.

- GET /api/v1/c/{community_id}/plugins/ removed the required property `items/items/item_actions` from the response with the `200` status
- GET /api/v1/c/{community_id}/plugins/ removed the required property `items/items/item_fields` from the response with the `200` status
- GET /api/v1/c/{community_id}/plugins/ removed the required property `items/items/item_initiatives` from the response with the `200` status
- GET /api/v1/c/{community_id}/plugins/ removed the required property `items/items/item_parts` from the response with the `200` status
- GET /api/v1/c/{community_id}/plugins/ removed the required property `items/items/placements` from the response with the `200` status
- POST /api/v1/c/{community_id}/plugins/ removed the required property `item_actions` from the response with the `201` status
- POST /api/v1/c/{community_id}/plugins/ removed the required property `item_fields` from the response with the `201` status
- POST /api/v1/c/{community_id}/plugins/ removed the required property `item_initiatives` from the response with the `201` status
- POST /api/v1/c/{community_id}/plugins/ removed the required property `item_parts` from the response with the `201` status
- POST /api/v1/c/{community_id}/plugins/ removed the required property `placements` from the response with the `201` status
- GET /api/v1/c/{community_id}/plugins/{plugin_id} removed the required property `item_actions` from the response with the `200` status
- GET /api/v1/c/{community_id}/plugins/{plugin_id} removed the required property `item_fields` from the response with the `200` status
- GET /api/v1/c/{community_id}/plugins/{plugin_id} removed the required property `item_initiatives` from the response with the `200` status
- GET /api/v1/c/{community_id}/plugins/{plugin_id} removed the required property `item_parts` from the response with the `200` status
- GET /api/v1/c/{community_id}/plugins/{plugin_id} removed the required property `placements` from the response with the `200` status
- PATCH /api/v1/c/{community_id}/plugins/{plugin_id} removed the required property `item_actions` from the response with the `200` status
- PATCH /api/v1/c/{community_id}/plugins/{plugin_id} removed the required property `item_fields` from the response with the `200` status
- PATCH /api/v1/c/{community_id}/plugins/{plugin_id} removed the required property `item_initiatives` from the response with the `200` status
- PATCH /api/v1/c/{community_id}/plugins/{plugin_id} removed the required property `item_parts` from the response with the `200` status
- PATCH /api/v1/c/{community_id}/plugins/{plugin_id} removed the required property `placements` from the response with the `200` status
- PUT /api/v1/c/{community_id}/plugins/{plugin_id}/config removed the required property `item_actions` from the response with the `200` status
- PUT /api/v1/c/{community_id}/plugins/{plugin_id}/config removed the required property `item_fields` from the response with the `200` status
- PUT /api/v1/c/{community_id}/plugins/{plugin_id}/config removed the required property `item_initiatives` from the response with the `200` status
- PUT /api/v1/c/{community_id}/plugins/{plugin_id}/config removed the required property `item_parts` from the response with the `200` status
- PUT /api/v1/c/{community_id}/plugins/{plugin_id}/config removed the required property `placements` from the response with the `200` status
- PUT /api/v1/c/{community_id}/plugins/{plugin_id}/placements/{initiative_id} api path removed without deprecation
- PUT /api/v1/c/{community_id}/plugins/{plugin_id}/scopes removed the required property `item_actions` from the response with the `200` status
- PUT /api/v1/c/{community_id}/plugins/{plugin_id}/scopes removed the required property `item_fields` from the response with the `200` status
- PUT /api/v1/c/{community_id}/plugins/{plugin_id}/scopes removed the required property `item_initiatives` from the response with the `200` status
- PUT /api/v1/c/{community_id}/plugins/{plugin_id}/scopes removed the required property `item_parts` from the response with the `200` status
- PUT /api/v1/c/{community_id}/plugins/{plugin_id}/scopes removed the required property `placements` from the response with the `200` status
- PUT /api/v1/c/{community_id}/plugins/{plugin_id}/settings/{key} removed the required property `item_actions` from the response with the `200` status
- PUT /api/v1/c/{community_id}/plugins/{plugin_id}/settings/{key} removed the required property `item_fields` from the response with the `200` status
- PUT /api/v1/c/{community_id}/plugins/{plugin_id}/settings/{key} removed the required property `item_initiatives` from the response with the `200` status
- PUT /api/v1/c/{community_id}/plugins/{plugin_id}/settings/{key} removed the required property `item_parts` from the response with the `200` status
- PUT /api/v1/c/{community_id}/plugins/{plugin_id}/settings/{key} removed the required property `placements` from the response with the `200` status
- POST /api/v1/c/{community_id}/plugins/{plugin_id}/upgrade removed the required property `item_actions` from the response with the `200` status
- POST /api/v1/c/{community_id}/plugins/{plugin_id}/upgrade removed the required property `item_fields` from the response with the `200` status
- POST /api/v1/c/{community_id}/plugins/{plugin_id}/upgrade removed the required property `item_initiatives` from the response with the `200` status
- POST /api/v1/c/{community_id}/plugins/{plugin_id}/upgrade removed the required property `item_parts` from the response with the `200` status
- POST /api/v1/c/{community_id}/plugins/{plugin_id}/upgrade removed the required property `placements` from the response with the `200` status
- POST /api/v1/c/{community_id}/plugins/{plugin_id}/upgrade/decline removed the required property `item_actions` from the response with the `200` status
- POST /api/v1/c/{community_id}/plugins/{plugin_id}/upgrade/decline removed the required property `item_fields` from the response with the `200` status
- POST /api/v1/c/{community_id}/plugins/{plugin_id}/upgrade/decline removed the required property `item_initiatives` from the response with the `200` status
- POST /api/v1/c/{community_id}/plugins/{plugin_id}/upgrade/decline removed the required property `item_parts` from the response with the `200` status
- POST /api/v1/c/{community_id}/plugins/{plugin_id}/upgrade/decline removed the required property `placements` from the response with the `200` status

### Every message device signs its keys

A device registered before 0.73 signed itself later through its own route;
those that never did are removed, so the route goes and a registration, and
every key it publishes, carries its signature.

- POST /api/v1/me/dm/devices the request property `fallback_key/signature` became required
- POST /api/v1/me/dm/devices the request property `one_time_keys/items/signature` became required
- POST /api/v1/me/dm/devices the request property `signature` became required
- POST /api/v1/me/dm/devices request property `fallback_key/signature` list-of-types was narrowed by removing types `null` from media type `application/json`
- POST /api/v1/me/dm/devices request property `one_time_keys/items/signature` list-of-types was narrowed by removing types `null` from media type `application/json`
- POST /api/v1/me/dm/devices request property `signature` list-of-types was narrowed by removing types `null` from media type `application/json`
- POST /api/v1/me/dm/devices the `fallback_key/signature` request property's maxLength was set to `88`
- POST /api/v1/me/dm/devices the `one_time_keys/items/signature` request property's maxLength was set to `88`
- POST /api/v1/me/dm/devices the `signature` request property's maxLength was set to `88`
- POST /api/v1/me/dm/devices the `fallback_key/signature` request property's minLength was set to `1`
- POST /api/v1/me/dm/devices the `one_time_keys/items/signature` request property's minLength was set to `1`
- POST /api/v1/me/dm/devices the `signature` request property's minLength was set to `1`
- PUT /api/v1/me/dm/devices/{device_id}/signature api path removed without deprecation
- POST /api/v1/me/dm/one-time-keys the request property `one_time_keys/items/signature` became required
- POST /api/v1/me/dm/one-time-keys request property `one_time_keys/items/signature` list-of-types was narrowed by removing types `null` from media type `application/json`
- POST /api/v1/me/dm/one-time-keys the `one_time_keys/items/signature` request property's maxLength was set to `88`
- POST /api/v1/me/dm/one-time-keys the `one_time_keys/items/signature` request property's minLength was set to `1`

### An account's email address as it is stored

The backend's type cleanup reads an account's `email` as the string it is
stored as rather than validating it as an address on the way out, so a read's
`email` no longer carries `format: email`. The operator's user reads say an
account with no address has `null` rather than `""`, as every other read of an
account already does.

- POST /api/v1/auth/register the `email/anyOf[subschema #1]/` response's property `format` changed from `email` to `none` for status `201`
- GET /api/v1/me the `email/anyOf[subschema #1]/` response's property `format` changed from `email` to `none` for status `200`
- PATCH /api/v1/me the `email/anyOf[subschema #1]/` response's property `format` changed from `email` to `none` for status `200`
- POST /api/v1/me/age-confirmation the `email/anyOf[subschema #1]/` response's property `format` changed from `email` to `none` for status `200`
- PUT /api/v1/me/avatar the `email/anyOf[subschema #1]/` response's property `format` changed from `email` to `none` for status `200`
- POST /api/v1/me/legal-acceptance the `email/anyOf[subschema #1]/` response's property `format` changed from `email` to `none` for status `200`
- PATCH /api/v1/me/username the `email/anyOf[subschema #1]/` response's property `format` changed from `email` to `none` for status `200`
- GET /api/v1/operator/users response property `items/items/email` list-of-types was widened by adding types `null` to media type `application/json` of response `200`
- DELETE /api/v1/operator/users/{user_id}/age-block response property `email` list-of-types was widened by adding types `null` to media type `application/json` of response `200`
- DELETE /api/v1/operator/users/{user_id}/api-keys response property `email` list-of-types was widened by adding types `null` to media type `application/json` of response `200`
- PATCH /api/v1/operator/users/{user_id}/platform-role response property `email` list-of-types was widened by adding types `null` to media type `application/json` of response `200`
- DELETE /api/v1/operator/users/{user_id}/profile/{field} response property `email` list-of-types was widened by adding types `null` to media type `application/json` of response `200`
- POST /api/v1/operator/users/{user_id}/reactivate response property `email` list-of-types was widened by adding types `null` to media type `application/json` of response `200`
- POST /api/v1/operator/users/{user_id}/restore response property `email` list-of-types was widened by adding types `null` to media type `application/json` of response `200`
- DELETE /api/v1/operator/users/{user_id}/sessions response property `email` list-of-types was widened by adding types `null` to media type `application/json` of response `200`
- DELETE /api/v1/operator/users/{user_id}/sign-in-lock response property `email` list-of-types was widened by adding types `null` to media type `application/json` of response `200`
- POST /api/v1/operator/users/{user_id}/suspension response property `email` list-of-types was widened by adding types `null` to media type `application/json` of response `200`
- PATCH /api/v1/operator/users/{user_id}/username response property `email` list-of-types was widened by adding types `null` to media type `application/json` of response `200`

### Announcements in notifications

`NotificationType` takes `announcement`: a dismissed announcement leaves a
read line in the reader's notifications, so every response carrying a
notification's type may hold it.

- GET /api/v1/notifications/ added the new `announcement` enum value to the `notifications/items/type` response property for the response status `200`
- GET /api/v1/notifications/{notification_id}/alert added the new `announcement` enum value to the `notification/type` response property for the response status `200`
- POST /api/v1/notifications/{notification_id}/read added the new `announcement` enum value to the `type` response property for the response status `200`
- POST /api/v1/notifications/{notification_id}/unread added the new `announcement` enum value to the `type` response property for the response status `200`

### The Ideas board

`IntakeStream` takes `ideas`: Initiative Cloud's Ideas board is a stream the
team fills by hand, so every response carrying a case's or a binding's stream
may hold it. `NotificationType` takes `idea_updated`: a voter is told when an
idea moves, so every response carrying a notification's type may hold it.

- GET /api/v1/access-grants/cases added the new `ideas` enum value to the `items/items/stream` response property for the response status `200`
- GET /api/v1/c/{community_id}/tasks/{task_id}/case added the new `ideas` enum value to the `stream` response property for the response status `200`
- GET /api/v1/me/tickets added the new `ideas` enum value to the `items/items/stream` response property for the response status `200`
- GET /api/v1/me/tickets/{task_id} added the new `ideas` enum value to the `stream` response property for the response status `200`
- POST /api/v1/me/tickets/{task_id}/replies added the new `ideas` enum value to the `stream` response property for the response status `201`
- GET /api/v1/operator/users/{user_id}/cases added the new `ideas` enum value to the `items/stream` response property for the response status `200`
- GET /api/v1/settings/intake added the new `ideas` enum value to the `bindings/items/stream` response property for the response status `200`
- GET /api/v1/settings/intake added the new `ideas` enum value to the `contact_emails/propertyNames/` response property for the response status `200`
- PUT /api/v1/settings/intake/community added the new `ideas` enum value to the `bindings/items/stream` response property for the response status `200`
- PUT /api/v1/settings/intake/community added the new `ideas` enum value to the `contact_emails/propertyNames/` response property for the response status `200`
- PUT /api/v1/settings/intake/contact added the new `ideas` enum value to the `bindings/items/stream` response property for the response status `200`
- PUT /api/v1/settings/intake/contact added the new `ideas` enum value to the `contact_emails/propertyNames/` response property for the response status `200`
- PUT /api/v1/settings/intake/{stream} added the new `ideas` enum value to the `stream` response property for the response status `200`
- POST /api/v1/settings/intake/{stream}/blueprint added the new `ideas` enum value to the `stream` response property for the response status `200`
- PUT /api/v1/settings/intake/{stream}/contact added the new `ideas` enum value to the `bindings/items/stream` response property for the response status `200`
- PUT /api/v1/settings/intake/{stream}/contact added the new `ideas` enum value to the `contact_emails/propertyNames/` response property for the response status `200`
- GET /api/v1/notifications/ added the new `idea_updated` enum value to the `notifications/items/type` response property for the response status `200`
- GET /api/v1/notifications/{notification_id}/alert added the new `idea_updated` enum value to the `notification/type` response property for the response status `200`
- POST /api/v1/notifications/{notification_id}/read added the new `idea_updated` enum value to the `type` response property for the response status `200`
- POST /api/v1/notifications/{notification_id}/unread added the new `idea_updated` enum value to the `type` response property for the response status `200`

### Feedback to Initiative Cloud

`TicketMode` takes `cloud`: Initiative Cloud takes the stream, and people
send it there, signed in to Cloud, as feedback is from any server. Every
stream's `mode` in the ticket availability may hold it.

- GET /api/v1/me/tickets/availability added the new `cloud` enum value to the `feedback/mode` response property for the response status `200`
- GET /api/v1/me/tickets/availability added the new `cloud` enum value to the `moderation/mode` response property for the response status `200`
- GET /api/v1/me/tickets/availability added the new `cloud` enum value to the `security/mode` response property for the response status `200`
- GET /api/v1/me/tickets/availability added the new `cloud` enum value to the `support/mode` response property for the response status `200`

### Communities that take requests to join

A community's `is_community` becomes `join_policy` (`private`, `request` or
`open`), and `NotificationType` takes the three notices of a request to join a
community, so every response carrying a notification's type may hold them.

- GET /api/v1/communities/ removed the required property `items/is_community` from the response with the `200` status
- POST /api/v1/communities/ removed the required property `is_community` from the response with the `201` status
- POST /api/v1/communities/directory/{community_id}/join removed the required property `is_community` from the response with the `200` status
- POST /api/v1/communities/invite/accept removed the required property `is_community` from the response with the `200` status
- GET /api/v1/communities/{community_id} removed the required property `is_community` from the response with the `200` status
- PATCH /api/v1/communities/{community_id} removed the required property `is_community` from the response with the `200` status
- DELETE /api/v1/communities/{community_id}/banner removed the required property `is_community` from the response with the `200` status
- PUT /api/v1/communities/{community_id}/banner removed the required property `is_community` from the response with the `200` status
- DELETE /api/v1/communities/{community_id}/icon removed the required property `is_community` from the response with the `200` status
- PUT /api/v1/communities/{community_id}/icon removed the required property `is_community` from the response with the `200` status
- GET /api/v1/notifications/ added the new `community_join_approved` enum value to the `notifications/items/type` response property for the response status `200`
- GET /api/v1/notifications/ added the new `community_join_denied` enum value to the `notifications/items/type` response property for the response status `200`
- GET /api/v1/notifications/ added the new `community_join_requested` enum value to the `notifications/items/type` response property for the response status `200`
- GET /api/v1/notifications/{notification_id}/alert added the new `community_join_approved` enum value to the `notification/type` response property for the response status `200`
- GET /api/v1/notifications/{notification_id}/alert added the new `community_join_denied` enum value to the `notification/type` response property for the response status `200`
- GET /api/v1/notifications/{notification_id}/alert added the new `community_join_requested` enum value to the `notification/type` response property for the response status `200`
- POST /api/v1/notifications/{notification_id}/read added the new `community_join_approved` enum value to the `type` response property for the response status `200`
- POST /api/v1/notifications/{notification_id}/read added the new `community_join_denied` enum value to the `type` response property for the response status `200`
- POST /api/v1/notifications/{notification_id}/read added the new `community_join_requested` enum value to the `type` response property for the response status `200`
- POST /api/v1/notifications/{notification_id}/unread added the new `community_join_approved` enum value to the `type` response property for the response status `200`
- POST /api/v1/notifications/{notification_id}/unread added the new `community_join_denied` enum value to the `type` response property for the response status `200`
- POST /api/v1/notifications/{notification_id}/unread added the new `community_join_requested` enum value to the `type` response property for the response status `200`
