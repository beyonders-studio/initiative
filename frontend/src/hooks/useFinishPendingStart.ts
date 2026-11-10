import { useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { useCallback, useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";

import { type CommunityCategory, Tool } from "@/api/generated/initiativeAPI.schemas";
import { useAuth } from "@/hooks/useAuth";
import { useCommunities } from "@/hooks/useCommunities";
import { communityPath } from "@/lib/communityUrl";
import { nearOfPlace, nearSearchOf, type Place, saveNear } from "@/lib/directoryNear";
import { type FirstHomeContext, seedFirstHome } from "@/lib/home/firstHome";
import { toast } from "@/lib/mascotToast";
import { returnPath } from "@/lib/returnPath";
import {
  clearStart,
  findStartedCommunity,
  readPendingNext,
  readPendingStart,
  type StartAnswers,
  type Starter,
  type StartPath,
  seedStarter,
} from "@/lib/startFlow";
import { toolDetailRoute } from "@/lib/tools";

/** Where a finished start lands: Personal on its list, anything else on the
 *  community's home. */
export const useLandOnStarter = () => {
  const navigate = useNavigate();
  return useCallback(
    async (communityId: number, starter: Starter | null) => {
      await navigate({
        to: communityPath(
          communityId,
          starter?.projectId
            ? toolDetailRoute(Tool.project, starter.initiativeId, starter.projectId)
            : "/"
        ),
      });
    },
    [navigate]
  );
};

/**
 * Make the first home page from why they signed up. Not waited on: nobody
 * lands on Home from the start flow, so it only has to be there by the next
 * visit.
 */
export const useSeedFirstHome = () => {
  const queryClient = useQueryClient();
  return useCallback(
    (path: StartPath, context?: FirstHomeContext) => void seedFirstHome(queryClient, path, context),
    [queryClient]
  );
};

/** What the first home page points at, from what the flow made. */
export const firstHomeContext = (
  communityId: number,
  starter: Starter | null
): FirstHomeContext => ({
  communityId,
  list: starter?.projectId
    ? { communityId, initiativeId: starter.initiativeId, projectId: starter.projectId }
    : null,
});

/** The directory, on the shelves they picked. */
export const useOpenDirectory = () => {
  const navigate = useNavigate();
  const { user } = useAuth();
  // Read when the directory opens, which can be just after the account that
  // is opening it was signed in.
  const userRef = useRef(user);
  userRef.current = user;
  return useCallback(
    (categories: CommunityCategory[], near: Place | null = null) => {
      // Kept for next time too, so the directory keeps opening near them. The
      // address carries it either way.
      if (near) saveNear(near, userRef.current?.id ?? null);
      return navigate({
        to: "/communities",
        search: { ...(categories.length ? { category: categories } : {}), ...nearSearchOf(near) },
      });
    },
    [navigate]
  );
};

/** Make the starter content, saying so if it could not be made. */
export const useSeedStarter = () => {
  const { t } = useTranslation("auth");
  return useCallback(
    async (communityId: number, answers: StartAnswers): Promise<Starter | null> => {
      try {
        return await seedStarter(communityId, answers);
      } catch {
        toast.error(t("start.starterError"));
        return null;
      }
    },
    [t]
  );
};

/**
 * Finish a start that signed up on this browser but could not sign in then,
 * on the first load that is signed in as that account.
 */
export const useFinishPendingStart = (): void => {
  const navigate = useNavigate();
  const { user } = useAuth();
  const { communities, loading, refreshCommunities } = useCommunities();
  const seed = useSeedStarter();
  const landOn = useLandOnStarter();
  const openDirectory = useOpenDirectory();
  const seedHome = useSeedFirstHome();
  const done = useRef(false);
  const refetched = useRef(false);

  useEffect(() => {
    if (done.current || !user?.email || loading) return;
    const answers = readPendingStart(user.email);
    if (!answers) return;
    // The page that sent them to sign up, when one did, is where it lands.
    const next = returnPath(readPendingNext(user.email));
    if (answers.path === "join" || answers.path === "invite") {
      done.current = true;
      seedHome(answers.path);
      void (async () => {
        await clearStart();
        if (next) await navigate({ href: next });
        else if (answers.path === "join" && !user.age_below_minimum_at) {
          await openDirectory(answers.categories, nearOfPlace(answers.near));
        }
      })();
      return;
    }
    // Kept until the new community is in the list; a list read before it
    // existed is read once more.
    const community = findStartedCommunity(communities, answers);
    if (!community) {
      if (!refetched.current) {
        refetched.current = true;
        void refreshCommunities().catch(() => undefined);
      }
      return;
    }
    done.current = true;
    void (async () => {
      await clearStart();
      const starter = await seed(community.id, answers);
      seedHome(answers.path, firstHomeContext(community.id, starter));
      await (next ? navigate({ href: next }) : landOn(community.id, starter));
    })();
  }, [
    user,
    loading,
    communities,
    refreshCommunities,
    seed,
    landOn,
    openDirectory,
    seedHome,
    navigate,
  ]);
};
