#!/usr/bin/env node
/**
 * Refresh this copy of Initiative's UI kit, or check that it is current.
 *
 * The kit is written in Initiative (frontend/src/ui) and copied whole into each
 * plug-in that draws with it, with the generated API types it reads and its
 * words. Nobody edits the copy: this script is how it moves, and each plug-in's
 * check runs it with --check. It travels with the copy, so every plug-in runs
 * the same one. Run it from the plug-in's frontend folder (the one holding
 * package.json and src/), where `@/` resolves to src/.
 *
 *   node src/ui/refresh.mjs --ref v0.80.0          copy the kit from an Initiative tag
 *   node src/ui/refresh.mjs --from ../initiative   copy it from a local checkout
 *   node src/ui/refresh.mjs --check                is the copy the stamped revision's?
 *
 * --check fails when a copied file differs from the stamped revision's, or when
 * the plug-in declares a different version of an npm package the kit imports
 * than Initiative does. It takes --from too, to check against a checkout.
 */
import { execFileSync } from "node:child_process";
import {
  existsSync,
  mkdirSync,
  mkdtempSync,
  readdirSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";

const ARCHIVE = "https://codeload.github.com/beyonders-studio/initiative/tar.gz";
const KIT = "src/ui";
const SCHEMAS = "src/api/generated/initiativeAPI.schemas.ts";
const LOCALES = "public/locales";
// The namespaces the kit reads its words from.
const NAMESPACES = ["ui", "editor"];
// Which Initiative revision the copy came from. Not part of the copy itself.
const STAMP = `${KIT}/.initiative-ref`;

const isTest = (file) => /\.test\.[cm]?[jt]sx?$/.test(file);

const walk = (root, dir = root) =>
  readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = path.join(dir, entry.name);
    return entry.isDirectory() ? walk(root, full) : [path.relative(root, full)];
  });

/** The kit's words in each language a frontend folder has. */
const wordsOf = (frontend) =>
  (existsSync(path.join(frontend, LOCALES)) ? readdirSync(path.join(frontend, LOCALES)) : [])
    .flatMap((language) =>
      NAMESPACES.map((namespace) => `${LOCALES}/${language}/${namespace}.json`)
    )
    .filter((name) => existsSync(path.join(frontend, name)));

/** The files that make up the kit, keyed by their path in a frontend folder. */
const kitOf = (frontend) => {
  if (!existsSync(path.join(frontend, KIT))) throw new Error(`${frontend} has no ${KIT}`);
  const files = new Map();
  for (const file of walk(path.join(frontend, KIT))) {
    const name = path.posix.join(KIT, file.split(path.sep).join("/"));
    if (!isTest(file) && name !== STAMP) files.set(name, readFileSync(path.join(frontend, name)));
  }
  for (const name of [SCHEMAS, ...wordsOf(frontend)]) {
    if (existsSync(path.join(frontend, name)))
      files.set(name, readFileSync(path.join(frontend, name)));
  }
  return files;
};

/** The npm packages the kit imports, its stylesheet's included, by name. */
const packagesOf = (files) => {
  const names = new Set();
  for (const [name, body] of files) {
    if (!/\.(?:[cm]?[jt]sx?|css)$/.test(name)) continue;
    const specs = body.toString().matchAll(/(?:from|import|@plugin)\s*\(?\s*["']([^"']+)["']/g);
    for (const [, spec] of specs) {
      if (spec.startsWith(".") || spec.startsWith("@/") || spec.startsWith("node:")) continue;
      const parts = spec.split("/");
      names.add(spec.startsWith("@") ? `${parts[0]}/${parts[1]}` : parts[0]);
    }
  }
  return names;
};

const declared = (frontend) => {
  const manifest = JSON.parse(readFileSync(path.join(frontend, "package.json"), "utf8"));
  return { ...manifest.devDependencies, ...manifest.dependencies };
};

/** Initiative's frontend folder at a revision, and the revision to stamp. */
const source = async (args) => {
  if (args.from) {
    const root = path.resolve(args.from);
    const revision = execFileSync("git", ["-C", root, "rev-parse", "HEAD"], { encoding: "utf8" });
    return { frontend: path.join(root, "frontend"), ref: revision.trim(), cleanup: () => {} };
  }
  const dir = mkdtempSync(path.join(tmpdir(), "initiative-ui-"));
  const archive = path.join(dir, "initiative.tar.gz");
  const response = await fetch(`${ARCHIVE}/${args.ref}`);
  if (!response.ok)
    throw new Error(`Initiative ${args.ref}: ${response.status} ${response.statusText}`);
  writeFileSync(archive, Buffer.from(await response.arrayBuffer()));
  execFileSync("tar", ["-xzf", archive, "-C", dir, "--strip-components=1"]);
  return {
    frontend: path.join(dir, "frontend"),
    ref: args.ref,
    cleanup: () => rmSync(dir, { recursive: true, force: true }),
  };
};

const parse = (argv) => {
  const args = { check: false };
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (arg === "--check") args.check = true;
    else if (arg === "--ref" || arg === "--from") args[arg.slice(2)] = argv[++index];
    else throw new Error(`unknown argument: ${arg}`);
  }
  if (args.check && !args.ref && !args.from) {
    args.ref = readFileSync(STAMP, "utf8").trim();
  }
  if (!args.ref && !args.from) throw new Error("give --ref, --from or --check");
  return args;
};

const check = (from) => {
  const wanted = kitOf(from.frontend);
  const problems = [];
  const held = existsSync(KIT) ? kitOf(".") : new Map();
  for (const [name, body] of wanted) {
    const mine = held.get(name);
    if (!mine) problems.push(`${name} is missing`);
    else if (!mine.equals(body)) problems.push(`${name} differs from Initiative's`);
  }
  for (const name of held.keys()) {
    if (!wanted.has(name)) problems.push(`${name} is not part of Initiative's kit`);
  }
  const theirs = declared(from.frontend);
  const mine = declared(".");
  for (const name of [...packagesOf(wanted)].sort()) {
    if (!(name in theirs)) continue; // a package Node or the bundler provides
    if (mine[name] !== theirs[name]) {
      problems.push(
        `package.json has ${name} ${mine[name] ?? "missing"}; the kit is built with ${theirs[name]}`
      );
    }
  }
  return problems;
};

/** Replace the copy, reading the new one in full before anything is removed. */
const copy = (from) => {
  const files = kitOf(from.frontend);
  rmSync(KIT, { recursive: true, force: true });
  for (const name of wordsOf(".")) rmSync(name);
  for (const [name, body] of files) {
    mkdirSync(path.dirname(name), { recursive: true });
    writeFileSync(name, body);
  }
  writeFileSync(STAMP, `${from.ref}\n`);
};

const args = parse(process.argv.slice(2));
const from = await source(args);
try {
  if (args.check) {
    const problems = check(from);
    for (const problem of problems) console.error(problem);
    if (problems.length > 0) {
      console.error(`The UI kit differs from Initiative ${from.ref}: run src/ui/refresh.mjs.`);
      process.exitCode = 1;
    }
  } else {
    copy(from);
    console.log(`Copied the UI kit from Initiative ${from.ref}.`);
  }
} finally {
  from.cleanup();
}
