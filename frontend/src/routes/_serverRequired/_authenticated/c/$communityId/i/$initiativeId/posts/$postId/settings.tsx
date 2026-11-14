import { createFileRoute } from "@tanstack/react-router";

import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { PostReactionsField } from "@/pages/community/tools/posts/PostReactionsField";
import { SettingsLayout } from "@/pages/community/tools/settings/SettingsLayout";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/posts/$postId/settings"
)({
  component: () => <SettingsLayout tool={Tool.post} detailsInline={<PostReactionsField />} />,
});
