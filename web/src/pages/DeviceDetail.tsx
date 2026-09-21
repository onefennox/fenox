import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";

import { keys, listDevices } from "@/api/queries";
import { Badge, Card, Spinner, StatusDot } from "@/components/ui";
import { Tabs } from "@/components/Tabs";
import { AppsPanel } from "./device/AppsPanel";
import { ControlPanel } from "./device/ControlPanel";
import { DevToolsPanel } from "./device/DevToolsPanel";
import { FilesPanel } from "./device/FilesPanel";
import { MirrorPanel } from "./device/MirrorPanel";
import { OverviewPanel } from "./device/OverviewPanel";
import { PhonePanel } from "./device/PhonePanel";
import { ScreenInputPanel } from "./device/ScreenInputPanel";

export function DeviceDetailPage() {
  const { id = "" } = useParams();
  const deviceId = decodeURIComponent(id);

  const devices = useQuery({ queryKey: keys.devices, queryFn: listDevices });
  const device = devices.data?.devices.find((item) => item.id === deviceId);

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
    <div className="space-y-6">
      <div>
        <Link to="/devices" className="text-xs text-[var(--color-muted)] hover:text-white">
          &larr; Devices
        </Link>
        <div className="mt-2 flex flex-wrap items-center gap-3">
          <StatusDot online={device.online} disabled={device.disabled} />
          <h1 className="text-lg font-semibold text-white">{device.id}</h1>
          <Badge>{device.type ?? "unknown"}</Badge>
          {device.online ? <Badge tone="accent">online</Badge> : <Badge tone="warn">offline</Badge>}
          <span className="text-xs text-[var(--color-muted)]">
            {device.model ?? "Android device"}
            {device.serial ? ` · ${device.serial}` : ""}
          </span>
        </div>
      </div>

      <Tabs
        tabs={[
          { id: "overview", label: "Overview", render: () => <OverviewPanel device={device} /> },
          { id: "mirror", label: "Mirror", render: () => <MirrorPanel device={device} /> },
          { id: "screen", label: "Screen & Input", render: () => <ScreenInputPanel device={device} /> },
          { id: "apps", label: "Apps", render: () => <AppsPanel device={device} /> },
          { id: "files", label: "Files", render: () => <FilesPanel device={device} /> },
          { id: "control", label: "Control", render: () => <ControlPanel device={device} /> },
          { id: "devtools", label: "Dev Tools", render: () => <DevToolsPanel device={device} /> },
          { id: "phone", label: "Phone", render: () => <PhonePanel device={device} /> },
        ]}
      />
    </div>
  );
}
