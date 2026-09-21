import { useMutation } from "@tanstack/react-query";
import {
  ArrowLeft, ChevronUp, CircleDot, Clipboard, ClipboardPaste, CornerDownLeft, ExternalLink, Home,
  Keyboard, Lock, MenuSquare, MousePointer2, Power, Search, Send, Smartphone, Trash2, Video, Volume1, Volume2,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useState } from "react";

import { lockDevice, openUrl, readClipboard, sendInput, wakeDevice, writeClipboard } from "@/api/queries";
import type { Device } from "@/api/types";
import { Button, Card, ErrorText, Field, Input } from "@/components/ui";

const KEYS: Array<{ key: string; label: string; icon: LucideIcon }> = [
  { key: "HOME", label: "Home", icon: Home },
  { key: "BACK", label: "Back", icon: ArrowLeft },
  { key: "APP_SWITCH", label: "Recent apps", icon: MenuSquare },
  { key: "ENTER", label: "Enter", icon: CornerDownLeft },
  { key: "DEL", label: "Delete", icon: Trash2 },
  { key: "SEARCH", label: "Search", icon: Search },
  { key: "VOLUME_UP", label: "Volume up", icon: Volume2 },
  { key: "VOLUME_DOWN", label: "Volume down", icon: Volume1 },
  { key: "POWER", label: "Power button", icon: Power },
];

function SectionTitle({ icon: Icon, title, detail }: { icon: LucideIcon; title: string; detail: string }) {
  return (
    <div className="flex items-start gap-3">
      <span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-[var(--color-accent)]/10 text-[var(--color-accent)]">
        <Icon size={18} />
      </span>
      <div>
        <h2 className="text-sm font-semibold text-white">{title}</h2>
        <p className="mt-0.5 text-xs leading-5 text-[var(--color-muted)]">{detail}</p>
      </div>
    </div>
  );
}

