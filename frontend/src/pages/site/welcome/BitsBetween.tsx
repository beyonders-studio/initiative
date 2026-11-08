/**
 * The features every tool shares, each with a small drawing of what it looks
 * like on screen. The drawings are pictures, so a screen reader gets the
 * heading and the sentence under each, not the drawing.
 *
 * On a phone the cards are one row that scrolls sideways.
 */

import {
  Bell,
  FileText,
  Heart,
  ListTodo,
  Lock,
  MessageCircle,
  Moon,
  Search,
  ThumbsUp,
} from "lucide-react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

/** Where people move in from. Product names, so not translated. */
const IMPORT_SOURCES = ["Todoist", "TickTick", "Vikunja", "Jira", "Confluence"];

const Card = ({ title, body, children }: { title: string; body: string; children: ReactNode }) => (
  <li className="flex w-71 shrink-0 snap-start flex-col overflow-hidden rounded-2xl border bg-card md:w-auto">
    <div
      className="flex h-42 flex-col justify-center gap-2 bg-muted p-4 text-sm md:h-46"
      aria-hidden="true"
    >
      {children}
    </div>
    <div className="p-4 sm:p-5">
      <h3 className="font-bold text-lg leading-tight sm:text-xl">{title}</h3>
      <p className="mt-1.5 text-muted-foreground text-sm sm:text-[15px]">{body}</p>
    </div>
  </li>
);

const Task = ({ name, where, color }: { name: string; where: string; color: string }) => (
  <div className="flex items-center gap-2.5 rounded-lg border bg-card px-2.5 py-1.5">
    <span className="h-4 w-4 shrink-0 rounded-[5px] border-2 border-muted-foreground/50" />
    <span className="min-w-0 flex-1 truncate font-medium">{name}</span>
    <span className="h-2 w-2 shrink-0 rounded-full" style={{ backgroundColor: color }} />
    <small className="whitespace-nowrap text-muted-foreground text-xs">{where}</small>
  </div>
);

const Relation = ({ label, item, doc }: { label: string; item: string; doc?: boolean }) => (
  <div className="flex items-center gap-2 rounded-lg border bg-card px-2.5 py-2">
    <small className="w-24 shrink-0 text-muted-foreground text-xs">{label}</small>
    {doc ? <FileText className="h-4 w-4 shrink-0" /> : <ListTodo className="h-4 w-4 shrink-0" />}
    <b className="truncate font-semibold">{item}</b>
  </div>
);

