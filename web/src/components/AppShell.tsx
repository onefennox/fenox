import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  ChevronsLeft,
  ChevronsRight,
  Cog,
  FolderKanban,
  Hammer,
  LayoutDashboard,
  LogOut,
  Menu,
  Moon,
  Play,
  Plus,
  Search,
  Smartphone,
  Sun,
  Wrench,
  X,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";

import { getSystem, keys, listBuilds, listDevices, listRuns, logout } from "@/api/queries";
import { useLive } from "@/hooks/useLive";
import { cn } from "@/lib/format";
import { useUi } from "@/lib/ui-state";
import { CommandPalette } from "./CommandPalette";
import { DeviceRail } from "./DeviceRail";

interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
  end?: boolean;
  badge?: number;
}

interface NavGroup {
  title: string;
  items: NavItem[];
}

const ACTIVE_RUN_STATUSES = new Set(["starting", "running", "stopping"]);

/** A breadcrumb trail from the path, so the header says where you are. */
function crumbs(pathname: string): Array<{ label: string; to: string }> {
  const parts = pathname.split("/").filter(Boolean);
  if (parts.length === 0) return [{ label: "Dashboard", to: "/" }];
  const root = parts[0];
  const labels: Record<string, string> = {
    devices: "Devices",
    connect: "Connect",
    projects: "Projects",
    runs: "Runs",
    system: "System",
    settings: "Settings",
  };
  const trail = [{ label: labels[root] ?? "Fenox", to: `/${root}` }];
  if (parts[1]) trail.push({ label: decodeURIComponent(parts[1]), to: pathname });
  return trail;
}

