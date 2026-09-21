import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { getTelemetry, keys } from "@/api/queries";
import type { Device } from "@/api/types";
import { Button, Card, Spinner } from "@/components/ui";

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between border-b border-[var(--color-border)] py-1.5 text-sm last:border-0">
      <span className="text-[var(--color-muted)]">{label}</span>
      <span className="text-white">{value}</span>
    </div>
  );
}

export function OverviewPanel({ device }: { device: Device }) {
  const [shotKey, setShotKey] = useState(0);
  const telemetry = useQuery({
    queryKey: keys.telemetry(device.id),
    queryFn: () => getTelemetry(device.id),
    enabled: device.online,
    refetchInterval: 10000,
  });

  if (!device.online) {
    return <Card className="p-6 text-sm text-[var(--color-muted)]">Connect the device to read telemetry.</Card>;
  }

  const tele = telemetry.data?.telemetry;

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
      <Card className="p-5">
        <h2 className="mb-3 text-sm font-semibold text-white">Live telemetry</h2>
        {telemetry.isLoading ? (
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
          </>
        ) : null}
      </Card>

      <Card className="p-5 lg:col-span-2">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-white">Screen</h2>
          <Button variant="secondary" onClick={() => setShotKey((value) => value + 1)}>
            Refresh
          </Button>
        </div>
        <img
          key={shotKey}
          src={`/api/devices/${encodeURIComponent(device.id)}/screenshot?t=${shotKey}`}
          alt={`Screen of ${device.id}`}
          className="mx-auto max-h-[560px] rounded-lg border border-[var(--color-border)]"
        />
      </Card>
    </div>
  );
}
