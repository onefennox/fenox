import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  FolderKanban,
  LayoutDashboard,
  LogOut,
  Menu,
  Play,
  Plus,
  Settings as SettingsIcon,
  Smartphone,
  Wrench,
  X,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";

import { getSystem, keys, listDevices, listRuns, logout } from "@/api/queries";
import { useLive } from "@/hooks/useLive";
import { DeviceRail } from "./DeviceRail";

interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
  end?: boolean;
  badge?: number;
}

const ACTIVE_RUN_STATUSES = new Set(["starting", "running", "stopping"]);

function titleFor(pathname: string): string {
  if (pathname === "/") return "Dashboard";
  if (pathname.startsWith("/connect")) return "Connect a device";
  if (pathname.startsWith("/devices")) return "Devices";
  if (pathname.startsWith("/projects")) return "Projects";
  if (pathname.startsWith("/runs")) return "Runs";
  if (pathname.startsWith("/system")) return "System";
  if (pathname.startsWith("/settings")) return "Settings";
  return "Fenox";
}

export function AppShell() {
  const navigate = useNavigate();
  const location = useLocation();
  const queryClient = useQueryClient();
  const live = useLive();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);

  const system = useQuery({ queryKey: keys.system, queryFn: getSystem });
  const devices = useQuery({ queryKey: keys.devices, queryFn: listDevices });
  const runs = useQuery({ queryKey: keys.runs, queryFn: listRuns, refetchInterval: 5000 });

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

  const nav: NavItem[] = [
    { to: "/", label: "Dashboard", icon: LayoutDashboard, end: true },
    { to: "/devices", label: "Devices", icon: Smartphone, badge: onlineCount },
    { to: "/connect", label: "Connect a device", icon: Plus },
    { to: "/projects", label: "Projects", icon: FolderKanban },
    { to: "/runs", label: "Runs", icon: Play, badge: activeRuns },
    { to: "/system", label: "System", icon: Wrench },
    { to: "/settings", label: "Settings", icon: SettingsIcon },
  ];

  const environment = system.data
    ? `${system.data.platform.wsl ? "WSL" : system.data.platform.linux ? "Linux" : "Unknown"} · adb ${system.data.adb.server_port}`
    : "";

  const navigation = (
    <nav className="flex flex-1 flex-col gap-1 px-3 py-4">
      {nav.map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          end={item.end}
          className={({ isActive }) =>
            `group flex items-center gap-3 rounded-md px-3 py-2 text-sm transition ${
              isActive
                ? "bg-[var(--color-panel-hover)] text-white"
                : "text-[var(--color-muted)] hover:bg-[var(--color-panel-hover)] hover:text-white"
            }`
          }
        >
          {({ isActive }) => (
            <>
              <item.icon size={17} className={isActive ? "text-[var(--color-accent)]" : ""} />
              <span className="flex-1">{item.label}</span>
              {item.badge ? (
                <span className="rounded-full bg-[var(--color-border)] px-2 py-0.5 text-xs text-[var(--color-muted)]">
                  {item.badge}
                </span>
              ) : null}
            </>
          )}
        </NavLink>
      ))}
    </nav>
  );

  const sidebarFooter = (
    <div className="border-t border-[var(--color-border)] px-4 py-3 text-xs text-[var(--color-muted)]">
      <div className="flex items-center justify-between">
        <span>Version</span>
        <span className="text-white">{system.data?.version ?? "—"}</span>
      </div>
      <div className="mt-1 flex items-center justify-between">
        <span>Reach</span>
        <span className="text-white">{system.data?.reach ?? "—"}</span>
      </div>
    </div>
  );

  return (
    <div className="flex min-h-screen flex-col bg-[var(--color-surface)]">
      <header className="sticky top-0 z-30 flex h-14 items-center gap-3 border-b border-[var(--color-border)] bg-[var(--color-panel)] px-4">
        <button
          className="cursor-pointer text-[var(--color-muted)] hover:text-white md:hidden"
          onClick={() => setDrawerOpen(true)}
          aria-label="Open navigation"
        >
          <Menu size={20} />
        </button>

        <div className="flex items-center gap-2">
          <span className="grid h-7 w-7 place-items-center rounded-md bg-[var(--color-accent)] text-sm font-bold text-white">
            F
          </span>
          <span className="text-sm font-semibold tracking-tight text-white">Fenox</span>
        </div>

        <span className="mx-2 hidden h-5 w-px bg-[var(--color-border)] sm:block" />
        <h1 className="truncate text-sm font-medium text-white">{titleFor(location.pathname)}</h1>

        <div className="ml-auto flex items-center gap-3">
          <span
            className={`hidden items-center gap-1.5 text-xs sm:flex ${live ? "text-emerald-400" : "text-[var(--color-muted)]"}`}
            title={live ? "Live updates connected" : "Reconnecting to the hub"}
          >
            <Activity size={14} className={live ? "" : "opacity-50"} />
            {live ? "Live" : "Offline"}
          </span>
          {environment ? (
            <span className="hidden rounded-full border border-[var(--color-border)] px-2.5 py-1 text-xs text-[var(--color-muted)] lg:inline">
              {environment}
            </span>
          ) : null}

          <div className="relative">
            <button
              className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1 text-sm text-[var(--color-muted)] hover:text-white"
              onClick={() => setMenuOpen((open) => !open)}
            >
              <span className="grid h-7 w-7 place-items-center rounded-full bg-[var(--color-border)] text-xs text-white">
                O
              </span>
              <span className="hidden sm:inline">Owner</span>
            </button>
            {menuOpen ? (
              <>
                <div className="fixed inset-0 z-40" onClick={() => setMenuOpen(false)} />
                <div className="absolute right-0 z-50 mt-2 w-44 overflow-hidden rounded-md border border-[var(--color-border)] bg-[var(--color-panel)] py-1 shadow-lg">
                  <button
                    className="flex w-full cursor-pointer items-center gap-2 px-3 py-2 text-left text-sm text-[var(--color-muted)] hover:bg-[var(--color-panel-hover)] hover:text-white"
                    onClick={() => signOut.mutate()}
                  >
                    <LogOut size={15} />
                    Sign out
                  </button>
                </div>
              </>
            ) : null}
          </div>
        </div>
      </header>

      <div className="flex flex-1">
        <aside className="hidden w-60 shrink-0 flex-col border-r border-[var(--color-border)] bg-[var(--color-panel)] md:flex">
          {navigation}
          {sidebarFooter}
        </aside>

        {drawerOpen ? (
          <div className="fixed inset-0 z-40 md:hidden">
            <div className="absolute inset-0 bg-black/60" onClick={() => setDrawerOpen(false)} />
            <aside className="absolute inset-y-0 left-0 flex w-64 flex-col border-r border-[var(--color-border)] bg-[var(--color-panel)]">
              <div className="flex h-14 items-center justify-between border-b border-[var(--color-border)] px-4">
                <span className="text-sm font-semibold text-white">Fenox</span>
                <button className="cursor-pointer text-[var(--color-muted)] hover:text-white" onClick={() => setDrawerOpen(false)}>
                  <X size={18} />
                </button>
              </div>
              {navigation}
              {sidebarFooter}
            </aside>
          </div>
        ) : null}

        <main className="min-w-0 flex-1">
          <div className="mx-auto w-full max-w-7xl px-4 py-6 sm:px-6">
            <Outlet />
          </div>
        </main>

        <aside className="sticky top-14 hidden h-[calc(100vh-3.5rem)] w-80 shrink-0 border-l border-[var(--color-border)] xl:block">
          <DeviceRail />
        </aside>
      </div>
    </div>
  );
}