export function AppShell() {
  const navigate = useNavigate();
  const location = useLocation();
  const queryClient = useQueryClient();
  const collapsed = useUi((state) => state.sidebarCollapsed);
  const toggleSidebar = useUi((state) => state.toggleSidebar);
  const theme = useUi((state) => state.theme);
  const toggleTheme = useUi((state) => state.toggleTheme);
  const setPaletteOpen = useUi((state) => state.setPaletteOpen);
  const live = useLive();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);

  const system = useQuery({ queryKey: keys.system, queryFn: getSystem });
  const devices = useQuery({ queryKey: keys.devices, queryFn: listDevices });
  const runs = useQuery({ queryKey: keys.runs, queryFn: listRuns, refetchInterval: 5000 });
  const builds = useQuery({ queryKey: keys.builds, queryFn: () => listBuilds(), refetchInterval: 5000 });

  useEffect(() => {
    setDrawerOpen(false);
    setMenuOpen(false);
  }, [location.pathname]);

  const signOut = useMutation({
    mutationFn: logout,
    onSuccess: () => {
      queryClient.clear();
      navigate("/");
    },
  });

  const onlineCount = (devices.data?.devices ?? []).filter((device) => device.online && !device.disabled).length;
  const activeRuns = (runs.data?.runs ?? []).filter((run) => ACTIVE_RUN_STATUSES.has(run.status)).length;
  const activeBuilds = (builds.data?.builds ?? []).filter((build) => build.status === "running").length;

  const groups: NavGroup[] = [
    { title: "Overview", items: [{ to: "/", label: "Dashboard", icon: LayoutDashboard, end: true }] },
    {
      title: "Devices",
      items: [
        { to: "/devices", label: "Devices", icon: Smartphone, badge: onlineCount },
        { to: "/connect", label: "Connect", icon: Plus },
      ],
    },
    {
      title: "Flutter",
      items: [
        { to: "/projects", label: "Projects", icon: FolderKanban },
        { to: "/builds", label: "Builds", icon: Hammer, badge: activeBuilds },
        { to: "/runs", label: "Runs", icon: Play, badge: activeRuns },
      ],
    },
    {
      title: "System",
      items: [
        { to: "/system", label: "Diagnostics", icon: Wrench },
        { to: "/settings", label: "Settings", icon: Cog },
      ],
    },
  ];

  const crumbs_ = crumbs(location.pathname);

  const navigation = (inDrawer = false) => (
    <nav className={cn("scroll-thin flex flex-1 flex-col overflow-y-auto px-2 py-3")}>
      {groups.map((group) => (
        <div key={group.title} className="mb-1">
          {collapsed && !inDrawer ? null : (
            <p className="px-2.5 pt-3 pb-1 text-[10px] font-semibold tracking-wider text-[var(--color-subtle)] uppercase">
              {group.title}
            </p>
          )}
          {group.items.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              title={collapsed && !inDrawer ? item.label : undefined}
              className={({ isActive }) =>
                cn(
                  "group relative flex items-center gap-2.5 rounded-[var(--radius-md)] px-2.5 py-2 text-sm transition-colors duration-[var(--duration-fast)]",
                  collapsed && !inDrawer && "justify-center px-0",
                  isActive
                    ? "bg-[var(--color-accent-soft)] text-[var(--color-text)]"
                    : "text-[var(--color-muted)] hover:bg-[var(--color-panel-hover)] hover:text-[var(--color-text)]",
                )
              }
            >
              {({ isActive }) => (
                <>
                  {isActive ? (
                    <span className="absolute left-0 h-4 w-0.5 rounded-r bg-[var(--color-accent)]" />
                  ) : null}
                  <item.icon
                    size={16}
                    className={cn("shrink-0", isActive && "text-[var(--color-accent)]")}
                  />
                  {collapsed && !inDrawer ? null : (
                    <>
                      <span className="flex-1 truncate">{item.label}</span>
                      {item.badge ? (
                        <span className="tnum rounded-full bg-[var(--color-elevated)] px-1.5 py-0.5 text-[10px] font-medium text-[var(--color-muted)]">
                          {item.badge}
                        </span>
                      ) : null}
                    </>
                  )}
                </>
              )}
            </NavLink>
          ))}
        </div>
      ))}
    </nav>
  );

  const sidebarFooter = (
    <div
      className={cn(
        "shrink-0 border-t border-[var(--color-border)] px-3 py-2.5 text-[11px] text-[var(--color-muted)]",
        collapsed && "px-2 text-center",
      )}
    >
      {collapsed ? (
        <span className="tnum">v{system.data?.version ?? "—"}</span>
      ) : (
        <>
          <div className="flex items-center justify-between">
            <span>Version</span>
            <span className="tnum text-[var(--color-text)]">{system.data?.version ?? "—"}</span>
          </div>
          <div className="mt-0.5 flex items-center justify-between">
            <span>Reach</span>
            <span className="text-[var(--color-text)]">{system.data?.reach ?? "—"}</span>
          </div>
        </>
      )}
    </div>
  );

  return (
    <div className="flex h-screen overflow-hidden bg-[var(--color-surface)]">
      <CommandPalette />

      {/* Desktop sidebar */}
      <aside
        className={cn(
          "hidden shrink-0 flex-col border-r border-[var(--color-border)] bg-[var(--color-panel)] transition-[width] duration-200 md:flex",
          collapsed ? "w-[52px]" : "w-56",
        )}
      >
        <Link
          to="/"
          className={cn(
            "flex h-14 shrink-0 items-center gap-2.5 border-b border-[var(--color-border)] px-3",
            collapsed && "justify-center px-0",
          )}
        >
          <span className="grid h-7 w-7 shrink-0 place-items-center rounded-[var(--radius-md)] bg-[var(--color-accent)] text-sm font-bold text-white">
            F
          </span>
          {collapsed ? null : <span className="text-sm font-semibold tracking-tight">Fenox</span>}
        </Link>
        {navigation()}
        {sidebarFooter}
      </aside>

      {/* Mobile drawer */}
      {drawerOpen ? (
        <div className="fixed inset-0 z-40 md:hidden">
          <div className="absolute inset-0 bg-black/60" onClick={() => setDrawerOpen(false)} />
          <aside className="absolute inset-y-0 left-0 flex w-60 flex-col border-r border-[var(--color-border)] bg-[var(--color-panel)]">
            <div className="flex h-14 items-center justify-between border-b border-[var(--color-border)] px-4">
              <span className="text-sm font-semibold">Fenox</span>
              <button
                className="cursor-pointer text-[var(--color-muted)] hover:text-[var(--color-text)]"
                onClick={() => setDrawerOpen(false)}
                aria-label="Close navigation"
              >
                <X size={18} />
              </button>
            </div>
            {navigation(true)}
            {sidebarFooter}
          </aside>
        </div>
      ) : null}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex h-14 shrink-0 items-center gap-2 border-b border-[var(--color-border)] bg-[var(--color-panel)]/95 px-3 backdrop-blur sm:px-4">
          <button
            className="cursor-pointer rounded-[var(--radius-sm)] p-1.5 text-[var(--color-muted)] transition-colors hover:bg-[var(--color-panel-hover)] hover:text-[var(--color-text)] md:hidden"
            onClick={() => setDrawerOpen(true)}
            aria-label="Open navigation"
          >
            <Menu size={18} />
          </button>
          <button
            className="hidden cursor-pointer rounded-[var(--radius-sm)] p-1.5 text-[var(--color-muted)] transition-colors hover:bg-[var(--color-panel-hover)] hover:text-[var(--color-text)] md:block"
            onClick={toggleSidebar}
            aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          >
            {collapsed ? <ChevronsRight size={16} /> : <ChevronsLeft size={16} />}
          </button>

          <nav className="flex min-w-0 items-center gap-1.5 text-sm" aria-label="Breadcrumb">
            {crumbs_.map((crumb, index) => (
              <span key={crumb.to} className="flex min-w-0 items-center gap-1.5">
                {index > 0 ? <span className="text-[var(--color-subtle)]">/</span> : null}
                {index === crumbs_.length - 1 ? (
                  <span className="ellipsis font-medium">{crumb.label}</span>
                ) : (
                  <Link to={crumb.to} className="ellipsis text-[var(--color-muted)] hover:text-[var(--color-text)]">
                    {crumb.label}
                  </Link>
                )}
              </span>
            ))}
          </nav>

          <div className="ml-auto flex items-center gap-1.5">
            <button
              onClick={() => setPaletteOpen(true)}
              className="flex cursor-pointer items-center gap-2 rounded-[var(--radius-md)] border border-[var(--color-border)] bg-[var(--color-surface)] px-2.5 py-1.5 text-xs text-[var(--color-subtle)] transition-colors hover:border-[var(--color-border-strong)] hover:text-[var(--color-muted)]"
              title="Search (⌘K)"
            >
              <Search size={13} />
              <span className="hidden sm:inline">Search</span>
              <kbd className="hidden rounded border border-[var(--color-border)] px-1 text-[10px] sm:inline">⌘K</kbd>
            </button>

            <span
              className={cn(
                "hidden items-center gap-1.5 rounded-[var(--radius-md)] px-2 py-1.5 text-xs sm:flex",
                live ? "text-[var(--color-success)]" : "text-[var(--color-muted)]",
              )}
              title={live ? "Live updates connected" : "Reconnecting"}
            >
              <Activity size={13} />
            </span>

            <button
              onClick={toggleTheme}
              className="cursor-pointer rounded-[var(--radius-md)] p-2 text-[var(--color-muted)] transition-colors hover:bg-[var(--color-panel-hover)] hover:text-[var(--color-text)]"
              aria-label="Toggle theme"
              title={theme === "dark" ? "Switch to light" : "Switch to dark"}
            >
              {theme === "dark" ? <Sun size={15} /> : <Moon size={15} />}
            </button>

            <div className="relative">
              <button
                className="flex cursor-pointer items-center gap-2 rounded-[var(--radius-md)] px-1.5 py-1 text-sm text-[var(--color-muted)] transition-colors hover:bg-[var(--color-panel-hover)] hover:text-[var(--color-text)]"
                onClick={() => setMenuOpen((open) => !open)}
              >
                <span className="grid h-7 w-7 place-items-center rounded-full bg-[var(--color-elevated)] text-xs font-medium text-[var(--color-text)]">
                  O
                </span>
              </button>
              {menuOpen ? (
                <>
                  <div className="fixed inset-0 z-40" onClick={() => setMenuOpen(false)} />
                  <div className="animate-in absolute right-0 z-50 mt-1.5 w-40 overflow-hidden rounded-[var(--radius-md)] border border-[var(--color-border-strong)] bg-[var(--color-panel)] py-1 shadow-xl">
                    <button
                      className="flex w-full cursor-pointer items-center gap-2 px-3 py-2 text-left text-sm text-[var(--color-muted)] transition-colors hover:bg-[var(--color-panel-hover)] hover:text-[var(--color-text)]"
                      onClick={() => signOut.mutate()}
                    >
                      <LogOut size={14} />
                      Sign out
                    </button>
                  </div>
                </>
              ) : null}
            </div>
          </div>
        </header>

        <div className="flex min-h-0 flex-1">
          <main className="scroll-thin min-w-0 flex-1 overflow-y-auto">
            <div className="mx-auto w-full max-w-[1400px] px-4 py-5 sm:px-6">
              <Outlet />
            </div>
          </main>

          <aside className="sticky top-0 hidden h-full w-72 shrink-0 border-l border-[var(--color-border)] xl:block">
            <DeviceRail />
          </aside>
        </div>
      </div>
    </div>
  );
}
