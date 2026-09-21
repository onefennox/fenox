import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Cable, ChevronRight, RefreshCw, Wifi } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import {
  connectDevice,
  connectWireless,
  discoverDevices,
  getTools,
  keys,
  listDevices,
  pairDevice,
} from "@/api/queries";
import type { Device } from "@/api/types";
import { Badge, Button, Card, ErrorText, Field, Input, Spinner, StatusDot } from "@/components/ui";

type Method = "usb" | "wireless";

function Steps({ items }: { items: string[] }) {
  return (
    <ol className="list-decimal space-y-1.5 pl-5 text-sm text-[var(--color-muted)]">
      {items.map((item) => (
        <li key={item}>{item}</li>
      ))}
    </ol>
  );
}

export function ConnectPage() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [method, setMethod] = useState<Method>("usb");
  const [pair, setPair] = useState({ ip: "", port: "", code: "" });
  const [address, setAddress] = useState({ ip: "", port: "" });
  const [showAdvanced, setShowAdvanced] = useState(false);

  const devices = useQuery({ queryKey: keys.devices, queryFn: listDevices });
  const tools = useQuery({ queryKey: ["tools"], queryFn: getTools });

  const refresh = () => queryClient.invalidateQueries({ queryKey: keys.devices });
  const scan = useMutation({ mutationFn: () => discoverDevices(method), onSuccess: refresh });
  const connect = useMutation({ mutationFn: connectDevice, onSuccess: refresh });
  const doPair = useMutation({
    mutationFn: () => pairDevice(pair.ip.trim(), pair.port.trim(), pair.code.trim()),
    onSuccess: () => {
      setPair({ ip: "", port: "", code: "" });
      scan.mutate();
    },
  });
  const doConnect = useMutation({
    mutationFn: () => connectWireless(address.ip.trim(), address.port.trim()),
    onSuccess: () => {
      setAddress({ ip: "", port: "" });
      refresh();
    },
  });

  const all = devices.data?.devices ?? [];
  const pending = devices.data?.pending ?? [];
  const unauthorized = pending.filter((item) => item.state === "unauthorized");
  const discoveredUnpaired = (scan.data?.pending ?? []).filter((item) => item.ip);
  const openDevice = (id: string) => navigate(`/devices/${encodeURIComponent(id)}`);

  const diagnostic = (() => {
    if (!tools.data) return null;
    if (!tools.data.adb.client && !tools.data.adb.server) return "adb was not found on this machine.";
    if (tools.data.os === "wsl" && !tools.data.adb.server) {
      return "Windows adb was not found; USB devices need Android Platform Tools installed on Windows.";
    }
    return null;
  })();

  const rows = all.length + unauthorized.length + discoveredUnpaired.length;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-lg font-semibold text-white">Connect a device</h1>
        <p className="mt-1 text-sm text-[var(--color-muted)]">
          Connect an Android phone over USB or wireless debugging. Fenox finds it and keeps it up to date.
        </p>
      </div>

      <Card className="space-y-5 p-5">
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          <button
            onClick={() => setMethod("usb")}
            className={`flex cursor-pointer items-center gap-3 rounded-lg border p-3 text-left text-sm transition ${
              method === "usb"
                ? "border-[var(--color-accent)] bg-[var(--color-panel-hover)] text-white"
                : "border-[var(--color-border)] text-[var(--color-muted)] hover:text-white"
            }`}
          >
            <Cable size={18} />
            <span>
              <span className="block font-medium">USB debugging</span>
              <span className="text-xs text-[var(--color-muted)]">Most reliable; good for setup</span>
            </span>
          </button>
          <button
            onClick={() => setMethod("wireless")}
            className={`flex cursor-pointer items-center gap-3 rounded-lg border p-3 text-left text-sm transition ${
              method === "wireless"
                ? "border-[var(--color-accent)] bg-[var(--color-panel-hover)] text-white"
                : "border-[var(--color-border)] text-[var(--color-muted)] hover:text-white"
            }`}
          >
            <Wifi size={18} />
            <span>
              <span className="block font-medium">Wireless debugging</span>
              <span className="text-xs text-[var(--color-muted)]">No cable; same network</span>
            </span>
          </button>
        </div>

        {method === "usb" ? (
          <div className="space-y-4">
            <Steps
              items={[
                "On the phone: Settings → About phone → tap Build number seven times to unlock Developer options.",
                "In Developer options, turn on USB debugging.",
                "Plug the phone into this computer and accept the “Allow USB debugging?” prompt.",
              ]}
            />
            <Button onClick={() => scan.mutate()} disabled={scan.isPending}>
              {scan.isPending ? "Scanning…" : "Scan for USB devices"}
            </Button>
          </div>
        ) : (
          <div className="space-y-4">
            <Steps
              items={[
                "On the phone: turn on Wireless debugging in Developer options.",
                "Keep the phone on the same network as this computer.",
                "If the phone has never been paired here, tap “Pair device with pairing code” and enter the details below.",
              ]}
            />
            <div className="flex flex-wrap gap-2">
              <Button onClick={() => scan.mutate()} disabled={scan.isPending}>
                {scan.isPending ? "Searching…" : "Find phones on network"}
              </Button>
              <Button variant="ghost" onClick={() => setShowAdvanced((open) => !open)}>
                {showAdvanced ? "Hide manual options" : "Manual options"}
              </Button>
            </div>

            {showAdvanced ? (
              <div className="space-y-4 rounded-lg border border-[var(--color-border)] p-4">
                <div className="space-y-3">
                  <p className="text-xs text-[var(--color-muted)]">
                    Pair a new phone. The pairing port and code are on the “Pair device with pairing code” screen.
                  </p>
                  <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
                    <Field label="IP address">
                      <Input value={pair.ip} onChange={(event) => setPair({ ...pair, ip: event.target.value })} placeholder="192.168.1.20" />
                    </Field>
                    <Field label="Pairing port">
                      <Input value={pair.port} onChange={(event) => setPair({ ...pair, port: event.target.value })} placeholder="41234" />
                    </Field>
                    <Field label="Code">
                      <Input value={pair.code} onChange={(event) => setPair({ ...pair, code: event.target.value })} placeholder="123456" />
                    </Field>
                  </div>
                  <Button
                    variant="secondary"
                    onClick={() => doPair.mutate()}
                    disabled={doPair.isPending || !pair.ip || !pair.port || !pair.code}
                  >
                    Pair phone
                  </Button>
                  <ErrorText>{(doPair.error as Error | null)?.message}</ErrorText>
                </div>

                <div className="space-y-3 border-t border-[var(--color-border)] pt-4">
                  <p className="text-xs text-[var(--color-muted)]">
                    Already paired? Connect directly using the IP and port on the main Wireless debugging screen (not the
                    pairing port).
                  </p>
                  <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
                    <Field label="IP address">
                      <Input value={address.ip} onChange={(event) => setAddress({ ...address, ip: event.target.value })} placeholder="192.168.1.20" />
                    </Field>
                    <Field label="Connection port">
                      <Input value={address.port} onChange={(event) => setAddress({ ...address, port: event.target.value })} placeholder="37001" />
                    </Field>
                  </div>
                  <Button
                    variant="secondary"
                    onClick={() => doConnect.mutate()}
                    disabled={doConnect.isPending || !address.ip || !address.port}
                  >
                    Connect
                  </Button>
                  <ErrorText>{(doConnect.error as Error | null)?.message}</ErrorText>
                </div>
              </div>
            ) : null}
          </div>
        )}
      </Card>

      <Card className="overflow-hidden">
        <div className="flex items-center justify-between border-b border-[var(--color-border)] px-4 py-3">
          <div>
            <h2 className="text-sm font-semibold text-white">Devices</h2>
            <p className="text-xs text-[var(--color-muted)]">Everything Fenox can see right now.</p>
          </div>
          <button
            className="cursor-pointer text-[var(--color-muted)] hover:text-white"
            onClick={() => scan.mutate()}
            disabled={scan.isPending}
            aria-label="Scan again"
          >
            <RefreshCw size={16} className={scan.isPending ? "animate-spin" : ""} />
          </button>
        </div>

        {devices.isLoading ? (
          <div className="p-6">
            <Spinner label="Checking devices" />
          </div>
        ) : rows === 0 ? (
          <p className="p-6 text-sm text-[var(--color-muted)]">
            Nothing yet. Follow the steps above; a phone that appears later shows up here on its own.
          </p>
        ) : (
          <table className="w-full text-left text-sm">
            <thead className="text-xs uppercase tracking-wide text-[var(--color-muted)]">
              <tr className="border-b border-[var(--color-border)]">
                <th className="px-4 py-2 font-medium">Status</th>
                <th className="px-4 py-2 font-medium">Device</th>
                <th className="hidden px-4 py-2 font-medium sm:table-cell">Transport</th>
                <th className="hidden px-4 py-2 font-medium md:table-cell">Details</th>
                <th className="px-4 py-2" />
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--color-border)]">
              {all.map((device: Device) => (
                <tr
                  key={device.id}
                  className="cursor-pointer transition hover:bg-[var(--color-panel-hover)]"
                  onClick={() => openDevice(device.id)}
                >
                  <td className="px-4 py-3">
                    <StatusDot online={device.online} disabled={device.disabled} />
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      <span className="text-white">{device.id}</span>
                      {device.disabled ? <Badge tone="warn">disabled</Badge> : device.online ? <Badge tone="accent">online</Badge> : <Badge tone="warn">offline</Badge>}
                    </div>
                  </td>
                  <td className="hidden px-4 py-3 text-[var(--color-muted)] sm:table-cell">
                    {device.type === "wireless" ? "wireless" : device.type === "usb" ? "usb" : device.type ?? "—"}
                  </td>
                  <td className="hidden px-4 py-3 text-[var(--color-muted)] md:table-cell">
                    {device.model ?? "Android device"}
                    {device.serial ? ` · ${device.serial}` : ""}
                    {device.ip ? ` · ${device.ip}${device.port ? `:${device.port}` : ""}` : ""}
                  </td>
                  <td className="px-4 py-3 text-right" onClick={(event) => event.stopPropagation()}>
                    {!device.online && !device.disabled ? (
                      <Button variant="ghost" onClick={() => connect.mutate(device.id)} disabled={connect.isPending}>
                        Connect
                      </Button>
                    ) : (
                      <Link
                        to={`/devices/${encodeURIComponent(device.id)}`}
                        className="inline-flex items-center gap-1 text-xs text-[var(--color-accent)] hover:underline"
                      >
                        Open <ChevronRight size={13} />
                      </Link>
                    )}
                  </td>
                </tr>
              ))}

              {unauthorized.map((item) => (
                <tr key={item.id}>
                  <td className="px-4 py-3">
                    <span className="inline-block h-2 w-2 rounded-full bg-amber-400" />
                  </td>
                  <td className="px-4 py-3 text-white">{item.id}</td>
                  <td className="hidden px-4 py-3 text-[var(--color-muted)] sm:table-cell">usb</td>
                  <td className="px-4 py-3 text-amber-300" colSpan={2}>
                    Waiting — accept the “Allow USB debugging?” prompt on the phone.
                  </td>
                </tr>
              ))}

              {discoveredUnpaired.map((item) => (
                <tr key={item.ip}>
                  <td className="px-4 py-3">
                    <span className="inline-block h-2 w-2 rounded-full bg-amber-400" />
                  </td>
                  <td className="px-4 py-3 text-white">{item.ip}</td>
                  <td className="hidden px-4 py-3 text-[var(--color-muted)] sm:table-cell">wireless</td>
                  <td className="px-4 py-3 text-amber-300" colSpan={2}>
                    Found, but not paired — use Manual options above.
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>

      {diagnostic ? (
        <Card className="border-amber-500/30 p-3 text-sm text-amber-300">{diagnostic}</Card>
      ) : null}

      <Card className="p-4 text-xs text-[var(--color-muted)]">
        Devices are detected continuously, so a phone that appears later shows up on its own. Manage the ones you already have
        on the <Link to="/devices" className="text-[var(--color-accent)] hover:underline">Devices</Link> page.
      </Card>
    </div>
  );
}
