import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, Plus } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";

import { connectDevice, keys, listDevices, mirrorStatus } from "@/api/queries";
import type { Device } from "@/api/types";
import { useActiveDevice } from "@/hooks/useActiveDevice";
import { MirrorStream, type MirrorPhase } from "@/components/MirrorStream";
import { PhoneFrame } from "@/components/PhoneFrame";
import { Badge, Button, StatusDot } from "@/components/ui";

/**
 * The right rail belongs to the selected phone. With nothing selected it lists
 * devices to pick from; once one is selected it shows that phone's screen alone,
 * streamed continuously.
 */
export function DeviceRail() {
  const { activeId, setActiveDevice } = useActiveDevice();
  const { data } = useQuery({ queryKey: keys.devices, queryFn: listDevices });
  const devices = data?.devices ?? [];
  const pending = data?.pending ?? [];
  const active = devices.find((device) => device.id === activeId) ?? null;

  if (active?.id) {
    return <DeviceScreenPane device={active} onBack={() => setActiveDevice(null)} />;
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
            Select a device to view its screen
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

function DeviceScreenPane({ device, onBack }: { device: Device; onBack: () => void }) {
  const queryClient = useQueryClient();
  const [phase, setPhase] = useState<MirrorPhase>("connecting");
  const [error, setError] = useState("");
  const [aspect, setAspect] = useState(9 / 19.5);
  const mirror = useQuery({
    queryKey: [...keys.info(device.id), "mirror"],
    queryFn: () => mirrorStatus(device.id),
    enabled: device.online,
  });
  const connect = useMutation({
    mutationFn: () => connectDevice(device.id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: keys.devices }),
  });

  const online = device.online && !device.disabled;
  const unavailable = Boolean(mirror.data && !mirror.data.available);

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
        {online && phase === "live" ? <Badge tone="accent">live</Badge> : null}
        <Link to={`/devices/${encodeURIComponent(device.id)}`} className="text-xs text-[var(--color-accent)] hover:underline">
          Open
        </Link>
      </div>

      <div className="flex flex-1 flex-col items-center justify-center gap-4 overflow-y-auto p-4">
        <PhoneFrame power={online} aspect={online && phase === "live" ? aspect : 9 / 19.5}>
          {online && !unavailable ? (
            <MirrorStream
              deviceId={device.id}
              onPhaseChange={setPhase}
              onError={setError}
              onSizeChange={(width, height) => setAspect(width / height)}
            />
          ) : online ? (
            <p className="px-4 text-center text-[11px] text-amber-300">Mirroring unavailable: {mirror.data?.reason}</p>
          ) : null}
        </PhoneFrame>

        {online && phase !== "live" ? (
          <p className="text-xs text-[var(--color-muted)]">
            {phase === "error" ? error || "Unavailable" : "Connecting to the screen…"}
          </p>
        ) : null}

        {!online && !device.disabled ? (
          <Button variant="secondary" onClick={() => connect.mutate()} disabled={connect.isPending}>
            {connect.isPending ? "Connecting…" : "Connect"}
          </Button>
        ) : null}
        {!device.online && device.disabled ? (
          <p className="text-xs text-[var(--color-muted)]">This device is disabled.</p>
        ) : null}
      </div>
    </div>
  );
}
