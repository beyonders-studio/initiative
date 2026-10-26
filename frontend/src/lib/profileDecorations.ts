/**
 * The catalog a profile's decorations are resolved against.
 *
 * A profile stores **ids**, never images: `{ banner: "core.aurora", frame:
 * "core.gold", trophies: ["core.founder"] }`. This module is what turns one of
 * those ids into something to render — a lookup in the table below, so an id
 * that isn't in it resolves to nothing at all.
 *
 * Everything here ships with the app under `public/decorations/`, so wearing a
 * banner costs a community none of its upload allowance. Which of them an
 * account may wear is the server's answer, not this file's — this only says
 * what a decoration looks like once it has been granted.
 *
 * Banners and frames animate; trophies do not. A trophy is a small, still mark of
 * belonging, and a row of them beside a name would be unreadable if each one
 * moved. The artwork is SVG rather than GIF so it stays crisp at any size,
 * weighs a few kB, and can hold still for a reader who has asked for less
 * motion — which it does, via `prefers-reduced-motion` inside each file.
 *
 * An id a deployment doesn't know renders as bare — which is the behaviour that
 * lets a profile keep wearing something the store has stopped offering.
 */

import type { ProfileDecorationsOutput } from "@/api/generated/initiativeAPI.schemas";
import { DATED_DECORATIONS, gradArtwork } from "@/lib/gradArtwork";

export type DecorationKind = "banner" | "frame" | "trophy";

/**
 * Where a frame's artwork holds the picture, in its own 128-unit viewBox.
 *
 * Every frame is drawn to this one aperture: a circle of radius 50 at the
 * centre, which the picture fills exactly. A frame is then free to run outward
 * as far as the canvas allows — the gold ring is thin, the vinyl record is
 * thick — without either of them needing the code to know which it is.
 *
 * Sizing the artwork so radius 50 lands on the picture's edge makes it 128/50
 * as wide as the picture; the overhang splits evenly across the two sides,
 * which is what `FRAME_INSET` says in the units CSS wants.
 */
const FRAME_APERTURE = 50;
const FRAME_VIEWBOX = 128;

/**
 * How wide the artwork runs next to the picture it holds, and how far it hangs
 * off each side. Both are percentages of the picture's own box.
 *
 * The size has to be stated: an absolutely positioned `<img>` whose width is
 * `auto` is laid out at its intrinsic size no matter what its insets say, so
 * offsets alone would draw every frame at 128px whatever it surrounds.
 */
export const FRAME_SIZE = `${((FRAME_VIEWBOX / (FRAME_APERTURE * 2)) * 100).toFixed(2)}%`;
export const FRAME_INSET = `${(((1 - FRAME_VIEWBOX / 2 / FRAME_APERTURE) / 2) * 100).toFixed(2)}%`;

/**
 * The other way round: where the picture sits when the *artwork* is the thing
 * being sized. Used by the swatches, which show a frame at a fixed size with a
 * stand-in disc where a face would be.
 */
export const FRAME_APERTURE_INSET = `${(((1 - (FRAME_APERTURE * 2) / FRAME_VIEWBOX) / 2) * 100).toFixed(2)}%`;