export const BitsBetween = () => {
  const { t } = useTranslation("landing");
  // The word the search drawing finds, in the reader's language.
  const match = t("between.search.match").toLowerCase();
  const highlight = (text: string, word: string) => {
    const at = text.toLowerCase().indexOf(word);
    if (at < 0) return text;
    return (
      <>
        {text.slice(0, at)}
        <mark className="rounded-sm bg-amber-200 px-0.5 text-inherit dark:bg-amber-500/40">
          {text.slice(at, at + word.length)}
        </mark>
        {text.slice(at + word.length)}
      </>
    );
  };

  return (
    <section className="bg-muted/40" aria-labelledby="landing-between-title">
      <div className="mx-auto max-w-6xl px-4 py-14 sm:px-8 sm:py-22">
        <div className="mb-7 max-w-2xl sm:mb-10">
          <h2
            id="landing-between-title"
            className="font-extrabold text-3xl tracking-tight sm:text-5xl"
          >
            {t("between.title")}
          </h2>
          <p className="mt-3 text-lg text-muted-foreground">{t("between.description")}</p>
        </div>
        {/* On a phone the cards are one row that scrolls sideways; the row
            takes focus so it can be scrolled from a keyboard too. */}
        <section
          // biome-ignore lint/a11y/noNoninteractiveTabindex: a scrolling region has to be reachable by keyboard
          tabIndex={0}
          aria-label={t("between.cardsAria")}
          className="-mx-4 snap-x snap-mandatory overflow-x-auto px-4 pb-1.5 focus-visible:outline-2 focus-visible:outline-ring md:mx-0 md:overflow-visible md:px-0"
        >
          <ul className="flex w-max gap-2.5 md:grid md:w-auto md:grid-cols-3 md:gap-4">
            <Card title={t("between.comments.title")} body={t("between.comments.body")}>
              <div className="flex items-start gap-2.5 rounded-xl border bg-card p-3">
                <span className="flex h-6.5 w-6.5 shrink-0 items-center justify-center rounded-full bg-teal-700 font-bold text-3xs text-white">
                  SM
                </span>
                <div className="min-w-0">
                  <p>
                    <b>{t("between.comments.author")}</b>{" "}
                    <span className="text-muted-foreground text-xs">
                      {t("between.comments.on")}
                    </span>
                  </p>
                  <p className="mt-0.5">
                    <span className="rounded bg-primary/15 px-1 font-semibold text-primary">
                      {t("between.comments.mention")}
                    </span>{" "}
                    {t("between.comments.text")}
                  </p>
                  <div className="mt-2 flex gap-1.5 text-xs">
                    <span className="inline-flex items-center gap-1 rounded-full border border-primary/30 bg-primary/10 px-2 py-0.5 font-semibold">
                      <ThumbsUp className="h-3 w-3" /> 3
                    </span>
                    <span className="inline-flex items-center gap-1 rounded-full border px-2 py-0.5 font-semibold">
                      <Heart className="h-3 w-3" /> 1
                    </span>
                    <span className="inline-flex items-center gap-1 rounded-full border px-2 py-0.5 font-semibold">
                      <MessageCircle className="h-3 w-3" /> {t("between.comments.replies")}
                    </span>
                  </div>
                </div>
              </div>
            </Card>

            <Card title={t("between.mine.title")} body={t("between.mine.body")}>
              <Task
                name={t("between.mine.task1")}
                where={t("between.mine.where1")}
                color="#ef4444"
              />
              <Task
                name={t("between.mine.task2")}
                where={t("between.mine.where2")}
                color="#14b8a6"
              />
              <Task
                name={t("between.mine.task3")}
                where={t("between.mine.where3")}
                color="#8b5cf6"
              />
              <Task
                name={t("between.mine.task4")}
                where={t("between.mine.where4")}
                color="#2563eb"
              />
            </Card>

            <Card title={t("between.search.title")} body={t("between.search.body")}>
              <div className="rounded-xl border bg-card p-2">
                <div className="flex items-center gap-2 border-b px-1.5 pb-2">
                  <Search className="h-4 w-4" />
                  <span className="flex-1 font-semibold">{t("between.search.query")}</span>
                  <kbd className="rounded border bg-muted px-1.5 font-semibold text-2xs text-foreground">
                    Ctrl K
                  </kbd>
                </div>
                <div className="mt-1 flex items-center gap-2 rounded-md bg-primary/10 px-2 py-1">
                  <FileText className="h-3.5 w-3.5" />
                  <span className="flex-1 truncate">
                    {highlight(t("between.search.result1"), match)}
                  </span>
                  <small className="text-foreground/80 text-xs">{t("between.search.doc")}</small>
                </div>
                <div className="flex items-center gap-2 px-2 py-1">
                  <ListTodo className="h-3.5 w-3.5" />
                  <span className="flex-1 truncate">
                    {highlight(t("between.search.result2"), match)}
                  </span>
                  <small className="text-muted-foreground text-xs">
                    {t("between.search.task")}
                  </small>
                </div>
                <div className="flex items-center gap-2 px-2 py-1">
                  <MessageCircle className="h-3.5 w-3.5" />
                  <span className="flex-1 truncate">
                    {highlight(t("between.search.result3"), match)}
                  </span>
                  <small className="text-muted-foreground text-xs">
                    {t("between.search.comment")}
                  </small>
                </div>
              </div>
            </Card>

            <Card title={t("between.relations.title")} body={t("between.relations.body")}>
              <Relation
                label={t("between.relations.blockedBy")}
                item={t("between.relations.item1")}
              />
              <Relation label={t("between.relations.partOf")} item={t("between.relations.item2")} />
              <Relation
                label={t("between.relations.mentionedIn")}
                item={t("between.relations.item3")}
                doc
              />
            </Card>

            <Card title={t("between.notify.title")} body={t("between.notify.body")}>
              <div className="flex items-start gap-2.5 rounded-xl bg-[#0b1224] px-3.5 py-3 text-slate-200">
                <Bell className="mt-0.5 h-4 w-4 shrink-0 text-amber-400" />
                <div>
                  <b className="text-white">{t("between.notify.toastTitle")}</b>
                  <span className="block text-xs">{t("between.notify.toastWhere")}</span>
                </div>
              </div>
              <div className="flex items-center justify-between gap-2 rounded-xl border bg-card px-3 py-2">
                <span className="flex items-center gap-2 font-semibold">
                  <Moon className="h-4 w-4" />
                  {t("between.notify.quiet")}
                </span>
                <span className="text-muted-foreground text-xs">
                  {t("between.notify.quietHours")}
                </span>
                <span className="relative h-5 w-8.5 shrink-0 rounded-full bg-primary">
                  <span className="absolute top-0.5 right-0.5 h-4 w-4 rounded-full bg-primary-foreground" />
                </span>
              </div>
            </Card>

            <Card title={t("between.messages.title")} body={t("between.messages.body")}>
              <span className="inline-flex items-center gap-1.5 self-center rounded-full bg-green-100 px-2.5 py-0.5 font-semibold text-green-800 text-xs dark:bg-green-900/40 dark:text-green-200">
                <Lock className="h-3 w-3" />
                {t("between.messages.e2e")}
              </span>
              <p className="max-w-[80%] self-start rounded-2xl rounded-bl-sm border bg-card px-3 py-1.5">
                {t("between.messages.m1")}
              </p>
              <p className="max-w-[80%] self-end rounded-2xl rounded-br-sm bg-primary px-3 py-1.5 text-primary-foreground">
                {t("between.messages.m2")}
              </p>
              <p className="max-w-[80%] self-start rounded-2xl rounded-bl-sm border bg-card px-3 py-1.5">
                {t("between.messages.m3")}
              </p>
            </Card>
          </ul>
        </section>
        <p className="mt-6 hidden flex-wrap items-center gap-2.5 rounded-2xl bg-[#0b1224] px-6 py-5 text-slate-200 md:flex">
          <b className="mr-1.5 text-white">{t("between.imports")}</b>
          {IMPORT_SOURCES.map((source) => (
            <span
              key={source}
              className="rounded-full border border-white/15 bg-white/8 px-3 py-0.5 font-semibold text-sm text-white"
            >
              {source}
            </span>
          ))}
        </p>
      </div>
    </section>
  );
};
