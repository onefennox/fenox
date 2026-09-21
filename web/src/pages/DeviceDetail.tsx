import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Activity, AppWindow, FolderOpen, Gauge, Info, MonitorSmartphone, Smartphone, SlidersHorizontal } from "lucide-react";
import { useEffect } from "react";
import { Link, useParams } from "react-router-dom";

import { connectDevice, keys, listDevices } from "@/api/queries";
import { Badge, Button, Card, Spinner, StatusDot } from "@/components/ui";
import { Tabs } from "@/components/Tabs";
import { useActiveDevice } from "@/hooks/useActiveDevice";
import { AppsPanel } from "./device/AppsPanel";
import { ControlPanel } from "./device/ControlPanel";
import { DevToolsPanel } from "./device/DevToolsPanel";
import { FilesPanel } from "./device/FilesPanel";
import { OverviewPanel } from "./device/OverviewPanel";
import { PhonePanel } from "./device/PhonePanel";
import { ScreenInputPanel } from "./device/ScreenInputPanel";

export function DeviceDetailPage() {
  const { id = "" } = useParams();
  const deviceId = decodeURIComponent(id);
  const { setActiveDevice } = useActiveDevice();

  const queryClient = useQueryClient();
  const devices = useQuery({ queryKey: keys.devices, queryFn: listDevices });
  const device = devices.data?.devices.find((item) => item.id === deviceId);
  const connect = useMutation({
    mutationFn: () => connectDevice(deviceId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: keys.devices }),
  });

  useEffect(() => {
    if (deviceId) setActiveDevice(deviceId);
  }, [deviceId, setActiveDevice]);

  if (devices.isLoading) {
    return <Spinner label="Loading device" />;
  }
  if (!device) {
    return (
      <div className="space-y-4">
        <Link to="/devices" className="text-xs text-[var(--color-muted)] hover:text-white">
          &larr; Devices
        </Link>
        <Card className="p-6 text-sm text-[var(--color-muted)]">This device is no longer registered.</Card>
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <div className="rounded-xl border border-[var(--color-border)] bg-gradient-to-r from-[var(--color-panel)] to-[var(--color-surface)] p-3 sm:p-4">
        <Link to="/devices" className="mb-2 inline-flex text-xs text-[var(--color-muted)] hover:text-white">
          &larr; All devices
        </Link>
        <div className="flex flex-wrap items-center gap-4">
          <div className="grid h-10 w-10 shrink-0 place-items-center rounded-xl border border-[var(--color-border)] bg-[var(--color-panel-hover)] text-[var(--color-accent)]">
            <Smartphone size={21} />
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <StatusDot online={device.online} disabled={device.disabled} />
              <h1 className="truncate text-xl font-semibold tracking-tight text-white">{device.id}</h1>
              {device.online ? <Badge tone="accent">Online</Badge> : <Badge tone="warn">Offline</Badge>}
            </div>
            <p className="mt-1 truncate text-sm text-[var(--color-muted)]">
              {device.model ?? "Android device"} <span className="px-1 text-[var(--color-border)]">•</span> {device.type ?? "Unknown connection"}
              {device.serial ? <><span className="px-1 text-[var(--color-border)]">•</span>{device.serial}</> : null}
            </p>
          </div>
          {!device.online && !device.disabled ? (
            <Button variant="secondary" onClick={() => connect.mutate()} disabled={connect.isPending}>
              {connect.isPending ? "Connecting…" : "Connect"}
            </Button>
          ) : null}
        </div>
        {connect.error ? <p className="mt-3 text-xs text-red-400">{(connect.error as Error).message}</p> : null}
      </div>

      <Tabs
        tabs={[
          { id: "overview", label: "Overview", icon: <Info size={16} />, render: () => <OverviewPanel device={device} /> },
          { id: "screen", label: "Remote control", icon: <MonitorSmartphone size={16} />, render: () => <ScreenInputPanel device={device} /> },
          { id: "apps", label: "Apps", icon: <AppWindow size={16} />, render: () => <AppsPanel device={device} /> },
          { id: "files", label: "Files", icon: <FolderOpen size={16} />, render: () => <FilesPanel device={device} /> },
          { id: "control", label: "Device controls", icon: <SlidersHorizontal size={16} />, render: () => <ControlPanel device={device} /> },
          { id: "devtools", label: "Diagnostics", icon: <Activity size={16} />, render: () => <DevToolsPanel device={device} /> },
          { id: "phone", label: "Phone data", icon: <Gauge size={16} />, render: () => <PhonePanel device={device} /> },
        ]}
      />
    </div>
  );
}
