import { Link, useLocation, useNavigate, useSearch } from "@tanstack/react-router";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  PluginSignInClientRead,
  PluginSignInPlaceRead,
  ReadSignInClientParams,
} from "@/api/generated/initiativeAPI.schemas";
import {
  useAuthorizeSignIn,
  useReadSignInClient,
  useReadSignInPlaces,
} from "@/api/generated/plugin-platform/plugin-platform";
import { owedAccountStep } from "@/components/account/owedAccountStep";
import { ServerChip } from "@/components/auth/ServerChoice";
import { SignInFrame } from "@/components/auth/SignInFrame";
import { useAuth } from "@/hooks/useAuth";
import { useCommunities } from "@/hooks/useCommunities";
import { getErrorMessage } from "@/lib/errorMessage";
import { Button } from "@/ui/button";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/ui/card";
import { Input } from "@/ui/input";
import { SkeletonRegion } from "@/ui/page-skeletons";
import { Skeleton } from "@/ui/skeleton";

/** The authorize request's parameters, as a plug-in sends them. */
export const SIGN_IN_PARAMS = [
  "client_id",
  "redirect_uri",
  "response_type",
  "scope",
  "state",
  "nonce",
  "code_challenge",
  "code_challenge_method",
] as const;

/** The request's parameters, each as the plug-in sent it. */
export type SignInSearch = Partial<Record<(typeof SIGN_IN_PARAMS)[number], string>>;

/** This page's own address, request and all: where signing in or up returns to. */
const useHere = () => useLocation({ select: (location) => location.href });

/**
 * Sign in with Initiative: a plug-in sent somebody here to sign in and choose
 * where to open it, and they go back with a code.
 *
 * The plug-in and its return address are checked before anything is shown;
 * a request that fails is answered here and never sent back. Signed out, the
 * page offers Initiative's own sign-in and sign-up, which return here. Signed
 * in, it offers the places where the plug-in's page would open inside
 * Initiative; with none, it offers to add the plug-in to a community the
 * person runs, or to start one.
 */
export const PluginSignInPage = () => {
  const { t } = useTranslation(["auth", "common"]);
  const search = useSearch({ strict: false }) as SignInSearch;
  const params: ReadSignInClientParams = Object.fromEntries(
    SIGN_IN_PARAMS.map((name) => [name, search[name] ?? null])
  );
  const { user, loading } = useAuth();
  const clientQuery = useReadSignInClient(params, { query: { retry: false } });
  const client = clientQuery.data;

  // A malformed request from a known plug-in is the plug-in's to hear about.
  useEffect(() => {
    if (client?.refusal_redirect) window.location.replace(client.refusal_redirect);
  }, [client?.refusal_redirect]);

  if (clientQuery.isError) {
    return (
      <Frame title={t("pluginSignIn.unavailableTitle")}>
        <p className="text-center text-muted-foreground text-sm">
          {getErrorMessage(clientQuery.error, "auth:pluginSignIn.unavailable")}
        </p>
      </Frame>
    );
  }
  if (!client || client.refusal_redirect || loading) {
    return (
      <Frame title={t("pluginSignIn.title")}>
        <SkeletonRegion>
          <Skeleton className="h-10 w-full" />
        </SkeletonRegion>
      </Frame>
    );
  }
  if (!user) return <SignedOut client={client} />;
  return owedAccountStep(user) ?? <ChoosePlace client={client} params={params} />;
};

const Frame = ({
  title,
  description,
  children,
  footer,
}: {
  title: string;
  description?: string;
  children: React.ReactNode;
  footer?: React.ReactNode;
}) => (
  <SignInFrame>
    <Card className="w-full max-w-md shadow-lg">
      <CardHeader className="items-center text-center">
        <CardTitle>{title}</CardTitle>
        {description ? <CardDescription>{description}</CardDescription> : null}
      </CardHeader>
      <CardContent className="space-y-3">{children}</CardContent>
      {footer ? <CardFooter className="flex-col gap-2">{footer}</CardFooter> : null}
      <CardFooter>
        <ServerChip />
      </CardFooter>
    </Card>
  </SignInFrame>
);

const Cancel = ({ client }: { client: PluginSignInClientRead }) => {
  const { t } = useTranslation("auth");
  return (
    <Button variant="ghost" className="w-full" asChild>
      <a href={client.cancel_redirect}>{t("pluginSignIn.cancel")}</a>
    </Button>
  );
};

/** Initiative's own sign-in and sign-up, each coming back here. */
const SignedOut = ({ client }: { client: PluginSignInClientRead }) => {
  const { t } = useTranslation("auth");
  const next = useHere();
  return (
    <Frame
      title={t("pluginSignIn.signInTo", { name: client.name })}
      description={t("pluginSignIn.whatItLearns", { name: client.name })}
      footer={<Cancel client={client} />}
    >
      <Button className="w-full" asChild>
        <Link to="/login" search={{ next }}>
          {t("pluginSignIn.signIn")}
        </Link>
      </Button>
      <Button variant="outline" className="w-full" asChild>
        <Link to="/start" search={{ next }}>
          {t("pluginSignIn.createAccount")}
        </Link>
      </Button>
    </Frame>
  );
};

