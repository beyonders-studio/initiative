import { createFileRoute } from "@tanstack/react-router";

import { LoginPage } from "@/pages/signIn/login/LoginPage";

export const Route = createFileRoute("/_serverRequired/login")({
  component: LoginPage,
});
