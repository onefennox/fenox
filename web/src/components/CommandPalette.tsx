import { useQuery } from "@tanstack/react-query";
import {
  ChevronRight,
  FolderKanban,
  LayoutDashboard,
  Moon,
  Play,
  Plus,
  Search,
  Settings as SettingsIcon,
  Smartphone,
  Sun,
  Wrench,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { keys, listDevices, listProjects, listRuns } from "@/api/queries";
import { cn } from "@/lib/format";
import { useUi } from "@/lib/ui-state";
import { useRecentProjects } from "@/hooks/useRecentProjects";

interface Command {
  id: string;
  label: string;
  hint?: string;
  icon: LucideIcon;
  group: string;
  run: () => void;
  keywords?: string;
}

/**
 * Subsequence match: "dvc" finds "Devices". Cheap, and it forgives the way
 * people actually type when they are in a hurry.
 */
function matches(query: string, text: string): boolean {
  const haystack = text.toLowerCase();
  const needle = query.toLowerCase().trim();
  if (!needle) return true;
  if (haystack.includes(needle)) return true;
  let index = 0;
  for (const char of needle) {
    index = haystack.indexOf(char, index);
    if (index === -1) return false;
    index += 1;
  }
  return true;
}

export function CommandPalette() {
  const open = useUi((state) => state.paletteOpen);
  const setOpen = useUi((state) => state.setPaletteOpen);
  const toggleTheme = useUi((state) => state.toggleTheme);
  const theme = useUi((state) => state.theme);
  const navigate = useNavigate();
  const projectsRevealed = useUi((state) => state.projectsRevealed);
  const recentProjects = useRecentProjects();
  const [query, setQuery] = useState("");
  const [cursor, setCursor] = useState(0);
  const listRef = useRef<HTMLDivElement>(null);

  const devices = useQuery({ queryKey: keys.devices, queryFn: listDevices, enabled: open });
  const projects = useQuery({ queryKey: keys.projects, queryFn: listProjects, enabled: open });
  const runs = useQuery({ queryKey: keys.runs, queryFn: listRuns, enabled: open });

  // Ctrl/Cmd+K opens it from anywhere, which is the whole point.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setOpen(!useUi.getState().paletteOpen);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [setOpen]);

  useEffect(() => {
    if (open) {
      setQuery("");
      setCursor(0);
    }
  }, [open]);

  const close = (then?: () => void) => {
    setOpen(false);
    then?.();
  };

  const commands = useMemo<Command[]>(() => {
    const go = (to: string) => () => close(() => navigate(to));
    const items: Command[] = [
      { id: "nav-dash", label: "Dashboard", icon: LayoutDashboard, group: "Go to", run: go("/") },
      { id: "nav-devices", label: "Devices", icon: Smartphone, group: "Go to", run: go("/devices") },
      { id: "nav-connect", label: "Connect a device", icon: Plus, group: "Go to", run: go("/connect") },
      { id: "nav-projects", label: "Projects", icon: FolderKanban, group: "Go to", run: go("/projects") },
      { id: "nav-runs", label: "Runs", icon: Play, group: "Go to", run: go("/runs") },
      { id: "nav-system", label: "System", icon: Wrench, group: "Go to", run: go("/system") },
      { id: "nav-settings", label: "Settings", icon: SettingsIcon, group: "Go to", run: go("/settings") },
      {
        id: "act-theme",
        label: theme === "dark" ? "Switch to light theme" : "Switch to dark theme",
        icon: theme === "dark" ? Sun : Moon,
        group: "Actions",
        run: () => close(toggleTheme),
      },
    ];

    for (const device of devices.data?.devices ?? []) {
      items.push({
        id: `device-${device.id}`,
        label: device.id,
        hint: device.model ?? device.type,
        icon: Smartphone,
        group: "Devices",
        keywords: `${device.type} ${device.model ?? ""} ${device.online ? "online" : "offline"}`,
        run: go(`/devices/${encodeURIComponent(device.id)}`),
      });
    }

    // Same rule as the Projects page: only pinned and recent unless the owner
    // has explicitly revealed the rest, so opening the palette while someone is
    // watching is not a leak.
    const catalogue = projects.data?.projects ?? {};
    const allowed = projectsRevealed
      ? Object.keys(catalogue)
      : Object.keys(catalogue).filter((name) => catalogue[name].pinned || recentProjects.includes(name));

    for (const name of allowed) {
      items.push({
        id: `project-${name}`,
        label: name,
        hint: "project",
        icon: FolderKanban,
        group: "Projects",
        run: go(`/projects/${encodeURIComponent(name)}`),
      });
    }

    for (const run of (runs.data?.runs ?? []).slice(0, 8)) {
      items.push({
        id: `run-${run.id}`,
        label: `${run.project} on ${run.device}`,
        hint: run.status,
        icon: Play,
        group: "Runs",
        run: go(`/runs/${run.id}`),
      });
    }

    return items;
  }, [devices.data, projects.data, runs.data, theme, toggleTheme, navigate, projectsRevealed, recentProjects]);

  const filtered = useMemo(
    () => commands.filter((command) => matches(query, `${command.label} ${command.keywords ?? ""} ${command.group}`)),
    [commands, query],
  );

  useEffect(() => setCursor(0), [query]);

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
      if (event.key === "ArrowDown") {
        event.preventDefault();
        setCursor((current) => Math.min(current + 1, filtered.length - 1));
      }
      if (event.key === "ArrowUp") {
        event.preventDefault();
        setCursor((current) => Math.max(current - 1, 0));
      }
      if (event.key === "Enter") {
        event.preventDefault();
        filtered[cursor]?.run();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, filtered, cursor, setOpen]);

  // Keep the highlighted row in view when arrowing past the fold.
  useEffect(() => {
    listRef.current?.querySelector<HTMLElement>('[data-active="true"]')?.scrollIntoView({ block: "nearest" });
  }, [cursor]);

  if (!open) return null;

  let currentGroup = "";

  return (
    <div
      className="fixed inset-0 z-[70] flex items-start justify-center bg-black/50 p-4 pt-[12vh] backdrop-blur-[2px]"
      onClick={() => setOpen(false)}
      role="presentation"
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Command palette"
        onClick={(event) => event.stopPropagation()}
        className="animate-in flex max-h-[60vh] w-full max-w-xl flex-col overflow-hidden rounded-[var(--radius-xl)] border border-[var(--color-border-strong)] bg-[var(--color-panel)] shadow-2xl"
      >
        <div className="flex items-center gap-2.5 border-b border-[var(--color-border)] px-4">
          <Search size={15} className="shrink-0 text-[var(--color-subtle)]" />
          <input
            autoFocus
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search devices, projects, pages…"
            className="h-12 flex-1 bg-transparent text-sm text-[var(--color-text)] outline-none placeholder:text-[var(--color-subtle)]"
          />
          <kbd className="hidden rounded border border-[var(--color-border)] px-1.5 py-0.5 text-[10px] text-[var(--color-subtle)] sm:block">
            esc
          </kbd>
        </div>

        <div ref={listRef} className="scroll-thin min-h-0 flex-1 overflow-y-auto py-1.5">
          {filtered.length === 0 ? (
            <p className="px-4 py-8 text-center text-sm text-[var(--color-muted)]">Nothing matches “{query}”.</p>
          ) : (
            filtered.map((command, index) => {
              const header = command.group !== currentGroup ? command.group : null;
              currentGroup = command.group;
              const active = index === cursor;
              return (
                <div key={command.id}>
                  {header ? (
                    <p className="px-4 pt-2.5 pb-1 text-[10px] font-semibold tracking-wider text-[var(--color-subtle)] uppercase">
                      {header}
                    </p>
                  ) : null}
                  <button
                    data-active={active}
                    onMouseEnter={() => setCursor(index)}
                    onClick={command.run}
                    className={cn(
                      "flex w-full cursor-pointer items-center gap-3 px-4 py-2 text-left text-sm transition-colors",
                      active ? "bg-[var(--color-panel-hover)] text-[var(--color-text)]" : "text-[var(--color-muted)]",
                    )}
                  >
                    <command.icon size={15} className={active ? "text-[var(--color-accent)]" : ""} />
                    <span className="flex-1 truncate">{command.label}</span>
                    {command.hint ? (
                      <span className="shrink-0 text-xs text-[var(--color-subtle)]">{command.hint}</span>
                    ) : null}
                    {active ? <ChevronRight size={13} className="shrink-0 text-[var(--color-subtle)]" /> : null}
                  </button>
                </div>
              );
            })
          )}
        </div>
      </div>
    </div>
  );
}
