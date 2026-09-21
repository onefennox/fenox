import { useQuery } from "@tanstack/react-query";

import { getTelemetry, keys } from "@/api/queries";
import type { Device } from "@/api/types";
import { Card, Spinner } from "@/components/ui";

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between border-b border-[var(--color-border)] py-2 text-sm last:border-0">
      <span className="text-[var(--color-muted)]">{label}</span>
      <span className="truncate pl-4 text-right text-white">{value}</span>
    </div>
  );
}

/** Device summary and live telemetry. The screen itself lives in the sidebar. */
export function OverviewPanel({ device }: { device: Device }) {
  const telemetry = useQuery({
    queryKey: keys.telemetry(device.id),
    queryFn: () => getTelemetry(device.id),
    enabled: device.online,
    refetchInterval: 8000,
  });
  const tele = telemetry.data?.telemetry;

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
      <Card className="p-5">
        <h2 className="mb-3 text-sm font-semibold text-white">Device</h2>
        <Row label="Model" value={device.model ?? "Android device"} />
        <Row label="Transport" value={device.type === "wireless" ? "wireless (adb)" : device.type ?? "unknown"} />
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
        ) : tele ? (
          <>
            <Row label="Battery" value={`${tele.battery}%${tele.charging ? " (charging)" : ""}`} />
            <Row label="Screen" value={tele.screen} />
            <Row label="Android" value={tele.android} />
            <Row label="Storage" value={tele.storage} />
            <Row label="Foreground app" value={tele.app} />
            <Row label="Model (on device)" value={tele.model} />
          </>
        ) : null}
      </Card>

      <Card className="p-5 lg:col-span-2">
        <h2 className="mb-2 text-sm font-semibold text-white">Screen</h2>
        <p className="text-sm text-[var(--color-muted)]">
          The live screen is shown in the device panel on the right. Select the device there to keep it in view while you work
          here.
        </p>
      </Card>
    </div>
  );
}
