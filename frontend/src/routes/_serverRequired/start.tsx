import { createFileRoute } from "@tanstack/react-router";

import { StartPage } from "@/pages/signIn/StartPage";

export interface StartSearch {
  invite_code?: string;
}

export const validateStartSearch = (search: Record<string, unknown>): StartSearch =>
  typeof search.invite_code === "string" && search.invite_code.trim()
    ? { invite_code: search.invite_code.trim() }
    : {};

export const Route = createFileRoute("/_serverRequired/start")({
  validateSearch: validateStartSearch,
  component: StartPage,
});
