import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Info, MoreHorizontal, Power, Search, Square, Trash2, Upload, X } from "lucide-react";
import { useState } from "react";

import { appInfo, clearApp, installApp, keys, launchApp, listApps, stopApp, uninstallApp } from "@/api/queries";
import type { Device } from "@/api/types";
import { Menu } from "@/components/Menu";
import { Button, Card, EmptyState, ErrorText, Input, Modal, SegmentedControl, SkeletonRows } from "@/components/ui";
import { toast } from "@/lib/toast";

type Scope = "user" | "all";

/** Package actions, behind the shared Menu so the scroll container cannot clip them. */
function AppMenu({ onAction, busy }: { onAction: (action: string) => void; busy: boolean }) {
  return (
    <Menu
      label="App actions"
      buttonSize="icon"
      buttonClassName="text-[var(--color-subtle)]"
      widthClass="w-40"
      disabled={busy}
      items={[
        { id: "open", label: "Open", icon: <Power size={13} />, onSelect: () => onAction("open") },
        { id: "stop", label: "Force stop", icon: <Square size={13} />, onSelect: () => onAction("stop") },
        { id: "clear", label: "Clear data", icon: <Trash2 size={13} />, onSelect: () => onAction("clear") },
        { id: "info", label: "Info", icon: <Info size={13} />, onSelect: () => onAction("info") },
        { id: "uninstall", label: "Uninstall", icon: <Trash2 size={13} />, danger: true, onSelect: () => onAction("uninstall") },
      ]}
    >
      <MoreHorizontal size={15} />
    </Menu>
  );
}

export function AppsPanel({ device }: { device: Device }) {
  const queryClient = useQueryClient();
  const [scope, setScope] = useState<Scope>("user");
  const [filter, setFilter] = useState("");
  const [installPath, setInstallPath] = useState("");
  const [info, setInfo] = useState<{ pkg: string; text: string } | null>(null);

  const apps = useQuery({
    queryKey: [...keys.apps(device.id), scope],
    queryFn: () => listApps(device.id, scope === "user"),
    enabled: device.online,
  });

  const refresh = () => queryClient.invalidateQueries({ queryKey: keys.apps(device.id) });
  const act = useMutation({
    mutationFn: (action: () => Promise<unknown>) => action(),
    onSuccess: refresh,
    onError: (error: Error) => toast.error("That did not work", error.message),
  });

  if (!device.online) {
    return (
      <Card>
        <EmptyState title="Device offline" description="Connect the phone to list and manage its apps." />
      </Card>
    );
  }

  const all = apps.data?.apps ?? [];
  const needle = filter.trim().toLowerCase();
  const packages = needle ? all.filter((pkg) => pkg.toLowerCase().includes(needle)) : all;

  const handle = (pkg: string, action: string) => {
    if (action === "open") act.mutate(() => launchApp(device.id, pkg));
    else if (action === "stop") act.mutate(() => stopApp(device.id, pkg));
    else if (action === "clear") act.mutate(() => clearApp(device.id, pkg));
    else if (action === "uninstall") act.mutate(() => uninstallApp(device.id, pkg));
    else if (action === "info") {
      appInfo(device.id, pkg)
        .then((result) => setInfo({ pkg, text: result.info }))
        .catch((error: Error) => toast.error("Could not read app info", error.message));
    }
  };

  return (
    <div className="space-y-3">
      <Card className="p-3">
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative min-w-48 flex-1">
            <Search size={13} className="absolute top-1/2 left-2.5 -translate-y-1/2 text-[var(--color-subtle)]" />
            <Input
              value={filter}
              onChange={(event) => setFilter(event.target.value)}
              placeholder="Search packages…"
              className="pl-8"
            />
            {filter ? (
              <button
                onClick={() => setFilter("")}
                aria-label="Clear search"
                className="absolute top-1/2 right-2 -translate-y-1/2 cursor-pointer text-[var(--color-subtle)] hover:text-[var(--color-text)]"
              >
                <X size={13} />
              </button>
            ) : null}
          </div>
          <SegmentedControl<Scope>
            value={scope}
            onChange={setScope}
            options={[
              { id: "user", label: "User apps" },
              { id: "all", label: "All" },
            ]}
          />
          <span className="tnum px-1 text-xs text-[var(--color-subtle)]">{packages.length}</span>
        </div>

        <div className="mt-2 flex flex-wrap items-center gap-2">
          <Input
            value={installPath}
            onChange={(event) => setInstallPath(event.target.value)}
            placeholder="/path/to/app.apk on this machine"
            className="min-w-48 flex-1 font-mono text-xs"
          />
          <Button
            size="sm"
            variant="secondary"
            disabled={!installPath || act.isPending}
            onClick={() =>
              act.mutate(async () => {
                await installApp(device.id, installPath);
                setInstallPath("");
              })
            }
          >
            <Upload size={13} />
            Install
          </Button>
        </div>
      </Card>

      <ErrorText>{(act.error as Error | null)?.message}</ErrorText>

      <Card className="overflow-hidden">
        {apps.isLoading ? (
          <div className="p-4">
            <SkeletonRows rows={6} />
          </div>
        ) : packages.length === 0 ? (
          <EmptyState
            title={needle ? "No packages match" : "No apps found"}
            description={needle ? `Nothing contains “${filter}”.` : "This device reported no packages in this scope."}
          />
        ) : (
          <div className="scroll-thin max-h-[60vh] divide-y divide-[var(--color-border)] overflow-y-auto">
            {packages.map((pkg) => (
              <div key={pkg} className="group flex items-center gap-2 px-3 py-1.5 transition-colors hover:bg-[var(--color-panel-hover)]">
                <span className="min-w-0 flex-1 truncate font-mono text-xs">{pkg}</span>
                <AppMenu busy={act.isPending} onAction={(action) => handle(pkg, action)} />
              </div>
            ))}
          </div>
        )}
      </Card>

      {info ? (
        <Modal
          title={info.pkg}
          description="What the device reports for this package."
          onClose={() => setInfo(null)}
          size="lg"
        >
          <pre className="scroll-thin max-h-[60vh] overflow-auto rounded-[var(--radius-md)] bg-[var(--color-surface)] p-3 font-mono text-[11px] leading-relaxed whitespace-pre-wrap text-[var(--color-muted)]">
            {info.text}
          </pre>
        </Modal>
      ) : null}
    </div>
  );
}
