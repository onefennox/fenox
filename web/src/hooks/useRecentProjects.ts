import { useEffect, useState } from "react";

/**
 * Recently opened projects, newest first.
 *
 * Kept in the browser rather than the hub: "recent" is a property of this
 * person on this machine, not of the project. Pinning is the deliberate,
 * server-side counterpart — this is the automatic half.
 */
const KEY = "fenox.projects.recent";
const EVENT = "fenox:recent-projects";
const LIMIT = 5;

function read(): string[] {
  try {
    const raw = localStorage.getItem(KEY);
    return raw ? (JSON.parse(raw) as string[]).filter((name) => typeof name === "string") : [];
  } catch {
    return [];
  }
}

/** Call when a project is opened. */
export function rememberProject(name: string): void {
  if (!name) return;
  try {
    const next = [name, ...read().filter((entry) => entry !== name)].slice(0, LIMIT);
    localStorage.setItem(KEY, JSON.stringify(next));
    window.dispatchEvent(new Event(EVENT));
  } catch {
    // Private mode, or storage disabled: recency is a convenience.
  }
}

/** Call when a project is removed, so a dead name does not linger. */
export function forgetProject(name: string): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(read().filter((entry) => entry !== name)));
    window.dispatchEvent(new Event(EVENT));
  } catch {
    // As above.
  }
}

export function useRecentProjects(): string[] {
  const [recent, setRecent] = useState<string[]>(read);

  useEffect(() => {
    const update = () => setRecent(read());
    window.addEventListener(EVENT, update);
    window.addEventListener("storage", update);
    return () => {
      window.removeEventListener(EVENT, update);
      window.removeEventListener("storage", update);
    };
  }, []);

  return recent;
}
