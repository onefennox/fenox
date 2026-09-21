import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Cable, ChevronRight, RefreshCw, Wifi } from "lucide-react";
import { useState, type ReactNode } from "react";
import { Link } from "react-router-dom";

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

function StatusRow({ children }: { children: ReactNode }) {
  return <div className="flex items-center gap-2 py-2 text-sm">{children}</div>;
}

export function ConnectPage() {
  const queryClient = useQueryClient();
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
  const list = method === "usb" ? all.filter((d) => d.type !== "wireless") : all.filter((d) => d.type === "wireless");
  const unauthorized = pending.filter((item) => item.state === "unauthorized");
  const discoveredUnpaired = (scan.data?.pending ?? []).filter((item) => item.ip);

  const addDiagnostic = (() => {
    if (!tools.data) return null;
    if (!tools.data.adb.client && !tools.data.adb.server) return "adb was not found on this machine.";
    if (tools.data.os === "wsl" && !tools.data.adb.server) {
      return "Windows adb was not found; USB devices need Android Platform Tools installed on Windows.";
    }
    return null;
  })();

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-lg font-semibold text-white">Connect a device</h1>
        <p className="mt-1 text-sm text-[var(--color-muted)]">
          Connect an Android phone over USB or wireless debugging. Fenox finds it and keeps it up to date.
        </p>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1fr_360px]">
        <Card className="space-y-5 p-5">
          <div className="grid grid-cols-2 gap-2">
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

        <Card className="flex flex-col p-5">
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-sm font-semibold text-white">Status</h2>
            <button
              className="cursor-pointer text-[var(--color-muted)] hover:text-white"
              onClick={() => scan.mutate()}
              disabled={scan.isPending}
              aria-label="Scan again"
            >
              <RefreshCw size={15} className={scan.isPending ? "animate-spin" : ""} />
            </button>
          </div>

          {devices.isLoading ? (
            <Spinner label="Checking devices" />
          ) : (
            <div className="divide-y divide-[var(--color-border)]">
              {list.map((device: Device) => (
                <StatusRow key={device.id}>
                  <StatusDot online={device.online} disabled={device.disabled} />
                  <span className="min-w-0 flex-1 truncate text-white">{device.id}</span>
                  {device.online ? <Badge tone="accent">online</Badge> : <Badge tone="warn">offline</Badge>}
                  {!device.online && !device.disabled ? (
                    <Button variant="ghost" onClick={() => connect.mutate(device.id)} disabled={connect.isPending}>
                      Connect
                    </Button>
                  ) : (
                    <Link
                      to={`/devices/${encodeURIComponent(device.id)}`}
                      className="flex items-center gap-1 text-xs text-[var(--color-accent)] hover:underline"
                    >
                      Open <ChevronRight size={13} />
                    </Link>
                  )}
                </StatusRow>
              ))}

              {method === "usb"
                ? unauthorized.map((item) => (
                    <StatusRow key={item.id}>
                      <span className="h-2 w-2 rounded-full bg-amber-400" />
                      <span className="min-w-0 flex-1 truncate text-white">{item.id}</span>
                      <span className="text-right text-xs text-amber-300">Accept the prompt on the phone</span>
                    </StatusRow>
                  ))
                : null}

              {method === "wireless"
                ? discoveredUnpaired.map((item) => (
                    <StatusRow key={item.ip}>
                      <span className="h-2 w-2 rounded-full bg-amber-400" />
                      <span className="min-w-0 flex-1 truncate text-white">{item.ip}</span>
                      <span className="text-right text-xs text-amber-300">Needs pairing</span>
                    </StatusRow>
                  ))
                : null}

              {list.length === 0 && unauthorized.length === 0 && discoveredUnpaired.length === 0 ? (
                <p className="py-3 text-sm text-[var(--color-muted)]">
                  {method === "usb"
                    ? "Nothing yet. Check the phone is unlocked and the USB prompt was accepted, then scan again."
                    : "Nothing yet. Turn on Wireless debugging, then search again."}
                </p>
              ) : null}
            </div>
          )}

          {addDiagnostic ? (
            <p className="mt-4 rounded-md border border-amber-500/30 p-2 text-xs text-amber-300">{addDiagnostic}</p>
          ) : null}
        </Card>
      </div>

      <Card className="p-4 text-xs text-[var(--color-muted)]">
        Devices are detected continuously once connected, so a phone that appears later shows up on its own. Manage the ones
        you already have on the <Link to="/devices" className="text-[var(--color-accent)] hover:underline">Devices</Link> page.
      </Card>
    </div>
  );
}