export function ScreenInputPanel({ device }: { device: Device }) {
  const [text, setText] = useState("");
  const [url, setUrl] = useState("");
  const [tap, setTap] = useState({ x: "540", y: "1200" });
  const [clipboard, setClipboard] = useState<string | null>(null);
  const run = useMutation({ mutationFn: (action: () => Promise<unknown>) => action() });
  const disabled = !device.online || run.isPending;

  return (
    <div className="space-y-4">
      {!device.online ? (
        <Card className="border-amber-500/30 p-4 text-sm text-amber-300">Connect this device to use remote controls.</Card>
      ) : null}

      <div className="grid grid-cols-1 gap-3 xl:grid-cols-5">
        <Card className="space-y-4 p-4 xl:col-span-3">
          <SectionTitle icon={Keyboard} title="Navigation and hardware keys" detail="Common phone controls, available without touching the physical device." />
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
            {KEYS.map(({ key, label, icon: Icon }) => (
              <Button key={key} variant="secondary" className="min-h-9 justify-start" disabled={disabled}
                onClick={() => run.mutate(() => sendInput(device.id, { type: "key", key }))}>
                <Icon size={16} className="text-[var(--color-accent)]" /> {label}
              </Button>
            ))}
          </div>
          <div className="flex flex-wrap gap-2 border-t border-[var(--color-border)] pt-4">
            <Button variant="secondary" disabled={disabled} onClick={() => run.mutate(() => wakeDevice(device.id))}>
              <Smartphone size={16} /> Wake screen
            </Button>
            <Button variant="secondary" disabled={disabled} onClick={() => run.mutate(() => lockDevice(device.id))}>
              <Lock size={16} /> Lock device
            </Button>
          </div>
        </Card>

        <Card className="space-y-4 p-4 xl:col-span-2">
          <SectionTitle icon={Send} title="Type on the phone" detail="Send text to whichever field is currently focused on the device." />
          <div className="flex gap-2">
            <Input value={text} onChange={(event) => setText(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && text && !disabled) run.mutate(() => sendInput(device.id, { type: "text", text }));
              }} placeholder="Enter text to type…" />
            <Button disabled={disabled || !text} onClick={() => run.mutate(() => sendInput(device.id, { type: "text", text }))}>
              <Send size={16} /> Send
            </Button>
          </div>
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-1">
            <Button variant="secondary" className="justify-center" disabled={disabled || !text}
              onClick={() => run.mutate(() => writeClipboard(device.id, text))}>
              <Clipboard size={16} /> Copy text to device
            </Button>
            <Button variant="secondary" className="justify-center" disabled={disabled}
              onClick={async () => setClipboard((await readClipboard(device.id)).clipboard)}>
              <ClipboardPaste size={16} /> Read device clipboard
            </Button>
          </div>
          {clipboard !== null ? (
            <div className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-3">
              <p className="mb-1 text-[10px] font-semibold tracking-wider text-[var(--color-muted)] uppercase">Device clipboard</p>
              <p className="break-words text-sm text-white">{clipboard || "Clipboard is empty"}</p>
            </div>
          ) : null}
        </Card>

        <Card className="space-y-4 p-4 xl:col-span-3">
          <SectionTitle icon={ExternalLink} title="Open a web address" detail="Launch a URL immediately in the phone’s default browser." />
          <div className="flex gap-2">
            <Input type="url" value={url} onChange={(event) => setUrl(event.target.value)} placeholder="https://example.com" />
            <Button disabled={disabled || !url} onClick={() => run.mutate(() => openUrl(device.id, url))}>
              <ExternalLink size={16} /> Open
            </Button>
          </div>
        </Card>

        <Card className="space-y-4 p-4 xl:col-span-2">
          <SectionTitle icon={Video} title="Screen recording" detail="Download a ten-second recording from the device." />
          <a className={`inline-flex min-h-10 items-center gap-2 rounded-md bg-[var(--color-panel-hover)] px-3 py-2 text-sm font-medium text-white transition hover:bg-[var(--color-border)] ${!device.online ? "pointer-events-none opacity-50" : ""}`}
            href={`/api/devices/${encodeURIComponent(device.id)}/record?seconds=10`}>
            <Video size={16} className="text-[var(--color-accent)]" /> Record and download clip
          </a>
        </Card>
      </div>

      <details className="group rounded-xl border border-[var(--color-border)] bg-[var(--color-panel)]">
        <summary className="flex cursor-pointer list-none items-center gap-3 p-4 text-sm font-medium text-white">
          <span className="grid h-8 w-8 place-items-center rounded-lg bg-[var(--color-panel-hover)] text-[var(--color-muted)]"><MousePointer2 size={16} /></span>
          Coordinate controls
          <span className="ml-auto text-xs font-normal text-[var(--color-muted)]">Advanced</span>
          <ChevronUp size={16} className="rotate-180 text-[var(--color-muted)] transition group-open:rotate-0" />
        </summary>
        <div className="border-t border-[var(--color-border)] p-4">
          <p className="mb-4 text-xs text-[var(--color-muted)]">The live phone accepts direct clicks and swipes. Use coordinates only for precise automation.</p>
          <div className="flex max-w-xl flex-wrap items-end gap-2">
            <Field label="X coordinate"><Input inputMode="numeric" value={tap.x} onChange={(event) => setTap({ ...tap, x: event.target.value })} /></Field>
            <Field label="Y coordinate"><Input inputMode="numeric" value={tap.y} onChange={(event) => setTap({ ...tap, y: event.target.value })} /></Field>
            <Button disabled={disabled} onClick={() => run.mutate(() => sendInput(device.id, { type: "tap", x: Number(tap.x), y: Number(tap.y) }))}>
              <CircleDot size={16} /> Tap point
            </Button>
            <Button variant="secondary" disabled={disabled}
              onClick={() => run.mutate(() => sendInput(device.id, { type: "swipe", x: Number(tap.x), y: Number(tap.y), x2: Number(tap.x), y2: Math.max(0, Number(tap.y) - 600), duration: 300 }))}>
              <ChevronUp size={16} /> Swipe up
            </Button>
          </div>
        </div>
      </details>
      <ErrorText>{(run.error as Error | null)?.message}</ErrorText>
    </div>
  );
}
