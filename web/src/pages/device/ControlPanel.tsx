import { useMutation } from "@tanstack/react-query";
import { useState } from "react";

import { rebootDevice, runShell, setBrightness, setVolume, toggleService } from "@/api/queries";
import type { Device } from "@/api/types";
import { Button, Card, ErrorText, Field, Input } from "@/components/ui";

export function ControlPanel({ device }: { device: Device }) {
  const [rebootMode, setRebootMode] = useState("");
  const [volume, setVol] = useState(50);
  const [brightness, setBright] = useState(128);
  const [command, setCommand] = useState("");
  const [output, setOutput] = useState("");

  const run = useMutation({ mutationFn: (action: () => Promise<unknown>) => action() });
  const disabled = !device.online || run.isPending;

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
      <Card className="space-y-3 p-5">
        <h2 className="text-sm font-semibold text-white">Power state</h2>
        <div className="flex items-center gap-2">
          <select
            className="rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-2 text-sm text-white"
            value={rebootMode}
            onChange={(event) => setRebootMode(event.target.value)}
          >
            <option value="">System</option>
            <option value="recovery">Recovery</option>
            <option value="bootloader">Bootloader</option>
          </select>
          <Button variant="danger" disabled={disabled} onClick={() => run.mutate(() => rebootDevice(device.id, rebootMode))}>
            Reboot
          </Button>
        </div>
      </Card>

      <Card className="space-y-3 p-5">
        <h2 className="text-sm font-semibold text-white">Radios</h2>
        <div className="flex flex-wrap gap-2">
          {(["wifi", "data", "bluetooth"] as const).map((service) => (
            <div key={service} className="flex gap-1">
              <Button variant="secondary" disabled={disabled} onClick={() => run.mutate(() => toggleService(device.id, service, true))}>
                {service} on
              </Button>
              <Button variant="ghost" disabled={disabled} onClick={() => run.mutate(() => toggleService(device.id, service, false))}>
                off
              </Button>
            </div>
          ))}
        </div>
      </Card>

      <Card className="space-y-4 p-5">
        <h2 className="text-sm font-semibold text-white">Volume and brightness</h2>
        <Field label={`Volume ${volume}`}>
          <input type="range" min={0} max={100} value={volume} onChange={(event) => setVol(Number(event.target.value))} className="w-full" />
        </Field>
        <Button variant="secondary" disabled={disabled} onClick={() => run.mutate(() => setVolume(device.id, volume))}>
          Apply volume
        </Button>
        <Field label={`Brightness ${brightness}`}>
          <input
            type="range"
            min={0}
            max={255}
            value={brightness}
            onChange={(event) => setBright(Number(event.target.value))}
            className="w-full"
          />
        </Field>
        <Button variant="secondary" disabled={disabled} onClick={() => run.mutate(() => setBrightness(device.id, brightness))}>
          Apply brightness
        </Button>
      </Card>

      <Card className="space-y-3 p-5">
        <h2 className="text-sm font-semibold text-white">Shell</h2>
        <div className="flex gap-2">
          <Input value={command} onChange={(event) => setCommand(event.target.value)} placeholder="getprop ro.product.model" />
          <Button
            disabled={disabled || !command}
            onClick={async () => {
              const result = await runShell(device.id, command);
              setOutput(result.output);
            }}
          >
            Run
          </Button>
        </div>
        {output ? (
          <pre className="max-h-40 overflow-auto rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] p-2 text-xs text-[var(--color-muted)]">
            {output}
          </pre>
        ) : null}
      </Card>

      <div className="lg:col-span-2">
        <ErrorText>{(run.error as Error | null)?.message}</ErrorText>
      </div>
    </div>
  );
}