/** Every decoration this build ships, by the name its label is keyed under. */
type DecorationName =
  | "alphabetblocks"
  | "ammonite"
  | "apple"
  | "arcade"
  | "aurora"
  | "backpack"
  | "balcony"
  | "bat"
  | "bauble"
  | "beach"
  | "benzene"
  | "bicycle"
  | "blade"
  | "blocks"
  | "bones"
  | "bookshelf"
  | "bunsenburner"
  | "buttons"
  | "bytrain"
  | "campfire"
  | "car"
  | "cassette"
  | "cat"
  | "catears"
  | "catnap"
  | "chalkboard"
  | "christmaseve"
  | "christmaslights"
  | "clapper"
  | "classroom"
  | "clay"
  | "cobweb"
  | "cocoa"
  | "collar"
  | "colosseum"
  | "commencement"
  | "controller"
  | "court"
  | "crayons"
  | "cupoftea"
  | "curtain"
  | "d20"
  | "dagger"
  | "desert"
  | "diamond"
  | "dicetower"
  | "diploma"
  | "directorschair"
  | "dividers"
  | "dna"
  | "dog"
  | "dogears"
  | "drivein"
  | "drums"
  | "eiffeltower"
  | "ember"
  | "endzone"
  | "engarde"
  | "enso"
  | "faceoff"
  | "fan"
  | "fastball"
  | "festival"
  | "fetch"
  | "filmstrip"
  | "flask"
  | "floodlights"
  | "flurry"
  | "gamesnight"
  | "garden"
  | "ghost"
  | "glasses"
  | "globe"
  | "gold"
  | "goldengate"
  | "goodplacetoread"
  | "grad"
  | "graduationcap"
  | "gradyear"
  | "grove"
  | "guitar"
  | "hamster"
  | "headphones"
  | "hearth"
  | "helix"
  | "hollow"
  | "horse"
  | "icicles"
  | "incense"
  | "ironwork"
  | "keys"
  | "koi"
  | "labbench"
  | "laces"
  | "lake"
  | "landmarks"
  | "lantern"
  | "laurel"
  | "lizard"
  | "lotus"
  | "madteaparty"
  | "magnet"
  | "marquee"
  | "masks"
  | "matcha"
  | "matchball"
  | "meeple"
  | "microphone"
  | "microscope"
  | "mixtape"
  | "monstera"
  | "morel"
  | "mortarboard"
  | "mountain"
  | "natural20"
  | "nest"
  | "net"
  | "nightsky"
  | "notebook"
  | "observatory"
  | "orbital"
  | "oreblock"
  | "overgrown"
  | "paddock"
  | "pages"
  | "panels"
  | "parchment"
  | "pawprint"
  | "pencil"
  | "pigskin"
  | "pines"
  | "piste"
  | "plane"
  | "playhouse"
  | "poinsettia"
  | "popcorn"
  | "porcelain"
  | "projector"
  | "puck"
  | "quill"
  | "rabbit"
  | "rakedsand"
  | "rakelines"
  | "rat"
  | "ratears"
  | "reel"
  | "ridge"
  | "rink"
  | "rockhammer"
  | "rosette"
  | "saxophone"
  | "schoolbus"
  | "sciencelab"
  | "screening"
  | "seams"
  | "sheetmusic"
  | "ship"
  | "showtime"
  | "singingbowl"
  | "skeletons"
  | "snake"
  | "snowflake"
  | "snowman"
  | "soundcheck"
  | "spike"
  | "spines"
  | "split"
  | "stack"
  | "stage"
  | "stagelights"
  | "stitching"
  | "stones"
  | "strings"
  | "succulent"
  | "swish"
  | "teabag"
  | "teacup"
  | "teagarden"
  | "teapot"
  | "teaservice"
  | "tennisace"
  | "tent"
  | "ticket"
  | "torii"
  | "train"
  | "turntable"
  | "typewriter"
  | "vines"
  | "vinyl"
  | "violin"
  | "windowsill"
  | "witchinghour"
  | "wreath"
  | "writingdesk"
  | "yorick";

/**
 * A pack is a marketplace listing now, so its name, publisher and description
 * come from the catalog — this file only says what its *pieces* look like.
 * That is why there is no pack table here: a pack published tomorrow needs no
 * entry, only artwork for the ids it grants.
 */

export interface Decoration {
  id: string;
  kind: DecorationKind;
  /**
   * For a banner, whether the artwork is dark enough to write on in white.
   *
   * A community picks its banner's text colour because it picks the picture.
   * A decoration's artwork ships with the app, so the artwork answers instead
   * — there is nothing to compute it from at runtime, and every banner but the
   * parchment one is a night sky.
   */
  ink?: "light" | "dark";
  /** Where the artwork is, relative to the app's root. */
  src: string;
  /** Key into the `profiles` namespace for this decoration's name. */
  labelKey: `decorations.${DecorationName}`;
  /**
   * How many colours the wearer picks for this one, if they pick any.
   *
   * Only what ships with the app: a pack's artwork is the pack's, and a
   * publisher who wanted it recoloured would have shipped it that way. A frame
   * with this set is drawn by `TintedFrame` rather than served as a file — the
   * file at `src` is what it looks like in its default colours.
   */
  tint?: 1 | 2;
  /**
   * Whether the artwork carries a year the wearer picked.
   *
   * Like `tint`, this marks a decoration that is drawn rather than fetched —
   * `src` holds this year's, which is what an unset year should look like, and
   * anything that knows the wearer's year asks `decorationSrc` for theirs.
   */
  dated?: true;
}

