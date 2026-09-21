import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { keys, listDevices } from "@/api/queries";
import { Card, Spinner } from "@/components/ui";

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

      <div className="text-sm">
        <Link to="/devices" className="text-[var(--color-accent)] hover:underline">
          Manage devices
        </Link>
      </div>
    </div>
  );
}
