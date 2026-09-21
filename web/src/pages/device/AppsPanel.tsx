import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { appInfo, clearApp, installApp, keys, launchApp, listApps, stopApp, uninstallApp } from "@/api/queries";
import type { Device } from "@/api/types";
import { Button, Card, ErrorText, Input, Modal, Spinner } from "@/components/ui";

export function AppsPanel({ device }: { device: Device }) {
  const queryClient = useQueryClient();
  const [filter, setFilter] = useState("");
  const [installPath, setInstallPath] = useState("");
  const [info, setInfo] = useState<{ pkg: string; text: string } | null>(null);

  const apps = useQuery({ queryKey: keys.apps(device.id), queryFn: () => listApps(device.id), enabled: device.online });

  const act = useMutation({
    mutationFn: (action: () => Promise<unknown>) => action(),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: keys.apps(device.id) }),
  });

  if (!device.online) {
    return <Card className="p-6 text-sm text-[var(--color-muted)]">The device is offline.</Card>;
  }

  const packages = (apps.data?.apps ?? []).filter((pkg) => pkg.toLowerCase().includes(filter.toLowerCase()));

  return (
    <div className="space-y-4">
      <Card className="flex flex-wrap items-end gap-3 p-4">
        <div className="flex-1">
          <Input value={filter} onChange={(event) => setFilter(event.target.value)} placeholder="Filter packages" />
        </div>
        <div className="flex gap-2">
          <Input value={installPath} onChange={(event) => setInstallPath(event.target.value)} placeholder="/path/to/app.apk" />
          <Button
            disabled={!installPath || act.isPending}
            onClick={() => act.mutate(() => installApp(device.id, installPath))}
          >
            Install APK
          </Button>
        </div>
      </Card>

      <ErrorText>{(act.error as Error | null)?.message}</ErrorText>

      {apps.isLoading ? (
        <Spinner label="Loading apps" />
      ) : (
        <Card className="max-h-[560px] divide-y divide-[var(--color-border)] overflow-y-auto">
          {packages.map((pkg) => (
            <div key={pkg} className="flex items-center gap-2 p-2.5 text-sm">
              <span className="min-w-0 flex-1 truncate text-white">{pkg}</span>
              <Button variant="ghost" onClick={() => act.mutate(() => launchApp(device.id, pkg))}>
                Open
              </Button>
              <Button variant="ghost" onClick={() => act.mutate(() => stopApp(device.id, pkg))}>
                Stop
              </Button>
              <Button variant="ghost" onClick={() => act.mutate(() => clearApp(device.id, pkg))}>
                Clear
              </Button>
              <Button
                variant="ghost"
                onClick={async () => {
                  const result = await appInfo(device.id, pkg);
                  setInfo({ pkg, text: result.info });
                }}
              >
                Info
              </Button>
              <Button variant="ghost" onClick={() => act.mutate(() => uninstallApp(device.id, pkg))}>
                Uninstall
              </Button>
            </div>
          ))}
          {packages.length === 0 ? <p className="p-4 text-sm text-[var(--color-muted)]">No packages match.</p> : null}
        </Card>
      )}

      {info ? (
        <Modal title={`Info · ${info.pkg}`} onClose={() => setInfo(null)}>
          <pre className="max-h-[60vh] overflow-auto whitespace-pre-wrap text-xs text-[var(--color-muted)]">{info.text}</pre>
        </Modal>
      ) : null}
    </div>
  );
}
