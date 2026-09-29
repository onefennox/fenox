import { useMutation, useQuery } from "@tanstack/react-query";
import { BatteryMedium, HardDrive, Search, Thermometer } from "lucide-react";
import { useMemo, useState } from "react";

import { getInfo, getProcesses, keys, readNotifications, sendNotification } from "@/api/queries";
import type { Device } from "@/api/types";
import { LogcatView } from "@/components/LogcatView";
import { Button, Card, EmptyState, ErrorText, Field, Input, Skeleton, SkeletonRows } from "@/components/ui";
import { cn } from "@/lib/format";
import { toast } from "@/lib/toast";

/** A labelled proportion. Turns a number into something readable at a glance. */
function Bar({
  label,
  detail,
  percent,
  tone,
}: {
  label: string;
  detail?: string;
  percent: number;
  tone?: string;
}) {
  const clamped = Math.max(0, Math.min(100, percent));
  const colour =
    tone ?? (clamped >= 90 ? "bg-[var(--color-danger)]" : clamped >= 75 ? "bg-[var(--color-warning)]" : "bg-[var(--color-accent)]");
  return (
    <div className="space-y-1">
      <div className="flex items-baseline justify-between gap-2 text-xs">
        <span className="truncate text-[var(--color-muted)]">{label}</span>
        <span className="tnum shrink-0 text-[var(--color-text)]">
          {detail ?? `${clamped.toFixed(0)}%`}
        </span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-[var(--color-border)]">
        <div className={cn("h-full rounded-full transition-[width] duration-500", colour)} style={{ width: `${clamped}%` }} />
      </div>
    </div>
  );
}

/**
 * `df` output as bars.
 *
 * The device prints a table, so this parses tolerantly and returns nothing at
 * all when the shape is unfamiliar — the caller falls back to showing the raw
 * text rather than inventing numbers.
 */
function parseStorage(text: string): Array<{ mount: string; used: number; size: string; usedText: string }> {
  const rows: Array<{ mount: string; used: number; size: string; usedText: string }> = [];
  for (const line of (text || "").split("\n")) {
    const parts = line.trim().split(/\s+/);
    if (parts.length < 6 || parts[0] === "Filesystem") continue;
    const percent = parts.find((part) => /^\d+%$/.test(part));
    if (!percent) continue;
    rows.push({
      mount: parts[parts.length - 1],
      used: Number.parseInt(percent, 10),
      size: parts[1],
      usedText: `${parts[2]} of ${parts[1]}`,
    });
  }
  return rows;
}

function Stat({ icon, label, value, hint }: { icon: React.ReactNode; label: string; value: string; hint?: string }) {
  return (
    <div className="flex items-center gap-3 rounded-[var(--radius-md)] border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-2.5">
      <span className="grid h-8 w-8 shrink-0 place-items-center rounded-[var(--radius-md)] bg-[var(--color-elevated)] text-[var(--color-muted)]">
        {icon}
      </span>
      <div className="min-w-0">
        <p className="text-[10px] tracking-wider text-[var(--color-subtle)] uppercase">{label}</p>
        <p className="truncate text-sm font-medium">{value}</p>
        {hint ? <p className="truncate text-[11px] text-[var(--color-subtle)]">{hint}</p> : null}
      </div>
    </div>
  );
}

