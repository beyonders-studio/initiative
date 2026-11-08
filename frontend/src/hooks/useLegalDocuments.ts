/**
 * A deployment's own legal documents, and which an account must accept.
 *
 * The documents are not in this repository — a deployment that has terms of
 * its own serves them from the external portal it names, and the app reads
 * them through `/api/v1/legal`, the server's window onto it. Going through
 * the server rather than straight there is what makes them readable from the
 * native build, whose origin is not an `https://` one, and it means the
 * revision a reader is shown is the revision the server records against their
 * acceptance.
 *
 * Which documents an account must accept is the portal's to say, and it may
 * say none: an enterprise's terms may sit in its own contract. A document kept
 * elsewhere (`url`, the customer's own contract) is linked, never read through
 * the server.
 *
 * Nothing is asked of a deployment that names no portal
 * (`useAppConfig().billing` is null): it has no terms of its own, and every
 * route here answers 404.
 */

import { useQuery } from "@tanstack/react-query";

import type { LegalDocumentRead } from "@/api/generated/initiativeAPI.schemas";
import { readLegalDocument, useReadLegalIndex } from "@/api/generated/legal/legal";
import { useAppConfig } from "@/hooks/useAppConfig";

/** Where a reader goes to read one served through the app. */
export const legalDocumentPath = (slug: string) => `/legal/${slug}`;

/** Where a reader goes to read one: where it's kept, when that's elsewhere. */
export const legalDocumentHref = (document: Pick<LegalDocumentRead, "slug" | "url">) =>
  document.url ?? legalDocumentPath(document.slug);

/** Revisions are rare and the server caches its own read of them, so this is
 *  about not re-asking within a session rather than about freshness. */
const LEGAL_STALE_MS = 10 * 60 * 1000;

export const useLegalIndex = () => {
  const { billing } = useAppConfig();
  const enabled = Boolean(billing);
  const query = useReadLegalIndex({ query: { enabled, staleTime: LEGAL_STALE_MS, retry: false } });

  const documents = query.data?.documents ?? [];
  const required = query.data?.required ?? [];
  const requiredDocuments = documents.filter((document) => required.includes(document.slug));
  return {
    /** Whether this deployment names a portal for its documents at all. */
    enabled,
    documents,
    /** What must be accepted, as the portal says: none while the index is
     *  loading or unreachable. */
    requiredDocuments,
    /** What a signup form showed above its button, by slug: sent with the
     *  registration, which records only these. A required document it didn't
     *  show is asked for after sign-in. */
    shownSlugs: requiredDocuments.map((document) => document.slug),
    /** Still asking: a signup form waits, so its notice is there to read. */
    pending: enabled && query.isLoading,
    isLoading: query.isLoading,
  };
};

/** One document's markdown, straight from the server's proxy.
 *
 *  Held for the session rather than re-fetched on every mount: the bytes are
 *  long and unchanging, and the server revalidates against the portal on a
 *  content hash anyway. */
export const useLegalDocument = (slug: string | undefined) =>
  useQuery<string>({
    queryKey: ["legal", "document", slug ?? null],
    // The spec declares no body schema for markdown, so the generated fetcher
    // is typed `void`; asked for text, it returns the document as a string.
    queryFn: () =>
      readLegalDocument(slug as string, {
        responseType: "text",
        headers: { Accept: "text/markdown" },
      }) as unknown as Promise<string>,
    enabled: Boolean(slug),
    staleTime: LEGAL_STALE_MS,
    retry: false,
  });
