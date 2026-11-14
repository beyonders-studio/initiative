import { Moon, Sun } from "lucide-react";
import { useTranslation } from "react-i18next";

import { useTheme } from "@/hooks/useTheme";
import { Button } from "@/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
} from "@/ui/dropdown-menu";
import { cn } from "@/ui/lib/utils";

/**
 * A sun that turns into a moon, and back.
 *
 * Whichever half is showing is the theme in force, so the one mark serves as
 * the button on a page with no account menu and as the entry inside one — and
 * it answers "which theme am I on" without being opened.
 */
export const ThemeIcon = ({ className }: { className?: string }) => (
  <span className={cn("relative flex items-center justify-center", className)}>
    <Sun className="size-full rotate-0 scale-100 transition-all dark:-rotate-90 dark:scale-0" />
    <Moon className="absolute size-full rotate-90 scale-0 transition-all dark:rotate-0 dark:scale-100" />
  </span>
);

/**
 * How the app looks: the choices on their own, to drop into a menu.
 *
 * Items rather than a menu of their own, because the two places that offer
 * them differ only in what they hang off — a button of its own on the landing
 * page, a submenu of the account menu in the sidebar, where the row has better
 * uses for the width than a control nobody touches twice.
 */
export const AppearanceMenuItems = () => {
  const { theme, setTheme } = useTheme();
  const { t } = useTranslation("nav");

  return (
    <>
      <DropdownMenuLabel>{t("theme")}</DropdownMenuLabel>
      <DropdownMenuRadioGroup
        value={theme}
        onValueChange={(value) => setTheme(value as "light" | "dark" | "system")}
      >
        <DropdownMenuRadioItem value="system">{t("themeSystem")}</DropdownMenuRadioItem>
        <DropdownMenuRadioItem value="light">{t("themeLight")}</DropdownMenuRadioItem>
        <DropdownMenuRadioItem value="dark">{t("themeDark")}</DropdownMenuRadioItem>
      </DropdownMenuRadioGroup>
    </>
  );
};

/** The same choices behind a sun that turns into a moon, for a page with no
 *  account menu to put them in. */
export const ModeToggle = () => {
  const { t } = useTranslation("nav");

  return (
    // modal={false}: a modal dropdown nested in the non-modal mobile sidebar
    // drawer dismisses the drawer on open (see SidebarUserFooter).
    <DropdownMenu modal={false}>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          className="relative"
          type="button"
          aria-label={t("toggleTheme")}
        >
          <ThemeIcon className="size-5" />
          <span className="sr-only">{t("toggleTheme")}</span>
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-40">
        <AppearanceMenuItems />
      </DropdownMenuContent>
    </DropdownMenu>
  );
};
