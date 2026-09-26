#!/usr/bin/env node
/*
 * fenox — npm entry point.
 *
 * Fenox is a Python application. This launcher exists so it can be installed
 * with the one command most developers already have:
 *
 *     npm install -g fenox
 *
 * It does not reimplement anything. On the first run it makes sure `uv` is
 * present (uv can fetch and manage a Python on its own, so no separate Python
 * install is required), installs Fenox with `uv tool install`, and from then on
 * it just executes the installed binary. Every run after that is a single exec,
 * so the cost is one node start-up and nothing else.
 *
 * Ordering matters: an existing Fenox always wins. Someone who installed with
 * the shell installer and later ran `npm install -g fenox` must keep the binary
 * they already have, not have it silently replaced underneath them.
 */
"use strict";

const { spawnSync, spawn } = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const REPO = "https://github.com/onefennox/fenox.git";
const PACKAGE = "fenox";

const isWindows = process.platform === "win32";
const binName = isWindows ? "fenox.exe" : "fenox";

function isExecutable(candidate) {
  try {
    fs.accessSync(candidate, fs.constants.X_OK);
    return fs.statSync(candidate).isFile();
  } catch {
    return false;
  }
}

/** Where `uv` keeps managed tool environments. */
function uvToolsDir() {
  if (isWindows) {
    const local = process.env.LOCALAPPDATA || path.join(os.homedir(), "AppData", "Local");
    return path.join(local, "uv", "tools");
  }
  const data = process.env.XDG_DATA_HOME || path.join(os.homedir(), ".local", "share");
  return path.join(data, "uv", "tools");
}

/** The real binary inside uv's own tool environment. */
function fromUvTools() {
  const base = path.join(uvToolsDir(), PACKAGE, "bin");
  const candidate = path.join(base, binName);
  if (isExecutable(candidate)) return candidate;
  // Windows puts console-script shims in Scripts, not bin.
  const windows = path.join(uvToolsDir(), PACKAGE, "Scripts", binName);
  return isExecutable(windows) ? windows : null;
}

/** An explicitly configured binary always wins. */
function fromEnvironment() {
  const configured = process.env.FENOX_BIN;
  return configured && isExecutable(configured) ? configured : null;
}

/**
 * This launcher, by its real path.
 *
 * npm's global prefix here is ~/.local, which is the same directory uv links
 * tool binaries into — so `which fenox` can resolve to *this* npm shim. Taking
 * that as the answer would re-exec ourselves on every call, forever.
 */
function selfPaths() {
  const here = fs.realpathSync(__filename);
  return new Set([here, path.resolve(__filename)]);
}

/** A `fenox` already on PATH, unless that is this very shim. */
function fromPath() {
  const finder = isWindows ? "where" : "which";
  const result = spawnSync(finder, [PACKAGE], { encoding: "utf8", shell: isWindows });
  if (result.status !== 0 || !result.stdout) return null;
  const mine = selfPaths();
  for (const line of result.stdout.split(/\r?\n/)) {
    const candidate = line.trim();
    if (!candidate || !isExecutable(candidate)) continue;
    try {
      if (mine.has(fs.realpathSync(candidate))) continue;
    } catch {
      continue;
    }
    return candidate;
  }
  return null;
}

function whichUv() {
  const result = spawnSync(isWindows ? "where" : "which", ["uv"], { encoding: "utf8", shell: isWindows });
  return result.status === 0 && (result.stdout || "").trim().split(/\r?\n/)[0];
}

/**
 * Fetch uv when it is not installed. Kept to the official installer and only
 * ever run on an explicit first run, never silently on an upgrade.
 */
function installUv() {
  const url = "https://astral.sh/uv/install.sh";
  if (isWindows) {
    process.stderr.write(
      "fenox needs uv to manage its own Python.\n" +
        "Install it with:  powershell -c \"irm https://astral.sh/uv/install.ps1 | iex\"\n" +
        "then run this command again.\n",
    );
    return null;
  }
  process.stderr.write("Installing uv (Fenox uses it to manage its own Python)...\n");
  const result = spawnSync("sh", ["-c", `curl -LsSf ${url} | sh`], { stdio: "inherit" });
  if (result.status !== 0) {
    process.stderr.write(
      "Could not install uv automatically. Install it with:\n" +
        "  curl -LsSf https://astral.sh/uv/install.sh | sh\n" +
        "then run this command again.\n",
    );
    return null;
  }
  return whichUv();
}

function installWithUv(uv) {
  process.stderr.write(`Installing ${PACKAGE} from ${REPO} (first run only)...\n`);
  const result = spawnSync(uv, ["tool", "install", `${PACKAGE} @ git+${REPO}`], { stdio: "inherit" });
  return result.status === 0;
}

function resolve() {
  return fromEnvironment() || fromPath() || fromUvTools();
}

function main() {
  const args = process.argv.slice(2);
  const already = resolve();
  if (already) {
    // Replace this process so the app owns stdin/stdout and signals, which
    // matters for the live terminal a Flutter run is streamed into.
    const child = spawn(already, args, { stdio: "inherit" });
    child.on("exit", (code, signal) => {
      if (signal) process.kill(process.pid, signal);
      else process.exit(code ?? 0);
    });
    child.on("error", (error) => {
      process.stderr.write(`Could not start ${already}: ${error.message}\n`);
      process.exit(1);
    });
    return;
  }

  const uv = whichUv() || installUv();
  if (!uv || !installWithUv(uv)) process.exit(1);

  const installed = resolve();
  if (!installed) {
    process.stderr.write(
      `Installed, but ${PACKAGE} is not on your PATH.\n` +
        `It is at: ${path.join(uvToolsDir(), PACKAGE, "bin", binName)}\n` +
        "Add that directory to your PATH and open a new terminal.\n",
    );
    process.exit(1);
  }
  main(); // re-resolve now that it exists
}

main();
