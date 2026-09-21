import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, Lock, Monitor, Plus, Sun } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { connectDevice, getTelemetry, keys, listDevices, lockDevice, wakeDevice } from "@/api/queries";
import type { Device } from "@/api/types";
import { useActiveDevice } from "@/hooks/useActiveDevice";
import { Badge, Button, StatusDot } from "@/components/ui";

/**
 * The right rail belongs to the selected phone. With nothing selected it lists
 * devices to pick from; once one is selected it becomes that phone's live pane —
 * a streaming screen preview, live telemetry, and quick controls.
 */
export function DeviceRail() {
  const { activeId, setActiveDevice } = useActiveDevice();
  const { data } = useQuery({ queryKey: keys.devices, queryFn: listDevices });
  const devices = data?.devices ?? [];
  const pending = data?.pending ?? [];
  const active = devices.find((device) => device.id === activeId) ?? null;

  if (active?.id) {
    return <ActiveDevicePane device={active} onBack={() => setActiveDevice(null)} />;
  }
  return <DevicePicker devices={devices} pending={pending.length} onSelect={setActiveDevice} />;
}

function DevicePicker({
  devices,
  pending,
  onSelect,
}: {
  devices: Device[];
  pending: number;
  onSelect: (id: string) => void;
}) {
  return (
    <div className="flex h-full flex-col bg-[var(--color-panel)]">
      <div className="flex items-start justify-between gap-2 border-b border-[var(--color-border)] px-4 py-3">
        <div className="min-w-0">
          <h2 className="text-sm font-semibold text-white">Devices</h2>
          <p className="truncate text-xs text-[var(--color-muted)]">
            Select a device to view it · {devices.length} total
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
                <button
                  onClick={() => onSelect(device.id)}
                  className="group flex w-full cursor-pointer items-center gap-3 px-4 py-3 text-left transition hover:bg-[var(--color-panel-hover)]"
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
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      {pending > 0 ? (
        <div className="border-t border-[var(--color-border)] px-4 py-3 text-xs text-amber-300">
          {pending === 1 ? "1 device is waiting" : `${pending} devices are waiting`} — check the phone for a prompt.
        </div>
      ) : null}
    </div>
  );
}

function ActiveDevicePane({ device, onBack }: { device: Device; onBack: () => void }) {
  const queryClient = useQueryClient();
  const telemetry = useQuery({
    queryKey: keys.telemetry(device.id),
    queryFn: () => getTelemetry(device.id),
    enabled: device.online,
    refetchInterval: 8000,
  });

  const refresh = () => queryClient.invalidateQueries({ queryKey: keys.devices });
  const wake = useMutation({ mutationFn: () => wakeDevice(device.id) });
  const lock = useMutation({ mutationFn: () => lockDevice(device.id) });
  const connect = useMutation({ mutationFn: () => connectDevice(device.id), onSuccess: refresh });

  const tele = telemetry.data?.telemetry;

  return (
    <div className="flex h-full flex-col bg-[var(--color-panel)]">
      <div className="flex items-center gap-2 border-b border-[var(--color-border)] px-3 py-3">
        <button className="cursor-pointer text-[var(--color-muted)] hover:text-white" onClick={onBack} aria-label="All devices">
          <ChevronLeft size={18} />
        </button>
        <StatusDot online={device.online} disabled={device.disabled} />
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-medium text-white">{device.id}</div>
          <div className="truncate text-xs text-[var(--color-muted)]">{device.model ?? "Android device"}</div>
        </div>
        <Link to={`/devices/${encodeURIComponent(device.id)}`} className="text-xs text-[var(--color-accent)] hover:underline">
          Open
        </Link>
      </div>

      <div className="flex-1 space-y-4 overflow-y-auto p-3">
        <DeviceScreen deviceId={device.id} online={device.online} />

        {!device.online ? (
          <Button variant="secondary" className="w-full justify-center" onClick={() => connect.mutate()} disabled={connect.isPending}>
            {connect.isPending ? "Connecting…" : "Connect"}
          </Button>
        ) : null}

        <div className="rounded-lg border border-[var(--color-border)]">
          <Row label="Battery" value={tele ? `${tele.battery}%${tele.charging ? " ⚡" : ""}` : "—"} />
          <Row label="Screen" value={tele?.screen ?? "—"} />
          <Row label="Foreground" value={tele?.app ?? "—"} />
          <Row label="Android" value={tele?.android ?? "—"} />
        </div>

        <div className="flex flex-wrap gap-2">
          <Button variant="secondary" onClick={() => wake.mutate()} disabled={!device.online || wake.isPending}>
            <Sun size={15} /> Wake
          </Button>
          <Button variant="secondary" onClick={() => lock.mutate()} disabled={!device.online || lock.isPending}>
            <Lock size={15} /> Lock
          </Button>
          <Link to={`/devices/${encodeURIComponent(device.id)}`}>
            <Button variant="ghost">
              <Monitor size={15} /> Mirror &amp; tools
            </Button>
          </Link>
        </div>
      </div>
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between border-b border-[var(--color-border)] px-3 py-2 text-xs last:border-0">
      <span className="text-[var(--color-muted)]">{label}</span>
      <span className="truncate pl-3 text-right text-white">{value}</span>
    </div>
  );
}

/** A live screen preview by refreshing the screenshot endpoint on a short timer. */
function DeviceScreen({ deviceId, online }: { deviceId: string; online: boolean }) {
  const [tick, setTick] = useState(0);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    setFailed(false);
    setTick(0);
  }, [deviceId]);

  useEffect(() => {
    if (!online) {
      return;
    }
    const interval = window.setInterval(() => setTick((value) => value + 1), 1200);
    return () => window.clearInterval(interval);
  }, [online]);

  if (!online) {
    return (
      <div className="grid aspect-[9/16] max-h-80 w-full place-items-center rounded-lg border border-[var(--color-border)] bg-black/40 text-xs text-[var(--color-muted)]">
        Device offline
      </div>
    );
  }

  return (
    <div className="relative grid place-items-center overflow-hidden rounded-lg border border-[var(--color-border)] bg-black/40">
      <img
        key={tick}
        src={`/api/devices/${encodeURIComponent(deviceId)}/screenshot?t=${tick}`}
        alt={`Screen of ${deviceId}`}
        className="max-h-80 w-full object-contain"
        onError={() => setFailed(true)}
      />
      {failed ? (
        <span className="absolute bottom-1 right-2 rounded bg-black/60 px-1.5 py-0.5 text-[10px] text-amber-300">
          Screen unavailable
        </span>
      ) : (
        <span className="absolute bottom-1 right-2 rounded bg-black/60 px-1.5 py-0.5 text-[10px] text-emerald-300">live</span>
      )}
    </div>
  );
}
