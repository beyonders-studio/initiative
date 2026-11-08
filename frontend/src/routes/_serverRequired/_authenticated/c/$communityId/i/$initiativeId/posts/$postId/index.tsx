import { createFileRoute } from "@tanstack/react-router";

import { PostPage } from "@/pages/community/tools/posts/PostPage";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/posts/$postId/"
)({
  component: PostPage,
});
