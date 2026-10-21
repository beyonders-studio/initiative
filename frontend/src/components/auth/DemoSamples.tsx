import { useTranslation } from "react-i18next";

import { useListDemoSamples } from "@/api/generated/demo/demo";
import { Button } from "@/components/ui/button";

interface DemoSamplesProps {
  /** Fills the sign-in form with a sample's address and password. */
  onUse: (email: string, password: string) => void;
}

/**
 * The demo's sample accounts, which anyone may sign in to: each with its
 * address and password, and a button that puts them in the form. Rendered
 * only on the demo, where the server lists them.
 */
export const DemoSamples = ({ onUse }: DemoSamplesProps) => {
  const { t } = useTranslation("auth");
  const samples = useListDemoSamples({ query: { retry: false, staleTime: Infinity } });
  if (!samples.data?.length) return null;
  return (
    <section className="space-y-3 border-t pt-4" aria-labelledby="demo-samples-title">
      <div className="space-y-1">
        <h2 id="demo-samples-title" className="font-medium text-sm">
          {t("login.samples.title")}
        </h2>
        <p className="text-muted-foreground text-xs">{t("login.samples.description")}</p>
      </div>
      <ul className="space-y-2">
        {samples.data.map((sample) => (
          <li
            key={sample.email}
            className="flex items-center justify-between gap-3 rounded-md border p-3"
          >
            <div className="min-w-0 space-y-0.5 text-sm">
              <p className="truncate font-medium">{sample.display_name}</p>
              {sample.about ? (
                <p className="truncate text-muted-foreground text-xs">{sample.about}</p>
              ) : null}
              <p className="truncate font-mono text-xs">
                {sample.email} · {sample.password}
              </p>
            </div>
            <Button
              type="button"
              size="sm"
              variant="outline"
              onClick={() => onUse(sample.email, sample.password)}
              aria-label={t("login.samples.useNamed", { name: sample.display_name })}
            >
              {t("login.samples.use")}
            </Button>
          </li>
        ))}
      </ul>
    </section>
  );
};
