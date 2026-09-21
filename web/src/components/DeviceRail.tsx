import { useQuery } from "@tanstack/react-query";
import { ChevronRight, Plus } from "lucide-react";
import { Link } from "react-router-dom";

import { keys, listDevices } from "@/api/queries";
import { Badge, Button, StatusDot } from "@/components/ui";

/**
 * The always-visible device rail. Devices appear here the moment they connect,
 * because the devices query is kept live by the event WebSocket.
 */
export function DeviceRail() {
  const { data } = useQuery({ queryKey: keys.devices, queryFn: listDevices });
  const devices = data?.devices ?? [];
  const pending = data?.pending ?? [];
  const online = devices.filter((device) => device.online && !device.disabled).length;

  return (
    <div className="flex h-full flex-col bg-[var(--color-panel)]">
      <div className="flex items-start justify-between gap-2 border-b border-[var(--color-border)] px-4 py-3">
        <div className="min-w-0">
          <h2 className="text-sm font-semibold text-white">Devices</h2>
          <p className="truncate text-xs text-[var(--color-muted)]">
            {online} online · {devices.length} total
          </p>
        </div>
        <Link to="/connect" aria-label="Connect a device">
          <Button variant="ghost">
            <Plus size={16} />
          </Button>
        </Link>
      </div>

      <div className="flex-1 overflow-y-auto">
        {devices.length === 0 ? (
          <div className="p-4">
            <p className="text-sm text-[var(--color-muted)]">No devices connected yet.</p>
            <Link to="/connect" className="mt-3 inline-block">
              <Button variant="secondary">Connect a device</Button>
            </Link>
          </div>
        ) : (
          <ul className="divide-y divide-[var(--color-border)]">
            {devices.map((device) => (
              <li key={device.id}>
                <Link
                  to={`/devices/${encodeURIComponent(device.id)}`}
                  className="group flex items-center gap-3 px-4 py-3 transition hover:bg-[var(--color-panel-hover)]"
                >
                  <StatusDot online={device.online} disabled={device.disabled} />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="truncate text-sm text-white">{device.id}</span>
                      <Badge>{device.type === "wireless" ? "wifi" : device.type === "usb" ? "usb" : device.type ?? "—"}</Badge>
                    </div>
                    <div className="truncate text-xs text-[var(--color-muted)]">
                      {device.disabled ? "disabled" : device.online ? device.model ?? "online" : "offline"}
                    </div>
                  </div>
                  <ChevronRight size={15} className="shrink-0 text-[var(--color-muted)] transition group-hover:text-white" />
                </Link>
              </li>
            ))}
          </ul>
        )}
      </div>

      {pending.length > 0 ? (
        <div className="border-t border-[var(--color-border)] px-4 py-3 text-xs text-amber-300">
          {pending.length === 1 ? "1 device is waiting" : `${pending.length} devices are waiting`} — check the phone for a
          prompt.
        </div>
      ) : null}
    </div>
  );
}
