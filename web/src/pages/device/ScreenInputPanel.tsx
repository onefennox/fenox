import { useMutation } from "@tanstack/react-query";
import { useState } from "react";

import { lockDevice, openUrl, readClipboard, sendInput, wakeDevice, writeClipboard } from "@/api/queries";
import type { Device } from "@/api/types";
import { Button, Card, ErrorText, Field, Input } from "@/components/ui";

const KEYS = ["HOME", "BACK", "APP_SWITCH", "ENTER", "DEL", "POWER", "VOLUME_UP", "VOLUME_DOWN", "SEARCH"];

export function ScreenInputPanel({ device }: { device: Device }) {
  const [text, setText] = useState("");
  const [url, setUrl] = useState("");
  const [tap, setTap] = useState({ x: "540", y: "1200" });
  const [clipboard, setClipboard] = useState<string | null>(null);

  const run = useMutation({
    mutationFn: (action: () => Promise<unknown>) => action(),
  });

  const disabled = !device.online || run.isPending;

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
      <Card className="space-y-3 p-5">
        <h2 className="text-sm font-semibold text-white">Power and keys</h2>
        <div className="flex flex-wrap gap-2">
          <Button variant="secondary" disabled={disabled} onClick={() => run.mutate(() => wakeDevice(device.id))}>
            Wake
          </Button>
          <Button variant="secondary" disabled={disabled} onClick={() => run.mutate(() => lockDevice(device.id))}>
            Lock
          </Button>
          {KEYS.map((key) => (
            <Button
              key={key}
              variant="ghost"
              disabled={disabled}
              onClick={() => run.mutate(() => sendInput(device.id, { type: "key", key }))}
            >
              {key.replace("APP_SWITCH", "RECENTS")}
            </Button>
          ))}
        </div>
      </Card>

      <Card className="space-y-3 p-5">
        <h2 className="text-sm font-semibold text-white">Text and clipboard</h2>
        <div className="flex gap-2">
          <Input value={text} onChange={(event) => setText(event.target.value)} placeholder="Type on the device" />
          <Button disabled={disabled || !text} onClick={() => run.mutate(() => sendInput(device.id, { type: "text", text }))}>
            Send
          </Button>
        </div>
        <div className="flex gap-2">
          <Button variant="secondary" disabled={disabled || !text} onClick={() => run.mutate(() => writeClipboard(device.id, text))}>
            Copy to device
          </Button>
          <Button
            variant="secondary"
            disabled={disabled}
            onClick={async () => {
              const result = await readClipboard(device.id);
              setClipboard(result.clipboard);
            }}
          >
            Read clipboard
          </Button>
        </div>
        {clipboard !== null ? <p className="truncate text-xs text-[var(--color-muted)]">{clipboard || "(empty)"}</p> : null}
      </Card>

      <Card className="space-y-3 p-5">
        <h2 className="text-sm font-semibold text-white">Tap and swipe</h2>
        <div className="flex items-end gap-2">
          <Field label="X">
            <Input value={tap.x} onChange={(event) => setTap({ ...tap, x: event.target.value })} />
          </Field>
          <Field label="Y">
            <Input value={tap.y} onChange={(event) => setTap({ ...tap, y: event.target.value })} />
          </Field>
          <Button
            disabled={disabled}
            onClick={() => run.mutate(() => sendInput(device.id, { type: "tap", x: Number(tap.x), y: Number(tap.y) }))}
          >
            Tap
          </Button>
        </div>
        <Button
          variant="secondary"
          disabled={disabled}
          onClick={() =>
            run.mutate(() =>
              sendInput(device.id, {
                type: "swipe",
                x: Number(tap.x),
                y: Number(tap.y),
                x2: Number(tap.x),
                y2: Math.max(0, Number(tap.y) - 600),
                duration: 300,
              }),
            )
          }
        >
          Swipe up from point
        </Button>
      </Card>

      <Card className="space-y-3 p-5">
        <h2 className="text-sm font-semibold text-white">Open a URL</h2>
        <div className="flex gap-2">
          <Input value={url} onChange={(event) => setUrl(event.target.value)} placeholder="https://example.com" />
          <Button disabled={disabled || !url} onClick={() => run.mutate(() => openUrl(device.id, url))}>
            Open
          </Button>
        </div>
        <a
          className="text-xs text-[var(--color-accent)] hover:underline"
          href={`/api/devices/${encodeURIComponent(device.id)}/record?seconds=10`}
        >
          Record a 10 second clip
        </a>
      </Card>

      <div className="lg:col-span-2">
        <ErrorText>{(run.error as Error | null)?.message}</ErrorText>
      </div>
    </div>
  );
}
