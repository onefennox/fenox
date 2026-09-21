import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Cable, ChevronRight, Wifi } from "lucide-react";
import { useState, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";

import {
  connectDevice,
  connectWireless,
  deleteDevice,
  discoverDevices,
  keys,
  listDevices,
  pairDevice,
  updateDevice,
} from "@/api/queries";
import type { Device } from "@/api/types";
import { Badge, Button, Card, ErrorText, Field, Input, Modal, Spinner, StatusDot } from "@/components/ui";

function Steps({ items }: { items: string[] }) {
  return (
    <ol className="list-decimal space-y-1 pl-5 text-sm text-[var(--color-muted)]">
      {items.map((item) => (
        <li key={item}>{item}</li>
      ))}
    </ol>
  );
}

function ConnectCard({
  icon,
  title,
  subtitle,
  children,
}: {
  icon: ReactNode;
  title: string;
  subtitle: string;
  children: ReactNode;
}) {
  return (
    <Card className="flex flex-col gap-3 p-5">
      <div className="flex items-center gap-2">
        <span className="text-[var(--color-accent)]">{icon}</span>
        <h2 className="text-sm font-semibold text-white">{title}</h2>
      </div>
      <p className="text-xs text-[var(--color-muted)]">{subtitle}</p>
      {children}
    </Card>
  );
}

export function DevicesPage() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const { data, isLoading, error } = useQuery({ queryKey: keys.devices, queryFn: listDevices });
  const openDevice = (deviceId: string) => navigate(`/devices/${encodeURIComponent(deviceId)}`);

  const [pairOpen, setPairOpen] = useState(false);
  const [addressOpen, setAddressOpen] = useState(false);
  const [renameTarget, setRenameTarget] = useState<Device | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [removeTarget, setRemoveTarget] = useState<Device | null>(null);
  const [pair, setPair] = useState({ ip: "", port: "", code: "" });
  const [address, setAddress] = useState({ ip: "", port: "" });

  const refresh = () => queryClient.invalidateQueries({ queryKey: keys.devices });
  const scanUsb = useMutation({ mutationFn: () => discoverDevices("usb"), onSuccess: refresh });
  const findWireless = useMutation({ mutationFn: () => discoverDevices("wireless"), onSuccess: refresh });
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
      findWireless.mutate();
    },
  });
  const doConnect = useMutation({
    mutationFn: () => connectWireless(address.ip.trim(), address.port.trim()),
    onSuccess: () => {
      setAddressOpen(false);
      setAddress({ ip: "", port: "" });
      refresh();
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
  const unauthorized = pending.filter((item) => item.state === "unauthorized");

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-lg font-semibold text-white">Devices</h1>
        <p className="mt-1 text-sm text-[var(--color-muted)]">
          Connect a phone over USB or wireless debugging. Everything else happens in the browser.
        </p>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <ConnectCard
          icon={<Cable size={18} />}
          title="USB debugging"
          subtitle="The most reliable connection. Best while setting up a new phone."
        >
          <Steps
            items={[
              "On the phone, enable Developer options (tap Build number seven times).",
              "Turn on USB debugging in Developer options.",
              "Plug the phone in and accept the “Allow USB debugging?” prompt.",
            ]}
          />
          <div className="mt-auto flex items-center gap-3 pt-2">
            <Button onClick={() => scanUsb.mutate()} disabled={scanUsb.isPending}>
              {scanUsb.isPending ? "Scanning…" : "Scan for USB devices"}
            </Button>
            {unauthorized.length > 0 ? (
              <span className="text-xs text-amber-300">Waiting on the phone&apos;s prompt</span>
            ) : null}
          </div>
        </ConnectCard>

        <ConnectCard
          icon={<Wifi size={18} />}
          title="Wireless debugging"
          subtitle="No cable. The phone and this machine must be on the same network."
        >
          <Steps
            items={[
              "On the phone, turn on Wireless debugging in Developer options.",
              "For a phone that has never been paired, tap “Pair device with pairing code”.",
              "After pairing, Fenox finds it on the network automatically.",
            ]}
          />
          <div className="mt-auto flex flex-wrap gap-2 pt-2">
            <Button onClick={() => findWireless.mutate()} disabled={findWireless.isPending}>
              {findWireless.isPending ? "Searching…" : "Find phones on network"}
            </Button>
            <Button variant="secondary" onClick={() => setPairOpen(true)}>
              Pair a new phone
            </Button>
            <Button variant="ghost" onClick={() => setAddressOpen(true)}>
              Connect by address
            </Button>
          </div>
        </ConnectCard>
      </div>

      {scanUsb.data && scanUsb.data.added.length > 0 ? (
        <Card className="border-emerald-500/30 p-3 text-sm text-emerald-300">
          Added {scanUsb.data.added.join(", ")}.
        </Card>
      ) : null}
      {findWireless.data && findWireless.data.added.length > 0 ? (
        <Card className="border-emerald-500/30 p-3 text-sm text-emerald-300">
          Connected {findWireless.data.added.join(", ")}.
        </Card>
      ) : null}
      {findWireless.data && findWireless.data.pending.length > 0 ? (
        <Card className="border-amber-500/30 p-3 text-sm text-amber-300">
          Found {findWireless.data.pending.map((item) => item.ip).join(", ")} but not paired yet. Use “Pair a new phone”.
        </Card>
      ) : null}

      {unauthorized.length > 0 ? (
        <Card className="border-amber-500/30 p-3 text-sm text-amber-300">
          {unauthorized.map((item) => (
            <div key={item.id}>
              {item.id} is waiting for authorization — accept the “Allow USB debugging?” prompt on the phone.
            </div>
          ))}
        </Card>
      ) : null}

      {devices.length === 0 ? (
        <Card className="p-8 text-center text-sm text-[var(--color-muted)]">
          No devices yet. Use one of the two methods above to connect a phone.
        </Card>
      ) : (
        <Card className="divide-y divide-[var(--color-border)]">
          {devices.map((device) => (
            <div
              key={device.id}
              role="button"
              tabIndex={0}
              aria-label={`Open ${device.id}`}
              onClick={() => openDevice(device.id)}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  openDevice(device.id);
                }
              }}
              className="group flex cursor-pointer items-center gap-4 p-4 transition hover:bg-[var(--color-panel-hover)] focus:bg-[var(--color-panel-hover)] focus:outline-none"
            >
              <StatusDot online={device.online} disabled={device.disabled} />
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="truncate font-medium text-white">{device.id}</span>
                  <Badge>{device.type === "wireless" ? "wireless" : device.type === "usb" ? "usb" : device.type ?? "unknown"}</Badge>
                  {device.disabled ? <Badge tone="warn">disabled</Badge> : null}
                  {device.online ? <Badge tone="accent">online</Badge> : <Badge tone="warn">offline</Badge>}
                </div>
                <div className="truncate text-xs text-[var(--color-muted)]">
                  {device.model ?? "Android device"}
                  {device.serial ? ` · ${device.serial}` : ""}
                  {device.ip ? ` · ${device.ip}${device.port ? `:${device.port}` : ""}` : ""}
                </div>
              </div>
              <div className="flex items-center gap-1" onClick={(event) => event.stopPropagation()}>
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
                <Button variant="ghost" onClick={() => update.mutate({ id: device.id, patch: { disabled: !device.disabled } })}>
                  {device.disabled ? "Enable" : "Disable"}
                </Button>
                <Button variant="ghost" onClick={() => setRemoveTarget(device)}>
                  Remove
                </Button>
              </div>
              <ChevronRight
                size={18}
                className="shrink-0 text-[var(--color-muted)] transition group-hover:text-white"
              />
            </div>
          ))}
        </Card>
      )}

      {(update.error || connect.error) ? (
        <ErrorText>{((update.error ?? connect.error) as Error).message}</ErrorText>
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
              On the phone: Developer options → Wireless debugging → <strong className="text-white">Pair device with pairing code</strong>.
              This shows an IP address, a pairing port, and a six-digit code. Pairing is done once per network.
            </p>
            <Field label="IP address">
              <Input value={pair.ip} onChange={(event) => setPair({ ...pair, ip: event.target.value })} placeholder="192.168.1.20" />
            </Field>
            <Field label="Pairing port">
              <Input value={pair.port} onChange={(event) => setPair({ ...pair, port: event.target.value })} placeholder="41234" />
            </Field>
            <Field label="Six-digit code">
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

      {addressOpen ? (
        <Modal title="Connect by address" onClose={() => setAddressOpen(false)}>
          <form
            className="space-y-4"
            onSubmit={(event) => {
              event.preventDefault();
              doConnect.mutate();
            }}
          >
            <p className="text-sm text-[var(--color-muted)]">
              Use the <strong className="text-white">IP address and port on the main Wireless debugging screen</strong> (not the
              pairing port). Useful when mDNS discovery is blocked on your network.
            </p>
            <Field label="IP address">
              <Input value={address.ip} onChange={(event) => setAddress({ ...address, ip: event.target.value })} placeholder="192.168.1.20" />
            </Field>
            <Field label="Connection port">
              <Input value={address.port} onChange={(event) => setAddress({ ...address, port: event.target.value })} placeholder="37001" />
            </Field>
            <ErrorText>{(doConnect.error as Error | null)?.message}</ErrorText>
            <div className="flex justify-end gap-2">
              <Button type="button" variant="ghost" onClick={() => setAddressOpen(false)}>
                Cancel
              </Button>
              <Button type="submit" disabled={doConnect.isPending || !address.ip || !address.port}>
                Connect
              </Button>
            </div>
          </form>
        </Modal>
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
            Remove <span className="text-white">{removeTarget.id}</span> from Fenox? This does not unpair the phone; you can
            connect it again.
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
    </div>
  );
}
