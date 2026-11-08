import { Camera } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  Presence,
  ProfileDecorationsOutput,
  UserSelfUpdate,
} from "@/api/generated/initiativeAPI.schemas";
import { deleteMyAvatar, uploadMyAvatar } from "@/api/generated/users/users";
import { ProfileAvatar } from "@/components/user/ProfileAvatar";
import { useApiMutation } from "@/hooks/useApiMutation";
import { useUpdateCurrentUser } from "@/hooks/useUsers";
import { getErrorMessage } from "@/lib/errorMessage";
import { ImageRenditionError, renderAvatar } from "@/lib/imageRenditions";
import { toast } from "@/lib/mascotToast";
import type { AvatarSourceUser, DisplayableUser } from "@/lib/userDisplay";
import { Button } from "@/ui/button";
import { ImagePicker } from "@/ui/image-picker";
import { Input } from "@/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/ui/popover";
import { Tabs, TabsBar, TabsContent, TabsTrigger } from "@/ui/tabs";

/** Where this server serves an uploaded picture from. A linked one — from a
 *  single sign-on account — is any other URL. */
const UPLOADED_PREFIX = "/api/v1/users/";

const uploaded = (url: string | null | undefined): string | null =>
  url?.startsWith(UPLOADED_PREFIX) ? url : null;

const linked = (url: string | null | undefined): boolean => Boolean(url) && !uploaded(url);

interface ProfilePictureProps {
  user: DisplayableUser & AvatarSourceUser;
  decorations: ProfileDecorationsOutput;
  presence?: Presence;
  /** Leave the corner empty for a caller putting its own control there. */
  hidePresence?: boolean;
  className?: string;
  /** Whether this is your own picture, and clicking it opens the editor. */
  editable?: boolean;
  onChanged?: () => Promise<void> | void;
}

/**
 * The picture, and — on your own profile — the way to change it.
 *
 * Clicking the face is how everyone expects to change the face, so there is no
 * separate section for it: the control is the thing it controls. Uploading
 * writes immediately, because an uploaded picture is a resource of its own
 * rather than a field of a form; a linked URL is the only part with anything
 * to save.
 */
export const ProfilePicture = ({
  user,
  decorations,
  presence,
  hidePresence,
  className,
  editable = false,
  onChanged,
}: ProfilePictureProps) => {
  const { t } = useTranslation(["settings", "common"]);
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState<"upload" | "url">(linked(user.avatar_url) ? "url" : "upload");
  const [url, setUrl] = useState(linked(user.avatar_url) ? (user.avatar_url ?? "") : "");

  // Follow the saved picture when it changes. Without this the field keeps the
  // URL it was mounted with, so uploading a picture and then saving the URL tab
  // would write the old link back over the upload.
  const [synced, setSynced] = useState(user.avatar_url ?? null);
  if (synced !== (user.avatar_url ?? null)) {
    setSynced(user.avatar_url ?? null);
    setUrl(linked(user.avatar_url) ? (user.avatar_url ?? "") : "");
    setMode(linked(user.avatar_url) ? "url" : "upload");
  }

  const saveLink = useUpdateCurrentUser({
    onSuccess: async () => {
      setOpen(false);
      await onChanged?.();
    },
    onError: (error: unknown) =>
      toast.error(getErrorMessage(error, "settings:profile.updateError")),
  });

  const picture = useApiMutation(
    { mutationFn: (work: () => Promise<unknown>) => work() },
    {
      onSuccess: async () => {
        setOpen(false);
        await onChanged?.();
      },
      // A picture the browser could not make sense of never reached the
      // server, so it has its own message rather than an API code.
      onError: (error) =>
        toast.error(
          error instanceof ImageRenditionError
            ? t(`settings:profile.avatar.${error.code}`)
            : getErrorMessage(error, "settings:profile.avatar.failed")
        ),
    }
  );

  const pick = (file: File) => {
    picture.mutate(async () => uploadMyAvatar({ file: await renderAvatar(file) }));
  };

  const avatar = (
    <ProfileAvatar
      user={user}
      decorations={decorations}
      presence={presence}
      hidePresence={hidePresence}
      ring
      className={className}
    />
  );

  if (!editable) return avatar;

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          className="group relative rounded-full focus-visible:outline-2 focus-visible:outline-ring focus-visible:outline-offset-2"
          aria-label={t("settings:profile.avatarLabel")}
        >
          {avatar}
          {/* Only on hover and focus: a camera badge sitting on every avatar
              all the time would read as part of the picture. */}
          <span className="absolute inset-0 flex items-center justify-center rounded-full bg-black/45 opacity-0 transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100">
            <Camera className="size-6 text-white" aria-hidden="true" />
          </span>
        </button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-80 space-y-3">
        <p className="font-medium text-sm">{t("settings:profile.avatarLabel")}</p>
        <Tabs value={mode} onValueChange={(value) => setMode(value as "upload" | "url")}>
          <TabsBar>
            <TabsTrigger value="upload">{t("settings:profile.avatarUploadTab")}</TabsTrigger>
            <TabsTrigger value="url">{t("settings:profile.avatarUrlTab")}</TabsTrigger>
          </TabsBar>
          <TabsContent value="upload" className="space-y-2">
            <ImagePicker accept="image/*" disabled={picture.isPending} onSelect={pick} />
            <p className="text-muted-foreground text-xs">
              {t("settings:profile.avatarUploadHelp")}
            </p>
            {uploaded(user.avatar_url) ? (
              <Button
                type="button"
                variant="ghost"
                size="sm"
                disabled={picture.isPending}
                onClick={() => picture.mutate(() => deleteMyAvatar())}
              >
                {t("settings:profile.removeUploadedAvatar")}
              </Button>
            ) : null}
          </TabsContent>
          <TabsContent value="url" className="space-y-2">
            <Input
              type="url"
              placeholder={t("settings:profile.avatarUrlPlaceholder")}
              value={url}
              onChange={(event) => setUrl(event.target.value)}
            />
            <Button
              type="button"
              size="sm"
              disabled={saveLink.isPending}
              onClick={() => saveLink.mutate({ avatar_url: url || null } as UserSelfUpdate)}
            >
              {saveLink.isPending ? t("common:submitting") : t("settings:profile.saveChanges")}
            </Button>
          </TabsContent>
        </Tabs>
      </PopoverContent>
    </Popover>
  );
};
