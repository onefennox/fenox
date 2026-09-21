import { useQuery } from "@tanstack/react-query";
import { ChevronRight } from "lucide-react";
import { Link } from "react-router-dom";

import { keys, listDevices } from "@/api/queries";
import { Badge, Card, Spinner, StatusDot } from "@/components/ui";

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <Card className="p-5">
      <div className="text-3xl font-semibold text-white">{value}</div>
      <div className="mt-1 text-sm text-[var(--color-muted)]">{label}</div>
    </Card>
  );
}

export function DashboardPage() {
  const { data, isLoading, error } = useQuery({ queryKey: keys.devices, queryFn: listDevices });

  if (isLoading) {
    return <Spinner label="Loading devices" />;
  }
  if (error) {
    return <p className="text-sm text-red-400">{(error as Error).message}</p>;
  }

  const devices = data?.devices ?? [];
  const online = devices.filter((device) => device.online && !device.disabled).length;
  const pending = data?.pending ?? [];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-lg font-semibold text-white">Dashboard</h1>
        <p className="mt-1 text-sm text-[var(--color-muted)]">
          Devices connected over USB, emulator, or wireless debugging.
        </p>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <Stat label="Registered devices" value={devices.length} />
        <Stat label="Online" value={online} />
        <Stat label="Waiting for authorization" value={pending.length} />
      </div>

      {pending.length > 0 ? (
        <Card className="border-amber-500/30 p-4">
          <p className="text-sm text-amber-300">
            {pending.length === 1 ? "One device is" : `${pending.length} devices are`} visible but not usable yet. Accept
            the debugging prompt on the phone, or unlock it and reconnect.
          </p>
        </Card>
      ) : null}

      <div>
        <div className="mb-2 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-white">Devices</h2>
          <Link to="/connect" className="text-xs text-[var(--color-accent)] hover:underline">
            Connect a device
          </Link>
        </div>
        {devices.length === 0 ? (
          <Card className="p-6 text-sm text-[var(--color-muted)]">
            No devices yet.{" "}
            <Link to="/connect" className="text-[var(--color-accent)] hover:underline">
              Connect a phone
            </Link>{" "}
            over USB or wireless debugging.
          </Card>
        ) : (
          <Card className="divide-y divide-[var(--color-border)]">
            {devices.map((device) => (
              <Link
                key={device.id}
                to={`/devices/${encodeURIComponent(device.id)}`}
                className="group flex cursor-pointer items-center gap-4 p-3 transition hover:bg-[var(--color-panel-hover)]"
              >
                <StatusDot online={device.online} disabled={device.disabled} />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="truncate text-sm font-medium text-white">{device.id}</span>
                    <Badge>{device.type === "wireless" ? "wireless" : device.type === "usb" ? "usb" : device.type ?? "unknown"}</Badge>
                  </div>
                  <div className="truncate text-xs text-[var(--color-muted)]">{device.model ?? "Android device"}</div>
                </div>
                <ChevronRight size={16} className="shrink-0 text-[var(--color-muted)] transition group-hover:text-white" />
              </Link>
            ))}
          </Card>
        )}
      </div>
    </div>
  );
}
