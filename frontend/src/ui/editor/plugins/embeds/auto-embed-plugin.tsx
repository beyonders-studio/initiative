import { SiX, SiYoutube } from "@icons-pack/react-simple-icons";
import {
  AutoEmbedOption,
  type EmbedConfig,
  type EmbedMatchResult,
  LexicalAutoEmbedPlugin,
  URL_MATCHER,
} from "@lexical/react/LexicalAutoEmbedPlugin";
import { useLexicalComposerContext } from "@lexical/react/LexicalComposerContext";
import { PopoverPortal } from "@radix-ui/react-popover";
import type { LexicalEditor } from "lexical";
import { type JSX, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/ui/button";
import { Command, CommandGroup, CommandItem, CommandList } from "@/ui/command";
import { DialogFooter } from "@/ui/dialog";
import { useEditorModal } from "@/ui/editor/editor-hooks/use-modal";
import { INSERT_TWEET_COMMAND } from "@/ui/editor/plugins/embeds/twitter-plugin";
import { INSERT_YOUTUBE_COMMAND } from "@/ui/editor/plugins/embeds/youtube-plugin";
import { Input } from "@/ui/input";
import { matchSmartLinkProvider } from "@/ui/lib/smartLinkProviders";
import { Popover, PopoverContent, PopoverTrigger } from "@/ui/popover";

export interface CustomEmbedConfig extends EmbedConfig {
  // Human readable name of the embeded content e.g. Tweet or Google Map.
  contentName: string;

  // i18n key for the content name (e.g. "youtubeVideo").
  contentNameKey?: string;

  // Icon for display.
  icon?: JSX.Element;

  // An example of a matching url https://twitter.com/jack/status/20
  exampleUrl: string;

  // For extra searching.
  keywords: Array<string>;

  // Embed a Project.
  description?: string;
}

export const YoutubeEmbedConfig: CustomEmbedConfig = {
  contentName: "Youtube Video",
  contentNameKey: "youtubeVideo",

  exampleUrl: "https://www.youtube.com/watch?v=jNQXAC9IVRw",

  // Icon for display.
  icon: <SiYoutube className="size-4" />,

  insertNode: (editor: LexicalEditor, result: EmbedMatchResult) => {
    editor.dispatchCommand(INSERT_YOUTUBE_COMMAND, result.id);
  },

  keywords: ["youtube", "video"],

  // Determine if a given URL is a match and return url data.
  parseUrl: (url: string) => {
    const embed = matchSmartLinkProvider(url);
    return embed.id === "youtube" && embed.ref ? { id: embed.ref, url } : null;
  },

  type: "youtube-video",
};

export const TwitterEmbedConfig: CustomEmbedConfig = {
  // e.g. Tweet or Google Map.
  contentName: "Tweet",
  contentNameKey: "tweet",

  exampleUrl: "https://twitter.com/jack/status/20",

  // Icon for display.
  icon: <SiX className="size-4" />,

  // Create the Lexical embed node from the url data.
  insertNode: (editor: LexicalEditor, result: EmbedMatchResult) => {
    editor.dispatchCommand(INSERT_TWEET_COMMAND, result.id);
  },

  // For extra searching.
  keywords: ["tweet", "twitter", "x"],

  // Determine if a given URL is a match and return url data.
  parseUrl: (text: string) => {
    const embed = matchSmartLinkProvider(text);
    return embed.id === "x" && embed.ref ? { id: embed.ref, url: text } : null;
  },

  type: "tweet",
};

export const EmbedConfigs = [TwitterEmbedConfig, YoutubeEmbedConfig];

const debounce = (callback: (text: string) => void, delay: number) => {
  let timeoutId: number;
  return (text: string) => {
    window.clearTimeout(timeoutId);
    timeoutId = window.setTimeout(() => {
      callback(text);
    }, delay);
  };
};

export function AutoEmbedDialog({
  embedConfig,
  onClose,
}: {
  embedConfig: CustomEmbedConfig;
  onClose: () => void;
}): JSX.Element {
  const { t } = useTranslation("editor");
  const [text, setText] = useState("");
  const [editor] = useLexicalComposerContext();
  const [embedResult, setEmbedResult] = useState<EmbedMatchResult | null>(null);

  const validateText = useMemo(
    () =>
      debounce((inputText: string) => {
        const urlMatch = URL_MATCHER.exec(inputText);
        if (embedConfig != null && inputText != null && urlMatch != null) {
          Promise.resolve(embedConfig.parseUrl(inputText)).then((parseResult) => {
            setEmbedResult(parseResult);
          });
        } else if (embedResult != null) {
          setEmbedResult(null);
        }
      }, 200),
    [embedConfig, embedResult]
  );

  const onClick = () => {
    if (embedResult != null) {
      embedConfig.insertNode(editor, embedResult);
      onClose();
    }
  };

  return (
    <div className="">
      <div className="space-y-4">
        <Input
          type="text"
          placeholder={embedConfig.exampleUrl}
          value={text}
          data-test-id={`${embedConfig.type}-embed-modal-url`}
          onChange={(e) => {
            const { value } = e.target;
            setText(value);
            validateText(value);
          }}
        />
        <DialogFooter>
          <Button
            disabled={!embedResult}
            onClick={onClick}
            data-test-id={`${embedConfig.type}-embed-modal-submit-btn`}
          >
            {t("embed")}
          </Button>
        </DialogFooter>
      </div>
    </div>
  );
}

export function AutoEmbedPlugin(): JSX.Element {
  const [modal, showModal] = useEditorModal();
  const { t } = useTranslation("editor");

  const getContentName = (config: CustomEmbedConfig) =>
    config.contentNameKey ? t(config.contentNameKey as never) : config.contentName;

  const openEmbedModal = (embedConfig: CustomEmbedConfig) => {
    showModal(t("embedContent", { contentName: getContentName(embedConfig) }), (onClose) => (
      <AutoEmbedDialog embedConfig={embedConfig} onClose={onClose} />
    ));
  };

  const getMenuOptions = (
    activeEmbedConfig: CustomEmbedConfig,
    embedFn: () => void,
    dismissFn: () => void
  ) => {
    return [
      new AutoEmbedOption(t("dismiss"), {
        onSelect: dismissFn,
      }),
      new AutoEmbedOption(t("embedContent", { contentName: getContentName(activeEmbedConfig) }), {
        onSelect: embedFn,
      }),
    ];
  };

  return (
    <>
      {modal}
      <LexicalAutoEmbedPlugin<CustomEmbedConfig>
        embedConfigs={EmbedConfigs}
        onOpenEmbedModalForConfig={openEmbedModal}
        getMenuOptions={getMenuOptions}
        menuRenderFn={(
          anchorElementRef,
          { /* selectedIndex, */ options, selectOptionAndCleanUp /*, setHighlightedIndex */ }
        ) => {
          return anchorElementRef.current ? (
            <Popover open={true}>
              <PopoverPortal container={anchorElementRef.current}>
                <div className="-translate-y-full transform">
                  <PopoverTrigger />
                  <PopoverContent className="w-[200px] p-0" align="start" side="right">
                    <Command>
                      <CommandList>
                        <CommandGroup>
                          {options.map((option) => (
                            <CommandItem
                              key={option.key}
                              value={option.title}
                              onSelect={() => {
                                selectOptionAndCleanUp(option);
                              }}
                              className="flex items-center gap-2"
                            >
                              {option.title}
                            </CommandItem>
                          ))}
                        </CommandGroup>
                      </CommandList>
                    </Command>
                  </PopoverContent>
                </div>
              </PopoverPortal>
            </Popover>
          ) : null;
        }}
      />
    </>
  );
}