/** Where each slot's artwork lives, since one of them does not just take an s. */
const FOLDER: Record<DecorationKind, string> = {
  banner: "banners",
  frame: "frames",
  trophy: "trophies",
};

const entry = (
  id: string,
  kind: DecorationKind,
  file: string,
  name: DecorationName,
  ink: "light" | "dark" = "light"
): Decoration => ({
  id,
  kind,
  src: `/decorations/${FOLDER[kind]}/${file}.svg`,
  labelKey: `decorations.${name}`,
  ...(kind === "banner" ? { ink } : null),
  ...(id in DEFAULT_TINTS ? { tint: DEFAULT_TINTS[id].length as 1 | 2 } : null),
  ...(DATED_DECORATIONS.has(id) ? { dated: true as const, src: gradArtwork(id) as string } : null),
});

/**
 * The frames whose colour is the wearer's, and what they are before anybody
 * chooses. The length is how many colours the frame takes, which is why the
 * catalog reads its `tint` from here rather than repeating the number.
 */
export const DEFAULT_TINTS: Readonly<Record<string, readonly string[]>> = {
  "core.gold": ["#d4a017"],
  "core.split": ["#1b5e32", "#f2c230"],
};

/** The catalog, by id — the app's own first, then every theme in order. */
export const DECORATIONS: Readonly<Record<string, Decoration>> = {
  // What ships with the app, and belongs to no theme.
  "core.aurora": entry("core.aurora", "banner", "core-aurora", "aurora"),
  "core.ember": entry("core.ember", "banner", "core-ember", "ember"),
  "core.parchment": entry("core.parchment", "banner", "core-parchment", "parchment", "dark"),
  "core.gold": entry("core.gold", "frame", "core-gold", "gold"),
  "core.split": entry("core.split", "frame", "core-split", "split"),
  "core.fan": entry("core.fan", "trophy", "core-fan", "fan"),

  "baseball.diamond": entry("baseball.diamond", "banner", "baseball-diamond", "diamond"),
  "baseball.stitching": entry("baseball.stitching", "frame", "baseball-stitching", "stitching"),
  "baseball.fastball": entry("baseball.fastball", "trophy", "baseball-fastball", "fastball"),

  "books.desk": entry("books.desk", "banner", "books-desk", "writingdesk", "dark"),
  "books.meadow": entry("books.meadow", "banner", "books-meadow", "goodplacetoread", "dark"),
  "books.shelf": entry("books.shelf", "banner", "books-shelf", "bookshelf", "dark"),
  "books.pages": entry("books.pages", "frame", "books-pages", "pages"),
  "books.spines": entry("books.spines", "frame", "books-spines", "spines"),
  "books.glasses": entry("books.glasses", "trophy", "books-glasses", "glasses"),
  "books.notebook": entry("books.notebook", "trophy", "books-notebook", "notebook"),
  "books.quill": entry("books.quill", "trophy", "books-quill", "quill"),
  "books.stack": entry("books.stack", "trophy", "books-stack", "stack"),
  "books.typewriter": entry("books.typewriter", "trophy", "books-typewriter", "typewriter"),

  "cinema.drivein": entry("cinema.drivein", "banner", "cinema-drivein", "drivein"),
  "cinema.marquee": entry("cinema.marquee", "banner", "cinema-marquee", "marquee"),
  "cinema.screening": entry("cinema.screening", "banner", "cinema-screening", "screening"),
  "cinema.filmstrip": entry("cinema.filmstrip", "frame", "cinema-filmstrip", "filmstrip"),
  "cinema.reel": entry("cinema.reel", "frame", "cinema-reel", "reel"),
  "cinema.chair": entry("cinema.chair", "trophy", "cinema-chair", "directorschair"),
  "cinema.clapper": entry("cinema.clapper", "trophy", "cinema-clapper", "clapper"),
  "cinema.popcorn": entry("cinema.popcorn", "trophy", "cinema-popcorn", "popcorn"),
  "cinema.projector": entry("cinema.projector", "trophy", "cinema-projector", "projector"),
  "cinema.ticket": entry("cinema.ticket", "trophy", "cinema-ticket", "ticket"),

  "drama.playhouse": entry("drama.playhouse", "banner", "drama-playhouse", "playhouse"),
  "drama.showtime": entry("drama.showtime", "banner", "drama-showtime", "showtime"),
  "drama.stage": entry("drama.stage", "banner", "drama-stage", "stage"),
  "drama.curtain": entry("drama.curtain", "frame", "drama-curtain", "curtain"),
  "drama.laurel": entry("drama.laurel", "frame", "drama-laurel", "laurel"),
  "drama.balcony": entry("drama.balcony", "trophy", "drama-balcony", "balcony"),
  "drama.dagger": entry("drama.dagger", "trophy", "drama-dagger", "dagger"),
  "drama.masks": entry("drama.masks", "trophy", "drama-masks", "masks"),
  "drama.skull": entry("drama.skull", "trophy", "drama-skull", "yorick"),

  "fencing.piste": entry("fencing.piste", "banner", "fencing-piste", "piste"),
  "fencing.blade": entry("fencing.blade", "frame", "fencing-blade", "blade"),
  "fencing.engarde": entry("fencing.engarde", "trophy", "fencing-engarde", "engarde"),

  "education.classroom": entry("education.classroom", "banner", "education-classroom", "classroom"),
  "education.gradbanner": entry("education.gradbanner", "banner", "education-gradbanner", "grad"),
  "education.lab": entry("education.lab", "banner", "education-lab", "sciencelab"),
  "education.commencement": entry(
    "education.commencement",
    "banner",
    "education-commencement",
    "commencement"
  ),
  "education.mortarboard": entry(
    "education.mortarboard",
    "frame",
    "education-mortarboard",
    "mortarboard"
  ),
  "education.crayons": entry("education.crayons", "frame", "education-crayons", "crayons"),
  "education.chalkboard": entry(
    "education.chalkboard",
    "frame",
    "education-chalkboard",
    "chalkboard"
  ),
  "education.apple": entry("education.apple", "trophy", "education-apple", "apple"),
  "education.blocks": entry("education.blocks", "trophy", "education-blocks", "alphabetblocks"),
  "education.bus": entry("education.bus", "trophy", "education-bus", "schoolbus"),
  "education.gradtrophy": entry(
    "education.gradtrophy",
    "trophy",
    "education-gradtrophy",
    "gradyear"
  ),
  "education.pencil": entry("education.pencil", "trophy", "education-pencil", "pencil"),
  "education.bunsen": entry("education.bunsen", "trophy", "education-bunsen", "bunsenburner"),
  "education.diploma": entry("education.diploma", "trophy", "education-diploma", "diploma"),
  "education.cap": entry("education.cap", "trophy", "education-cap", "graduationcap"),

  // Communities, raid nights, arcades, patch day, and the table.
  "gaming.arcade": entry("gaming.arcade", "banner", "gaming-arcade", "arcade"),
  "gaming.blocks": entry("gaming.blocks", "banner", "gaming-blocks", "blocks"),
  "gaming.tabletop": entry("gaming.tabletop", "banner", "gaming-tabletop", "gamesnight"),
  "gaming.buttons": entry("gaming.buttons", "frame", "gaming-buttons", "buttons"),
  "gaming.controller": entry("gaming.controller", "trophy", "gaming-controller", "controller"),
  "gaming.meeple": entry("gaming.meeple", "trophy", "gaming-meeple", "meeple"),
  "gaming.ore": entry("gaming.ore", "trophy", "gaming-ore", "oreblock"),

  "gridiron.endzone": entry("gridiron.endzone", "banner", "gridiron-endzone", "endzone"),
  "gridiron.laces": entry("gridiron.laces", "frame", "gridiron-laces", "laces"),
  "gridiron.pigskin": entry("gridiron.pigskin", "trophy", "gridiron-pigskin", "pigskin"),

  "hockey.rink": entry("hockey.rink", "banner", "hockey-rink", "rink"),
  "hockey.faceoff": entry("hockey.faceoff", "frame", "hockey-faceoff", "faceoff"),
  "hockey.puck": entry("hockey.puck", "trophy", "hockey-puck", "puck"),

  "hoops.court": entry("hoops.court", "banner", "hoops-court", "court"),
  "hoops.seams": entry("hoops.seams", "frame", "hoops-seams", "seams"),
  "hoops.swish": entry("hoops.swish", "trophy", "hoops-swish", "swish"),

  // Bands, choirs, anyone who books a room and plugs in.
  "music.festival": entry("music.festival", "banner", "music-festival", "festival"),
  "music.sheet": entry("music.sheet", "banner", "music-sheet", "sheetmusic", "dark"),
  "music.soundcheck": entry("music.soundcheck", "banner", "music-soundcheck", "soundcheck"),
  "music.headphones": entry("music.headphones", "frame", "music-headphones", "headphones"),
  "music.mixtape": entry("music.mixtape", "frame", "music-mixtape", "mixtape"),
  "music.stagelights": entry("music.stagelights", "frame", "music-stagelights", "stagelights"),
  "music.vinyl": entry("music.vinyl", "frame", "music-vinyl", "vinyl"),
  "music.cassette": entry("music.cassette", "trophy", "music-cassette", "cassette"),
  "music.drums": entry("music.drums", "trophy", "music-drums", "drums"),
  "music.guitar": entry("music.guitar", "trophy", "music-guitar", "guitar"),
  "music.keys": entry("music.keys", "trophy", "music-keys", "keys"),
  "music.mic": entry("music.mic", "trophy", "music-mic", "microphone"),
  "music.sax": entry("music.sax", "trophy", "music-sax", "saxophone"),
  "music.turntable": entry("music.turntable", "trophy", "music-turntable", "turntable"),
  "music.violin": entry("music.violin", "trophy", "music-violin", "violin"),

  "nature.beach": entry("nature.beach", "banner", "nature-beach", "beach"),
  "nature.desert": entry("nature.desert", "banner", "nature-desert", "desert"),
  "nature.lake": entry("nature.lake", "banner", "nature-lake", "lake"),
  "nature.nightsky": entry("nature.nightsky", "banner", "nature-nightsky", "nightsky"),
  "nature.pines": entry("nature.pines", "frame", "nature-pines", "pines"),
  "nature.ridge": entry("nature.ridge", "frame", "nature-ridge", "ridge"),
  "nature.backpack": entry("nature.backpack", "trophy", "nature-backpack", "backpack"),
  "nature.campfire": entry("nature.campfire", "trophy", "nature-campfire", "campfire"),
  "nature.mountain": entry("nature.mountain", "trophy", "nature-mountain", "mountain"),
  "nature.tent": entry("nature.tent", "trophy", "nature-tent", "tent"),

  "pets.catnap": entry("pets.catnap", "banner", "pets-catnap", "catnap"),
  "pets.fetch": entry("pets.fetch", "banner", "pets-fetch", "fetch"),
  "pets.paddock": entry("pets.paddock", "banner", "pets-paddock", "paddock"),
  "pets.catears": entry("pets.catears", "frame", "pets-catears", "catears"),
  "pets.collar": entry("pets.collar", "frame", "pets-collar", "collar"),
  "pets.dogears": entry("pets.dogears", "frame", "pets-dogears", "dogears"),
  "pets.ratears": entry("pets.ratears", "frame", "pets-ratears", "ratears"),
  "pets.bunny": entry("pets.bunny", "trophy", "pets-bunny", "rabbit"),
  "pets.cat": entry("pets.cat", "trophy", "pets-cat", "cat"),
  "pets.dog": entry("pets.dog", "trophy", "pets-dog", "dog"),
  "pets.hamster": entry("pets.hamster", "trophy", "pets-hamster", "hamster"),
  "pets.horse": entry("pets.horse", "trophy", "pets-horse", "horse"),
  "pets.lizard": entry("pets.lizard", "trophy", "pets-lizard", "lizard"),
  "pets.paw": entry("pets.paw", "trophy", "pets-paw", "pawprint"),
  "pets.rat": entry("pets.rat", "trophy", "pets-rat", "rat"),
  "pets.snake": entry("pets.snake", "trophy", "pets-snake", "snake"),

  // Foragers, houseplant keepers, and anyone who stops a walk to look at a log.
  "plants.grove": entry("plants.grove", "banner", "plants-grove", "grove"),
  "plants.overgrown": entry("plants.overgrown", "banner", "plants-overgrown", "overgrown"),
  "plants.windowsill": entry("plants.windowsill", "banner", "plants-windowsill", "windowsill"),
  "plants.nest": entry("plants.nest", "frame", "plants-nest", "nest"),
  "plants.rosette": entry("plants.rosette", "frame", "plants-rosette", "rosette"),
  "plants.vines": entry("plants.vines", "frame", "plants-vines", "vines"),
  "plants.monstera": entry("plants.monstera", "trophy", "plants-monstera", "monstera"),
  "plants.morel": entry("plants.morel", "trophy", "plants-morel", "morel"),
  "plants.succulent": entry("plants.succulent", "trophy", "plants-succulent", "succulent"),

  // Labs, field stations, reading groups with a whiteboard.
  "science.lab": entry("science.lab", "banner", "science-lab", "labbench"),
  "science.observatory": entry(
    "science.observatory",
    "banner",
    "science-observatory",
    "observatory"
  ),
  "science.helix": entry("science.helix", "frame", "science-helix", "helix"),
  "science.orbital": entry("science.orbital", "frame", "science-orbital", "orbital"),
  "science.ammonite": entry("science.ammonite", "trophy", "science-ammonite", "ammonite"),
  "science.benzene": entry("science.benzene", "trophy", "science-benzene", "benzene"),
  "science.dividers": entry("science.dividers", "trophy", "science-dividers", "dividers"),
  "science.dna": entry("science.dna", "trophy", "science-dna", "dna"),
  "science.flask": entry("science.flask", "trophy", "science-flask", "flask"),
  "science.hammer": entry("science.hammer", "trophy", "science-hammer", "rockhammer"),
  "science.magnet": entry("science.magnet", "trophy", "science-magnet", "magnet"),
  "science.microscope": entry("science.microscope", "trophy", "science-microscope", "microscope"),

  "soccer.floodlights": entry("soccer.floodlights", "banner", "soccer-floodlights", "floodlights"),
  "soccer.panels": entry("soccer.panels", "frame", "soccer-panels", "panels"),
  "soccer.matchball": entry("soccer.matchball", "trophy", "soccer-matchball", "matchball"),

  // The group that keeps October in the calendar all year.
  "spooky.hollow": entry("spooky.hollow", "banner", "spooky-hollow", "hollow"),
  "spooky.skeletons": entry("spooky.skeletons", "banner", "spooky-skeletons", "skeletons"),
  "spooky.witching": entry("spooky.witching", "banner", "spooky-witching", "witchinghour"),
  "spooky.bones": entry("spooky.bones", "frame", "spooky-bones", "bones"),
  "spooky.ironwork": entry("spooky.ironwork", "frame", "spooky-ironwork", "ironwork"),
  "spooky.web": entry("spooky.web", "frame", "spooky-web", "cobweb"),
  "spooky.bat": entry("spooky.bat", "trophy", "spooky-bat", "bat"),
  "spooky.ghost": entry("spooky.ghost", "trophy", "spooky-ghost", "ghost"),
  "spooky.lantern": entry("spooky.lantern", "trophy", "spooky-lantern", "lantern"),

  "tea.garden": entry("tea.garden", "banner", "tea-garden", "teagarden"),
  "tea.party": entry("tea.party", "banner", "tea-party", "madteaparty", "dark"),
  "tea.service": entry("tea.service", "banner", "tea-service", "teaservice"),
  "tea.porcelain": entry("tea.porcelain", "frame", "tea-porcelain", "porcelain"),
  "tea.teacup": entry("tea.teacup", "frame", "tea-teacup", "cupoftea"),
  "tea.bag": entry("tea.bag", "trophy", "tea-bag", "teabag"),
  "tea.cup": entry("tea.cup", "trophy", "tea-cup", "teacup"),
  "tea.matcha": entry("tea.matcha", "trophy", "tea-matcha", "matcha"),
  "tea.pot": entry("tea.pot", "trophy", "tea-pot", "teapot"),

  "tennis.clay": entry("tennis.clay", "banner", "tennis-clay", "clay", "dark"),
  "tennis.strings": entry("tennis.strings", "frame", "tennis-strings", "strings"),
  "tennis.ace": entry("tennis.ace", "trophy", "tennis-ace", "tennisace"),

  "travel.landmarks": entry("travel.landmarks", "banner", "travel-landmarks", "landmarks"),
  "travel.trainride": entry("travel.trainride", "banner", "travel-train", "bytrain"),
  "travel.colosseum": entry("travel.colosseum", "frame", "travel-colosseum", "colosseum"),
  "travel.eiffel": entry("travel.eiffel", "frame", "travel-eiffel", "eiffeltower"),
  "travel.goldengate": entry("travel.goldengate", "frame", "travel-goldengate", "goldengate"),
  "travel.torii": entry("travel.torii", "frame", "travel-torii", "torii"),
  "travel.bicycle": entry("travel.bicycle", "trophy", "travel-bicycle", "bicycle"),
  "travel.car": entry("travel.car", "trophy", "travel-car", "car"),
  "travel.globe": entry("travel.globe", "trophy", "travel-globe", "globe"),
  "travel.plane": entry("travel.plane", "trophy", "travel-plane", "plane"),
  "travel.ship": entry("travel.ship", "trophy", "travel-ship", "ship"),
  "travel.train": entry("travel.train", "trophy", "travel-train", "train"),

  "ttrpg.dicetower": entry("ttrpg.dicetower", "banner", "ttrpg-dicetower", "dicetower"),
  "ttrpg.natural20": entry("ttrpg.natural20", "frame", "ttrpg-natural20", "natural20"),
  "ttrpg.d20": entry("ttrpg.d20", "trophy", "ttrpg-d20", "d20"),

  "volleyball.beach": entry("volleyball.beach", "banner", "volleyball-beach", "beach"),
  "volleyball.net": entry("volleyball.net", "frame", "volleyball-net", "net"),
  "volleyball.spike": entry("volleyball.spike", "trophy", "volleyball-spike", "spike"),

  "winter.flurry": entry("winter.flurry", "banner", "winter-flurry", "flurry"),
  "winter.hearth": entry("winter.hearth", "banner", "winter-hearth", "hearth"),
  "winter.lights": entry("winter.lights", "banner", "winter-lights", "christmaslights"),
  "winter.santa": entry("winter.santa", "banner", "winter-santa", "christmaseve"),
  "winter.icicles": entry("winter.icicles", "frame", "winter-icicles", "icicles"),
  "winter.poinsettia": entry("winter.poinsettia", "frame", "winter-poinsettia", "poinsettia"),
  "winter.wreath": entry("winter.wreath", "frame", "winter-wreath", "wreath"),
  "winter.bauble": entry("winter.bauble", "trophy", "winter-bauble", "bauble"),
  "winter.cocoa": entry("winter.cocoa", "trophy", "winter-cocoa", "cocoa"),
  "winter.snowflake": entry("winter.snowflake", "trophy", "winter-snowflake", "snowflake"),
  "winter.snowman": entry("winter.snowman", "trophy", "winter-snowman", "snowman"),

  "zen.garden": entry("zen.garden", "banner", "zen-garden", "garden"),
  "zen.sand": entry("zen.sand", "banner", "zen-sand", "rakedsand"),
  "zen.enso": entry("zen.enso", "frame", "zen-enso", "enso"),
  "zen.rake": entry("zen.rake", "frame", "zen-rake", "rakelines"),
  "zen.bell": entry("zen.bell", "trophy", "zen-bell", "singingbowl"),
  "zen.cairn": entry("zen.cairn", "trophy", "zen-cairn", "stones"),
  "zen.incense": entry("zen.incense", "trophy", "zen-incense", "incense"),
  "zen.koi": entry("zen.koi", "trophy", "zen-koi", "koi"),
  "zen.lotus": entry("zen.lotus", "trophy", "zen-lotus", "lotus"),
};

/** The decoration this id names, if this build has it and it is of that kind. */
export const resolveDecoration = (
  id: string | null | undefined,
  kind: DecorationKind
): Decoration | undefined => {
  if (!id) return undefined;
  const found = DECORATIONS[id];
  return found?.kind === kind ? found : undefined;
};

/**
 * Where to fetch a decoration's artwork, for a wearer whose year is known.
 *
 * Every decoration but the two dated ones ignores the year and hands back the
 * file it always had, so a caller with no year to give loses nothing by asking.
 */
export const decorationSrc = (decoration: Decoration, year?: number | null): string =>
  (decoration.dated ? gradArtwork(decoration.id, year) : undefined) ?? decoration.src;

/** The trophies a profile is wearing that this build can draw, in the order worn. */
export const resolveTrophies = (
  decorations: ProfileDecorationsOutput | null | undefined
): Decoration[] =>
  (decorations?.trophies ?? [])
    .map((id) => resolveDecoration(id, "trophy"))
    .filter((trophy): trophy is Decoration => Boolean(trophy));