export function DevToolsPanel({ device }: { device: Device }) {
  const [title, setTitle] = useState("Fenox");
  const [text, setText] = useState("");
  const [notifications, setNotifications] = useState<string | null>(null);
  const [processFilter, setProcessFilter] = useState("");

  const info = useQuery({ queryKey: keys.info(device.id), queryFn: () => getInfo(device.id), enabled: device.online });
  const processes = useQuery({
    queryKey: keys.processes(device.id),
    queryFn: () => getProcesses(device.id),
    enabled: device.online,
  });
  const notify = useMutation({
    mutationFn: () => sendNotification(device.id, title, text),
    onSuccess: () => toast.success("Notification sent"),
    onError: (error: Error) => toast.error("Could not send", error.message),
  });

  const storage = useMemo(() => parseStorage(info.data?.storage ?? ""), [info.data?.storage]);
  const battery = info.data?.battery ?? {};
  const level = Number.parseFloat(String(battery.level ?? ""));
  const temperature = String(battery.temperature ?? "");

  const list = processes.data?.processes ?? [];
  const shown = processFilter
    ? list.filter((line) => line.toLowerCase().includes(processFilter.toLowerCase()))
    : list;

  if (!device.online) {
    return (
      <Card>
        <EmptyState title="Device offline" description="Connect the phone to read diagnostics." />
      </Card>
    );
  }

  return (
    <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
      <Card className="p-4">
        <h2 className="mb-3 text-sm font-semibold">Health</h2>
        {info.isLoading ? (
          <div className="space-y-2">
            <Skeleton className="h-12" />
            <Skeleton className="h-12" />
          </div>
        ) : (
          <>
            <div className="mb-3 grid grid-cols-1 gap-2 sm:grid-cols-2">
              <Stat
                icon={<BatteryMedium size={15} />}
                label="Battery"
                value={Number.isFinite(level) ? `${level}%` : "—"}
                hint={battery.charging ? "charging" : undefined}
              />
              <Stat
                icon={<Thermometer size={15} />}
                label="Temperature"
                value={temperature && temperature !== "?" ? `${temperature}°C` : "—"}
              />
            </div>
            {Number.isFinite(level) ? (
              <Bar
                label="Charge"
                percent={level}
                tone={level > 50 ? "bg-[var(--color-success)]" : level > 20 ? "bg-[var(--color-warning)]" : "bg-[var(--color-danger)]"}
                detail={`${level}%${battery.charging ? " ↑" : ""}`}
              />
            ) : null}
          </>
        )}
      </Card>

      <Card className="p-4">
        <div className="mb-3 flex items-center gap-2">
          <HardDrive size={14} className="text-[var(--color-subtle)]" />
          <h2 className="text-sm font-semibold">Storage</h2>
        </div>
        {info.isLoading ? (
          <SkeletonRows rows={2} />
        ) : storage.length > 0 ? (
          <div className="space-y-3">
            {storage.slice(0, 4).map((row) => (
              <Bar key={row.mount} label={row.mount} percent={row.used} detail={row.usedText} />
            ))}
          </div>
        ) : (
          // The device's table was not in a shape we recognise; show it as-is
          // rather than pretend to have parsed it.
          <pre className="scroll-thin max-h-40 overflow-auto font-mono text-[11px] whitespace-pre-wrap text-[var(--color-muted)]">
            {info.data?.storage || "—"}
          </pre>
        )}
      </Card>

      <Card className="p-4 lg:col-span-2">
        <h2 className="mb-3 text-sm font-semibold">Device properties</h2>
        {info.isLoading ? (
          <SkeletonRows rows={4} />
        ) : (
          <dl className="grid grid-cols-1 gap-x-6 gap-y-1 sm:grid-cols-2 lg:grid-cols-3">
            {Object.entries(info.data?.props ?? {}).map(([key, value]) => (
              <div
                key={key}
                className="flex items-baseline justify-between gap-3 border-b border-[var(--color-border)] py-1 text-sm last:border-0"
              >
                <dt className="shrink-0 text-[var(--color-muted)]">{key}</dt>
                <dd className="truncate text-right">{value}</dd>
              </div>
            ))}
          </dl>
        )}
      </Card>

      <Card className="space-y-3 p-4">
        <h2 className="text-sm font-semibold">Notifications</h2>
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          <Field label="Title">
            <Input value={title} onChange={(event) => setTitle(event.target.value)} />
          </Field>
          <Field label="Text">
            <Input value={text} onChange={(event) => setText(event.target.value)} />
          </Field>
        </div>
        <div className="flex gap-2">
          <Button size="sm" disabled={!text || notify.isPending} onClick={() => notify.mutate()}>
            {notify.isPending ? "Sending…" : "Send"}
          </Button>
          <Button
            size="sm"
            variant="secondary"
            onClick={async () => setNotifications((await readNotifications(device.id)).notifications)}
          >
            Read active
          </Button>
        </div>
        {notifications ? (
          <pre className="scroll-thin max-h-40 overflow-auto rounded-[var(--radius-md)] bg-[var(--color-surface)] p-2 font-mono text-[11px] whitespace-pre-wrap text-[var(--color-muted)]">
            {notifications}
          </pre>
        ) : null}
      </Card>

      <Card className="flex flex-col p-4">
        <div className="mb-2 flex items-center gap-2">
          <h2 className="text-sm font-semibold">Processes</h2>
          <span className="tnum text-xs text-[var(--color-subtle)]">{shown.length}</span>
          <div className="relative ml-auto w-40">
            <Search size={12} className="absolute top-1/2 left-2 -translate-y-1/2 text-[var(--color-subtle)]" />
            <Input
              value={processFilter}
              onChange={(event) => setProcessFilter(event.target.value)}
              placeholder="Filter"
              className="h-7 pl-7 text-xs"
            />
          </div>
        </div>
        {processes.isLoading ? (
          <SkeletonRows rows={4} />
        ) : (
          <pre className="scroll-thin max-h-52 overflow-auto font-mono text-[11px] whitespace-pre-wrap text-[var(--color-muted)]">
            {shown.join("\n") || "—"}
          </pre>
        )}
      </Card>

      <Card className="p-4 lg:col-span-2">
        <h2 className="mb-3 text-sm font-semibold">Logcat</h2>
        <LogcatView deviceId={device.id} />
      </Card>

      <div className="lg:col-span-2">
        <ErrorText>{(notify.error as Error | null)?.message}</ErrorText>
      </div>
    </div>
  );
}