const ChoosePlace = ({
  client,
  params,
}: {
  client: PluginSignInClientRead;
  params: ReadSignInClientParams;
}) => {
  const { t } = useTranslation(["auth", "common"]);
  const { user, logout } = useAuth();
  // Read afresh each time the page opens: somebody returning from adding the
  // plug-in to a community must see it there.
  const placesQuery = useReadSignInPlaces(params, {
    query: { retry: false, refetchOnMount: "always" },
  });
  const authorize = useAuthorizeSignIn();
  // Only an answer read since the page opened counts, so a cached one never
  // offers, or opens, a place that is no longer there.
  const read = placesQuery.isFetchedAfterMount && !placesQuery.isError;
  const places = read ? (placesQuery.data?.places ?? []) : [];

  const open = (place: PluginSignInPlaceRead) =>
    authorize.mutate(
      {
        data: {
          ...params,
          community_id: place.community_id,
          initiative_id: place.initiative_id ?? null,
        },
      },
      { onSuccess: ({ redirect_to }) => window.location.assign(redirect_to) }
    );

  // With one place there is no choice to make.
  const opened = useRef(false);
  useEffect(() => {
    if (places.length !== 1 || opened.current) return;
    opened.current = true;
    open(places[0]);
  });

  const footer = (
    <>
      <p className="text-center text-muted-foreground text-xs">
        {t("pluginSignIn.signedInAs", { handle: user?.username ?? "" })}{" "}
        <button
          type="button"
          className="text-primary underline-offset-4 hover:underline"
          onClick={() => void logout()}
        >
          {t("pluginSignIn.switchAccount")}
        </button>
      </p>
      <Cancel client={client} />
    </>
  );

  // A read that failed says nothing about where the plug-in is.
  if (placesQuery.isError) {
    return (
      <Frame title={t("pluginSignIn.title")} footer={footer}>
        <p className="text-center text-destructive text-sm">
          {getErrorMessage(placesQuery.error, "auth:pluginSignIn.placesFailed")}
        </p>
        <Button className="w-full" onClick={() => void placesQuery.refetch()}>
          {t("common:tryAgain")}
        </Button>
      </Frame>
    );
  }

  if (!read || places.length === 1) {
    return (
      <Frame title={t("pluginSignIn.opening", { name: client.name })} footer={footer}>
        <SkeletonRegion>
          <Skeleton className="h-10 w-full" />
        </SkeletonRegion>
        {authorize.isError ? (
          <p className="text-destructive text-sm">
            {getErrorMessage(authorize.error, "auth:pluginSignIn.unavailable")}
          </p>
        ) : null}
      </Frame>
    );
  }

  if (places.length === 0) {
    return (
      <Frame title={t("pluginSignIn.nowhereTitle", { name: client.name })} footer={footer}>
        <AddToCommunity
          client={client}
          installed={placesQuery.data?.installed_community_ids ?? []}
        />
      </Frame>
    );
  }

  return (
    <Frame
      title={t("pluginSignIn.chooseTitle", { name: client.name })}
      description={t("pluginSignIn.whatItLearns", { name: client.name })}
      footer={footer}
    >
      {places.map((place) => (
        <Button
          key={`${place.community_id}:${place.initiative_id ?? ""}`}
          variant="outline"
          className="w-full justify-start"
          disabled={authorize.isPending}
          onClick={() => open(place)}
        >
          {place.initiative_name
            ? t("pluginSignIn.placeInInitiative", {
                initiative: place.initiative_name,
                community: place.community_name,
              })
            : place.community_name}
        </Button>
      ))}
      {authorize.isError ? (
        <p className="text-destructive text-sm">
          {getErrorMessage(authorize.error, "auth:pluginSignIn.unavailable")}
        </p>
      ) : null}
    </Frame>
  );
};

/**
 * No place to open the plug-in yet: add it to a community the person runs,
 * through the marketplace's own install (and checkout, for a paid one), or
 * start a community for it. Both come back here.
 */
const AddToCommunity = ({
  client,
  installed,
}: {
  client: PluginSignInClientRead;
  installed: number[];
}) => {
  const { t } = useTranslation(["auth", "communities"]);
  const navigate = useNavigate();
  const { communities, canCreateCommunities, createCommunity } = useCommunities();
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const next = useHere();

  const addTo = (communityId: number) =>
    navigate({
      to: "/c/$communityId/marketplace/$publicId",
      params: { communityId: String(communityId), publicId: client.listing_public_id },
      search: { next },
    });

  const runs = communities.filter(
    (community) => community.can.seat && !installed.includes(community.id)
  );

  const start = async () => {
    setBusy(true);
    setError(null);
    try {
      const made = await createCommunity({ name: name.trim() });
      await addTo(made.id);
    } catch (err) {
      setError(getErrorMessage(err, "communities:unableToCreateCommunity"));
      setBusy(false);
    }
  };

  return (
    <>
      <p className="text-center text-muted-foreground text-sm">
        {installed.length > 0
          ? t("pluginSignIn.notAllowed", { name: client.name })
          : t("pluginSignIn.notAdded", { name: client.name })}
      </p>
      {runs.map((community) => (
        <Button
          key={community.id}
          variant="outline"
          className="w-full justify-start"
          onClick={() => void addTo(community.id)}
        >
          {t("pluginSignIn.addTo", { name: client.name, community: community.name })}
        </Button>
      ))}
      {canCreateCommunities ? (
        <form
          className="space-y-2"
          onSubmit={(event) => {
            event.preventDefault();
            if (name.trim()) void start();
          }}
        >
          <Input
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder={t("pluginSignIn.communityName")}
            aria-label={t("pluginSignIn.communityName")}
          />
          <Button type="submit" className="w-full" disabled={busy || !name.trim()}>
            {t("pluginSignIn.startCommunity", { name: client.name })}
          </Button>
          {error ? <p className="text-destructive text-sm">{error}</p> : null}
        </form>
      ) : runs.length === 0 ? (
        <p className="text-center text-muted-foreground text-sm">
          {t("pluginSignIn.askAnAdmin", { name: client.name })}
        </p>
      ) : null}
    </>
  );
};
