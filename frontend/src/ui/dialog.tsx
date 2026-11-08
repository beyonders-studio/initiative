import * as DialogPrimitive from "@radix-ui/react-dialog";
import { XIcon } from "lucide-react";
import * as React from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/ui/button";
import { FieldContext } from "@/ui/field";
import { cn } from "@/ui/lib/utils";

function Dialog({ ...props }: React.ComponentProps<typeof DialogPrimitive.Root>) {
  return <DialogPrimitive.Root data-slot="dialog" {...props} />;
}

function DialogTrigger({ ...props }: React.ComponentProps<typeof DialogPrimitive.Trigger>) {
  return <DialogPrimitive.Trigger data-slot="dialog-trigger" {...props} />;
}

function DialogPortal({ ...props }: React.ComponentProps<typeof DialogPrimitive.Portal>) {
  return <DialogPrimitive.Portal data-slot="dialog-portal" {...props} />;
}

function DialogClose({ ...props }: React.ComponentProps<typeof DialogPrimitive.Close>) {
  return <DialogPrimitive.Close data-slot="dialog-close" {...props} />;
}

/** The backdrop behind every modal panel: a dialog's, an alert dialog's and a modal sheet's. */
const dialogOverlayClassName =
  "data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 fixed inset-0 z-50 bg-black/50 backdrop-blur duration-200 data-[state=closed]:animate-out data-[state=open]:animate-in supports-backdrop-blur:bg-black/60";

/** A panel's own look wherever it sits. A sheet draws it against an edge of the screen. */
const dialogSurfaceClassName =
  "z-50 gap-4 bg-background p-6 shadow-lg data-[state=closed]:animate-out data-[state=open]:animate-in";

/**
 * A panel centred in the viewport, as a dialog and an alert dialog draw it.
 *
 * `[&>*]:min-w-0` is load-bearing, not cosmetic. This is a grid, so every
 * direct child is a grid item with `min-width: auto` — its automatic minimum
 * is its *content's* minimum, which a nowrap row, a long unbroken word or an
 * editor toolbar can push past the dialog's own width. The item then
 * overflows the box rather than shrinking inside it, and on a phone the
 * right-hand side of every field is simply cut off. Resetting the floor lets
 * children shrink to the dialog and clip/wrap on their own terms.
 */
const dialogContentClassName = `${dialogSurfaceClassName} data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95 fixed top-[50%] left-[50%] grid max-h-[calc(100dvh-2rem)] w-full max-w-[calc(100%-2rem)] translate-x-[-50%] translate-y-[-50%] overflow-y-auto rounded-lg border duration-200 sm:max-w-lg [&>*]:min-w-0`;

const DialogOverlay = React.forwardRef<
  React.ElementRef<typeof DialogPrimitive.Overlay>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Overlay>
>(({ className, ...props }, ref) => (
  <DialogPrimitive.Overlay
    ref={ref}
    data-slot="dialog-overlay"
    className={cn(dialogOverlayClassName, className)}
    {...props}
  />
));
DialogOverlay.displayName = DialogPrimitive.Overlay.displayName;

const DialogContent = React.forwardRef<
  React.ElementRef<typeof DialogPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Content> & {
    showCloseButton?: boolean;
  }
>(({ className, children, showCloseButton = true, ...props }, ref) => {
  const { t } = useTranslation("ui");
  return (
    <DialogPortal data-slot="dialog-portal">
      {/* The content sits inside its overlay. Radix portals each child of the
        portal separately, appended to the body in the order they mount, so
        as siblings an overlay mounted after its content paints over it. */}
      <DialogOverlay>
        <DialogPrimitive.Content
          ref={ref}
          data-slot="dialog-content"
          className={cn(dialogContentClassName, className)}
          {...props}
        >
          {/* A dialog's fields are its own, not those of a field it opened from. */}
          <FieldContext value={null}>{children}</FieldContext>
          {showCloseButton && (
            <DialogPrimitive.Close
              data-slot="dialog-close"
              className="absolute top-4 right-4 rounded-xs opacity-70 ring-offset-background transition-opacity hover:opacity-100 focus:outline-hidden focus:ring-2 focus:ring-ring focus:ring-offset-2 disabled:pointer-events-none data-[state=open]:bg-accent data-[state=open]:text-muted-foreground [&_svg:not([class*='size-'])]:size-4 [&_svg]:pointer-events-none [&_svg]:shrink-0"
            >
              <XIcon />
              <span className="sr-only">{t("close")}</span>
            </DialogPrimitive.Close>
          )}
        </DialogPrimitive.Content>
      </DialogOverlay>
    </DialogPortal>
  );
});
DialogContent.displayName = DialogPrimitive.Content.displayName;

function DialogHeader({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="dialog-header"
      className={cn("flex flex-col gap-2 text-center sm:text-left", className)}
      {...props}
    />
  );
}

type DialogFooterProps = Omit<React.ComponentProps<"div">, "onSubmit"> & {
  /**
   * The submit button's label. With it the footer draws the usual pair after
   * its children: Cancel, which closes the dialog, then the submit button.
   * Without it the footer only lays out its children.
   */
  submitLabel?: React.ReactNode;
  /** The submit button's click. Without one it submits the form the footer is in. */
  onSubmit?: () => void;
  /** Cancel's label, when it is not the kit's own word. */
  cancel?: string;
  /** The work is under way: the submit button spins and both buttons are disabled. */
  pending?: boolean;
  /** The submit button's label while `pending`. */
  pendingLabel?: React.ReactNode;
  /** Disables the submit button. */
  disabled?: boolean;
  destructive?: boolean;
};

function DialogFooter({
  className,
  children,
  submitLabel,
  onSubmit,
  cancel,
  pending = false,
  pendingLabel,
  disabled,
  destructive,
  ...props
}: DialogFooterProps) {
  const { t } = useTranslation("ui");
  return (
    <div
      data-slot="dialog-footer"
      className={cn("flex flex-col-reverse gap-2 sm:flex-row sm:justify-end", className)}
      {...props}
    >
      {children}
      {submitLabel !== undefined && (
        <>
          <DialogPrimitive.Close asChild>
            <Button variant="outline" disabled={pending}>
              {cancel ?? t("cancel")}
            </Button>
          </DialogPrimitive.Close>
          <Button
            type={onSubmit ? "button" : "submit"}
            onClick={onSubmit}
            variant={destructive ? "destructive" : "default"}
            pending={pending}
            disabled={disabled}
          >
            {pending ? (pendingLabel ?? submitLabel) : submitLabel}
          </Button>
        </>
      )}
    </div>
  );
}

const DialogTitle = React.forwardRef<
  React.ElementRef<typeof DialogPrimitive.Title>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Title>
>(({ className, ...props }, ref) => (
  <DialogPrimitive.Title
    ref={ref}
    data-slot="dialog-title"
    className={cn("font-semibold text-lg leading-none", className)}
    {...props}
  />
));
DialogTitle.displayName = DialogPrimitive.Title.displayName;

const DialogDescription = React.forwardRef<
  React.ElementRef<typeof DialogPrimitive.Description>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Description>
>(({ className, ...props }, ref) => (
  <DialogPrimitive.Description
    ref={ref}
    data-slot="dialog-description"
    className={cn("text-muted-foreground text-sm", className)}
    {...props}
  />
));
DialogDescription.displayName = DialogPrimitive.Description.displayName;

export {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogOverlay,
  DialogPortal,
  DialogTitle,
  DialogTrigger,
  dialogContentClassName,
  dialogOverlayClassName,
  dialogSurfaceClassName,
};
