import { useTranslation } from "react-i18next";

import type { PostReader } from "@/api/generated/initiativeAPI.schemas";
import { PersonRow } from "@/components/connections/PersonRow";
import { usePostReaders } from "@/hooks/usePosts";
import type { DialogProps } from "@/types/dialog";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/ui/dialog";
import { ListSkeleton, SkeletonRegion } from "@/ui/page-skeletons";
import { RelativeTime } from "@/ui/relative-time";
import { StatusMessage } from "@/ui/status-message";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/ui/tabs";

type PostReadersDialogProps = DialogProps & {
  postId: number;
};

/**
 * The scrolling roster.
 *
 * The horizontal padding is not decoration. A worn frame is drawn 128% of the
 * avatar and hangs ~14% of its width outside on every edge, and a box with
 * `overflow-y: auto` computes its `overflow-x` to `auto` as well — so without
 * room to hang into, the left of every frame is clipped against the edge of
 * the list. The height cap is what makes the scroll necessary in the first
 * place: a notice read by fifty should not push the dialog off the screen.
 */
const ROSTER_LIST = "max-h-80 divide-y overflow-y-auto px-2";

/**
 * One person on the roster.
 *
 * The same row the connections and requests lists use, so somebody wearing a
 * frame wears it here too — a list of people should look like every other
 * list of people in the app, not like a list this one screen invented.
 */
const Person = ({ person }: { person: PostReader }) => (
  <PersonRow user={person}>
    {person.read_at ? (
      <RelativeTime date={person.read_at} className="shrink-0 text-muted-foreground text-xs" />
    ) : null}
  </PersonRow>
);

/**
 * Who has read a notice.
 *
 * Two lists rather than one: who it reached, and who it is still waiting on.
 * The second is the people it was *shared with* — a board of a hundred where a
 * notice went to five is not ninety-five people ignoring it — and the author
 * is on neither, because writing a notice is not reading it.
 */
export const PostReadersDialog = ({ open, onOpenChange, postId }: PostReadersDialogProps) => {
  const { t } = useTranslation(["posts", "common"]);
  const readers = usePostReaders(postId, { enabled: open });

  const read = readers.data?.read ?? [];
  const unread = readers.data?.unread ?? [];

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{t("read.whoRead")}</DialogTitle>
          <DialogDescription>{t("read.whoReadHint")}</DialogDescription>
        </DialogHeader>

        {readers.isLoading ? (
          <SkeletonRegion>
            <ListSkeleton rows={4} />
          </SkeletonRegion>
        ) : readers.isError ? (
          <StatusMessage onRetry={readers.refetch} />
        ) : (
          <Tabs defaultValue="read">
            <TabsList className="w-full">
              <TabsTrigger value="read" className="flex-1">
                {t("read.readTab", { count: read.length })}
              </TabsTrigger>
              <TabsTrigger value="unread" className="flex-1">
                {t("read.unreadTab", { count: unread.length })}
              </TabsTrigger>
            </TabsList>
            <TabsContent value="read">
              {read.length > 0 ? (
                <ul className={ROSTER_LIST}>
                  {read.map((person) => (
                    <Person key={person.id} person={person} />
                  ))}
                </ul>
              ) : (
                <p className="py-6 text-center text-muted-foreground text-sm">
                  {t("read.nobodyYet")}
                </p>
              )}
            </TabsContent>
            <TabsContent value="unread">
              {unread.length > 0 ? (
                <ul className={ROSTER_LIST}>
                  {unread.map((person) => (
                    <Person key={person.id} person={person} />
                  ))}
                </ul>
              ) : (
                <p className="py-6 text-center text-muted-foreground text-sm">
                  {t("read.everyone")}
                </p>
              )}
            </TabsContent>
          </Tabs>
        )}
      </DialogContent>
    </Dialog>
  );
};
