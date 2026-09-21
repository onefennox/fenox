import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import { getTelemetry, keys, listDevices } from "@/api/queries";
import { Badge, Button, Card, Spinner, StatusDot } from "@/components/ui";

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between border-b border-[var(--color-border)] py-2 text-sm last:border-0">
      <span className="text-[var(--color-muted)]">{label}</span>
      <span className="text-white">{value}</span>
    </div>
  );
}

export function DeviceDetailPage() {
  const { id = "" } = useParams();
  const deviceId = decodeURIComponent(id);
  const [shotKey, setShotKey] = useState(0);

  const devices = useQuery({ queryKey: keys.devices, queryFn: listDevices });
  const device = devices.data?.devices.find((item) => item.id === deviceId);

  const telemetry = useQuery({
    queryKey: keys.telemetry(deviceId),
    queryFn: () => getTelemetry(deviceId),
    enabled: Boolean(device?.online),
    refetchInterval: 10000,
  });

  return (
    <div className="space-y-6">
      <div>
        <Link to="/devices" className="text-xs text-[var(--color-muted)] hover:text-white">
          &larr; Devices
        </Link>
        <div className="mt-2 flex items-center gap-3">
          {device ? <StatusDot online={device.online} disabled={device.disabled} /> : null}
          <h1 className="text-lg font-semibold text-white">{deviceId}</h1>
          {device ? <Badge>{device.type ?? "unknown"}</Badge> : null}
          {device?.online ? <Badge tone="accent">online</Badge> : <Badge tone="warn">offline</Badge>}
        </div>
      </div>

      {!device ? (
        <Card className="p-6 text-sm text-[var(--color-muted)]">This device is no longer registered.</Card>
      ) : (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          <Card className="p-5">
            <h2 className="mb-3 text-sm font-semibold text-white">Device</h2>
            <Row label="Model" value={device.model ?? "Android device"} />
            <Row label="Type" value={device.type ?? "unknown"} />
            <Row label="Serial" value={device.serial ?? "—"} />
            <Row label="Address" value={device.ip ? `${device.ip}${device.port ? `:${device.port}` : ""}` : "—"} />
            <Row label="State" value={device.disabled ? "disabled" : device.online ? "online" : "offline"} />
          </Card>

          <Card className="p-5">
            <div className="mb-3 flex items-center justify-between">
              <h2 className="text-sm font-semibold text-white">Live telemetry</h2>
              {telemetry.isFetching ? <span className="text-xs text-[var(--color-muted)]">refreshing…</span> : null}
            </div>
            {!device.online ? (
              <p className="text-sm text-[var(--color-muted)]">Connect the device to read telemetry.</p>
            ) : telemetry.isLoading ? (
              <Spinner />
            ) : telemetry.error ? (
              <p className="text-sm text-red-400">{(telemetry.error as Error).message}</p>
            ) : telemetry.data ? (
              <>
                <Row label="Battery" value={`${telemetry.data.telemetry.battery}%${telemetry.data.telemetry.charging ? " (charging)" : ""}`} />
                <Row label="Screen" value={telemetry.data.telemetry.screen} />
                <Row label="Android" value={telemetry.data.telemetry.android} />
                <Row label="Storage" value={telemetry.data.telemetry.storage} />
                <Row label="Foreground app" value={telemetry.data.telemetry.app} />
              </>
            ) : null}
          </Card>

          <Card className="p-5 lg:col-span-2">
            <div className="mb-3 flex items-center justify-between">
              <h2 className="text-sm font-semibold text-white">Screen</h2>
              <Button variant="secondary" onClick={() => setShotKey((value) => value + 1)} disabled={!device.online}>
                Refresh
              </Button>
            </div>
            {device.online ? (
              <img
                key={shotKey}
                src={`/api/devices/${encodeURIComponent(deviceId)}/screenshot?t=${shotKey}`}
                alt={`Screen of ${deviceId}`}
                className="mx-auto max-h-[560px] rounded-lg border border-[var(--color-border)]"
              />
            ) : (
              <p className="text-sm text-[var(--color-muted)]">The device is offline.</p>
            )}
          </Card>
        </div>
      )}
    </div>
  );
}
