import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { NavLink, Outlet, useNavigate } from "react-router-dom";

import { getSystem, keys, logout } from "@/api/queries";
import { Button } from "./ui";

const navItems = [
  { to: "/", label: "Dashboard", end: true },
  { to: "/devices", label: "Devices", end: false },
  { to: "/projects", label: "Projects", end: false },
  { to: "/runs", label: "Runs", end: false },
  { to: "/system", label: "System", end: false },
  { to: "/settings", label: "Settings", end: false },
];

export function AppShell() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { data: system } = useQuery({ queryKey: keys.system, queryFn: getSystem });

  const signOut = useMutation({
    mutationFn: logout,
    onSuccess: () => {
      queryClient.clear();
      navigate("/");
    },
  });

  return (
    <div className="flex min-h-full flex-col">
      <header className="border-b border-[var(--color-border)]">
        <div className="mx-auto flex w-full max-w-6xl items-center gap-6 px-6 py-3">
          <div className="flex items-center gap-2">
            <span className="text-sm font-semibold tracking-tight text-white">Fenox</span>
            {system ? <span className="text-xs text-[var(--color-muted)]">v{system.version}</span> : null}
          </div>
          <nav className="flex items-center gap-1">
            {navItems.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={({ isActive }) =>
                  `rounded-md px-3 py-1.5 text-sm transition ${
                    isActive ? "bg-[var(--color-panel-hover)] text-white" : "text-[var(--color-muted)] hover:text-white"
                  }`
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-3">
            {system ? (
              <span className="hidden text-xs text-[var(--color-muted)] sm:inline">
                {system.platform.wsl ? "WSL" : system.platform.linux ? "Linux" : "Unknown"} · adb {system.adb.server_port}
              </span>
            ) : null}
            <Button variant="ghost" onClick={() => signOut.mutate()}>
              Sign out
            </Button>
          </div>
        </div>
      </header>
      <main className="mx-auto w-full max-w-6xl flex-1 px-6 py-6">
        <Outlet />
      </main>
    </div>
  );
}
