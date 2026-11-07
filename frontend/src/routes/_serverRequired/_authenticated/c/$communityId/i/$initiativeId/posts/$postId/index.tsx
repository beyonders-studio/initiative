import { createFileRoute } from "@tanstack/react-router";

import { PostDetailPage } from "@/pages/initiativeTools/posts/PostDetailPage";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/posts/$postId/"
)({
  component: PostDetailPage,
});
