import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";

import {
  connectDevice,
  deleteDevice,
  discoverDevices,
  keys,
  listDevices,
  pairDevice,
  updateDevice,
} from "@/api/queries";
import type { Device } from "@/api/types";
import { Badge, Button, Card, ErrorText, Field, Input, Modal, Spinner, StatusDot } from "@/components/ui";

export function DevicesPage() {
  const queryClient = useQueryClient();
  const { data, isLoading, error } = useQuery({ queryKey: keys.devices, queryFn: listDevices });

  const [renameTarget, setRenameTarget] = useState<Device | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [removeTarget, setRemoveTarget] = useState<Device | null>(null);
  const [pairOpen, setPairOpen] = useState(false);
  const [pair, setPair] = useState({ ip: "", port: "", code: "" });

  const refresh = () => queryClient.invalidateQueries({ queryKey: keys.devices });

  const discover = useMutation({ mutationFn: discoverDevices, onSuccess: refresh });
  const connect = useMutation({ mutationFn: connectDevice, onSuccess: refresh });
  const update = useMutation({
    mutationFn: ({ id, patch }: { id: string; patch: Partial<Device> & { name?: string } }) => updateDevice(id, patch),
    onSuccess: refresh,
  });
  const remove = useMutation({ mutationFn: deleteDevice, onSuccess: refresh });
  const doPair = useMutation({
    mutationFn: () => pairDevice(pair.ip.trim(), pair.port.trim(), pair.code.trim()),
    onSuccess: () => {
      setPairOpen(false);
      setPair({ ip: "", port: "", code: "" });
      discover.mutate();
    },
  });

  if (isLoading) {
    return <Spinner label="Loading devices" />;
  }
  if (error) {
    return <p className="text-sm text-red-400">{(error as Error).message}</p>;
  }

  const devices = data?.devices ?? [];
  const pending = data?.pending ?? [];

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold text-white">Devices</h1>
          <p className="mt-1 text-sm text-[var(--color-muted)]">Connect, organize, and monitor your Android devices.</p>
        </div>
        <div className="flex gap-2">
          <Button variant="secondary" onClick={() => discover.mutate()} disabled={discover.isPending}>
            {discover.isPending ? "Searching…" : "Discover"}
          </Button>
          <Button onClick={() => setPairOpen(true)}>Pair device</Button>
        </div>
      </div>

      {discover.data && discover.data.added.length > 0 ? (
        <Card className="border-emerald-500/30 p-3 text-sm text-emerald-300">
          Added {discover.data.added.join(", ")}.
        </Card>
      ) : null}

      {pending.length > 0 ? (
        <Card className="border-amber-500/30 p-3 text-sm text-amber-300">
          {pending.map((item) => (
            <div key={item.id}>
              {item.id}: {item.state === "unauthorized" ? "waiting for the debugging prompt" : "offline"}
            </div>
          ))}
        </Card>
      ) : null}

      {devices.length === 0 ? (
        <Card className="p-8 text-center text-sm text-[var(--color-muted)]">
          No devices yet. Plug in a phone with USB debugging on, or use Discover for devices already on your network.
        </Card>
      ) : (
        <Card className="divide-y divide-[var(--color-border)]">
          {devices.map((device) => (
            <div key={device.id} className="flex items-center gap-4 p-4">
              <StatusDot online={device.online} disabled={device.disabled} />
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <Link to={`/devices/${encodeURIComponent(device.id)}`} className="truncate font-medium text-white hover:underline">
                    {device.id}
                  </Link>
                  <Badge>{device.type ?? "unknown"}</Badge>
                  {device.disabled ? <Badge tone="warn">disabled</Badge> : null}
                </div>
                <div className="truncate text-xs text-[var(--color-muted)]">
                  {device.model ?? "Android device"}
                  {device.serial ? ` · ${device.serial}` : ""}
                  {device.ip ? ` · ${device.ip}${device.port ? `:${device.port}` : ""}` : ""}
                </div>
              </div>
              <div className="flex items-center gap-1">
                {!device.online && !device.disabled ? (
                  <Button variant="ghost" onClick={() => connect.mutate(device.id)} disabled={connect.isPending}>
                    Connect
                  </Button>
                ) : null}
                <Button
                  variant="ghost"
                  onClick={() => {
                    setRenameTarget(device);
                    setRenameValue(device.id);
                  }}
                >
                  Rename
                </Button>
                <Button
                  variant="ghost"
                  onClick={() => update.mutate({ id: device.id, patch: { disabled: !device.disabled } })}
                >
                  {device.disabled ? "Enable" : "Disable"}
                </Button>
                <Button variant="ghost" onClick={() => setRemoveTarget(device)}>
                  Remove
                </Button>
              </div>
            </div>
          ))}
        </Card>
      )}

      {(update.error || connect.error) ? (
        <ErrorText>{((update.error ?? connect.error) as Error).message}</ErrorText>
      ) : null}

      {renameTarget ? (
        <Modal title="Rename device" onClose={() => setRenameTarget(null)}>
          <form
            className="space-y-4"
            onSubmit={(event) => {
              event.preventDefault();
              if (renameValue.trim() && renameValue.trim() !== renameTarget.id) {
                update.mutate(
                  { id: renameTarget.id, patch: { name: renameValue.trim() } },
                  { onSuccess: () => setRenameTarget(null) },
                );
              }
            }}
          >
            <Field label="Name">
              <Input autoFocus value={renameValue} onChange={(event) => setRenameValue(event.target.value)} />
            </Field>
            <ErrorText>{(update.error as Error | null)?.message}</ErrorText>
            <div className="flex justify-end gap-2">
              <Button type="button" variant="ghost" onClick={() => setRenameTarget(null)}>
                Cancel
              </Button>
              <Button type="submit" disabled={update.isPending}>
                Save
              </Button>
            </div>
          </form>
        </Modal>
      ) : null}

      {removeTarget ? (
        <Modal title="Remove device" onClose={() => setRemoveTarget(null)}>
          <p className="text-sm text-[var(--color-muted)]">
            Remove <span className="text-white">{removeTarget.id}</span> from Fenox? This does not unpair the phone; you
            can Discover it again.
          </p>
          <div className="mt-5 flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setRemoveTarget(null)}>
              Cancel
            </Button>
            <Button
              variant="danger"
              onClick={() => remove.mutate(removeTarget.id, { onSuccess: () => setRemoveTarget(null) })}
              disabled={remove.isPending}
            >
              Remove
            </Button>
          </div>
        </Modal>
      ) : null}

      {pairOpen ? (
        <Modal title="Pair over wireless debugging" onClose={() => setPairOpen(false)}>
          <form
            className="space-y-4"
            onSubmit={(event) => {
              event.preventDefault();
              doPair.mutate();
            }}
          >
            <p className="text-sm text-[var(--color-muted)]">
              On the phone, open Developer options, then Wireless debugging, then Pair device with pairing code.
            </p>
            <Field label="IP address">
              <Input value={pair.ip} onChange={(event) => setPair({ ...pair, ip: event.target.value })} placeholder="192.168.1.20" />
            </Field>
            <Field label="Pairing port">
              <Input value={pair.port} onChange={(event) => setPair({ ...pair, port: event.target.value })} placeholder="41234" />
            </Field>
            <Field label="Pairing code">
              <Input value={pair.code} onChange={(event) => setPair({ ...pair, code: event.target.value })} placeholder="123456" />
            </Field>
            <ErrorText>{(doPair.error as Error | null)?.message}</ErrorText>
            <div className="flex justify-end gap-2">
              <Button type="button" variant="ghost" onClick={() => setPairOpen(false)}>
                Cancel
              </Button>
              <Button type="submit" disabled={doPair.isPending || !pair.ip || !pair.port || !pair.code}>
                Pair
              </Button>
            </div>
          </form>
        </Modal>
      ) : null}
    </div>
  );
}
