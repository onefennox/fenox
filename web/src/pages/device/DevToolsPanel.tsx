import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { getInfo, getProcesses, keys, readNotifications, sendNotification } from "@/api/queries";
import type { Device } from "@/api/types";
import { LogcatView } from "@/components/LogcatView";
import { Button, Card, ErrorText, Field, Input, Spinner } from "@/components/ui";

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between border-b border-[var(--color-border)] py-1.5 text-sm last:border-0">
      <span className="text-[var(--color-muted)]">{label}</span>
      <span className="truncate pl-4 text-right text-white">{value}</span>
    </div>
  );
}

export function DevToolsPanel({ device }: { device: Device }) {
  const [title, setTitle] = useState("Fenox");
  const [text, setText] = useState("");
  const [notifications, setNotifications] = useState<string | null>(null);

  const info = useQuery({ queryKey: keys.info(device.id), queryFn: () => getInfo(device.id), enabled: device.online });
  const processes = useQuery({
    queryKey: keys.processes(device.id),
    queryFn: () => getProcesses(device.id),
    enabled: device.online,
  });
  const notify = useMutation({ mutationFn: () => sendNotification(device.id, title, text) });

  if (!device.online) {
    return <Card className="p-6 text-sm text-[var(--color-muted)]">The device is offline.</Card>;
  }

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
      <Card className="p-5">
        <h2 className="mb-3 text-sm font-semibold text-white">Device</h2>
        {info.isLoading ? (
          <Spinner />
        ) : info.data ? (
          <>
            {Object.entries(info.data.props).map(([key, value]) => (
              <Row key={key} label={key} value={value} />
            ))}
            <Row label="Battery level" value={`${info.data.battery.level ?? "?"}%`} />
            <Row label="Battery temperature" value={`${info.data.battery.temperature ?? "?"}`} />
          </>
        ) : null}
      </Card>

      <Card className="p-5">
        <h2 className="mb-3 text-sm font-semibold text-white">Storage</h2>
        <pre className="max-h-40 overflow-auto whitespace-pre-wrap font-mono text-xs text-[var(--color-muted)]">
          {info.data?.storage ?? ""}
        </pre>
      </Card>

      <Card className="space-y-3 p-5">
        <h2 className="text-sm font-semibold text-white">Notifications</h2>
        <Field label="Title">
          <Input value={title} onChange={(event) => setTitle(event.target.value)} />
        </Field>
        <Field label="Text">
          <Input value={text} onChange={(event) => setText(event.target.value)} />
        </Field>
        <div className="flex gap-2">
          <Button disabled={!text || notify.isPending} onClick={() => notify.mutate()}>
            Send
          </Button>
          <Button
            variant="secondary"
            onClick={async () => setNotifications((await readNotifications(device.id)).notifications)}
          >
            Read active
          </Button>
        </div>
        {notifications ? (
          <pre className="max-h-40 overflow-auto whitespace-pre-wrap text-xs text-[var(--color-muted)]">{notifications}</pre>
        ) : null}
      </Card>

      <Card className="space-y-3 p-5">
        <h2 className="text-sm font-semibold text-white">Processes</h2>
        <pre className="max-h-40 overflow-auto whitespace-pre-wrap font-mono text-xs text-[var(--color-muted)]">
          {(processes.data?.processes ?? []).join("\n")}
        </pre>
      </Card>

      <Card className="p-5 lg:col-span-2">
        <h2 className="mb-3 text-sm font-semibold text-white">Logcat</h2>
        <LogcatView deviceId={device.id} />
      </Card>

      <div className="lg:col-span-2">
        <ErrorText>{(notify.error as Error | null)?.message}</ErrorText>
      </div>
    </div>
  );
}
