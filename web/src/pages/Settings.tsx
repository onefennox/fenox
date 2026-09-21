import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { getSettings, getTools, rotateToken, updateSettings } from "@/api/queries";
import { Button, Card, ErrorText, Field, Input, Spinner } from "@/components/ui";

export function SettingsPage() {
  const queryClient = useQueryClient();
  const settings = useQuery({ queryKey: ["settings"], queryFn: getSettings });
  const tools = useQuery({ queryKey: ["tools"], queryFn: getTools });
  const [form, setForm] = useState({
    reach: "local",
    port: "8787",
    remote_domain: "",
    flutter_path: "",
    adb_path: "",
  });
  const [token, setToken] = useState<string | null>(null);

  useEffect(() => {
    if (settings.data) {
      setForm({
        reach: settings.data.reach,
        port: String(settings.data.port),
        remote_domain: settings.data.remote_domain,
        flutter_path: settings.data.flutter_path,
        adb_path: settings.data.adb_path,
      });
      setToken(settings.data.token);
    }
  }, [settings.data]);

  const save = useMutation({
    mutationFn: () =>
      updateSettings({
        reach: form.reach,
        port: Number(form.port),
        remote_domain: form.remote_domain,
        flutter_path: form.flutter_path,
        adb_path: form.adb_path,
      }),
    onSuccess: (data) => {
      setToken(data.token);
      queryClient.invalidateQueries({ queryKey: ["settings"] });
      queryClient.invalidateQueries({ queryKey: ["tools"] });
    },
  });
  const rotate = useMutation({ mutationFn: rotateToken, onSuccess: (data) => setToken(data.token) });

  if (settings.isLoading) {
    return <Spinner label="Loading settings" />;
  }
  if (settings.error || !settings.data) {
    return <p className="text-sm text-red-400">{(settings.error as Error | null)?.message ?? "Settings unavailable."}</p>;
  }

  const current = settings.data;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-lg font-semibold text-white">Settings</h1>
        <p className="mt-1 text-sm text-[var(--color-muted)]">How the hub is reached, and the token for scripts.</p>
      </div>

      <Card className="space-y-4 p-5">
        <h2 className="text-sm font-semibold text-white">Reach</h2>
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
          {current.reach_levels.map((level) => (
            <button
              key={level.id}
              onClick={() => setForm({ ...form, reach: level.id })}
              className={`cursor-pointer rounded-lg border p-3 text-left text-sm transition ${
                form.reach === level.id
                  ? "border-[var(--color-accent)] bg-[var(--color-panel-hover)] text-white"
                  : "border-[var(--color-border)] text-[var(--color-muted)] hover:text-white"
              }`}
            >
              {level.label}
            </button>
          ))}
        </div>
        <ul className="list-disc space-y-1 pl-5 text-xs text-[var(--color-muted)]">
          {current.notes.map((note) => (
            <li key={note}>{note}</li>
          ))}
        </ul>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <Field label="Port">
            <Input value={form.port} onChange={(event) => setForm({ ...form, port: event.target.value })} />
          </Field>
          <Field label="Remote domain">
            <Input
              value={form.remote_domain}
              onChange={(event) => setForm({ ...form, remote_domain: event.target.value })}
              placeholder="example.com"
            />
          </Field>
        </div>
        <div className="flex items-center gap-3">
          <Button onClick={() => save.mutate()} disabled={save.isPending}>
            Save
          </Button>
          {current.restart_required ? (
            <span className="text-xs text-amber-300">Restart Fenox to apply the new address.</span>
          ) : null}
        </div>
        <ErrorText>{(save.error as Error | null)?.message}</ErrorText>
        <div className="text-xs text-[var(--color-muted)]">
          Reachable at: {current.urls.join(", ")}
        </div>
      </Card>

      <Card className="space-y-4 p-5">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-white">Tools</h2>
          <Button variant="ghost" onClick={() => queryClient.invalidateQueries({ queryKey: ["tools"] })}>
            Re-detect
          </Button>
        </div>
        {tools.isLoading ? (
          <Spinner label="Detecting tools" />
        ) : tools.data ? (
          <div className="space-y-2 text-sm">
            <ToolLine label="adb (client)" value={tools.data.adb.client} />
            <ToolLine label="adb (server)" value={tools.data.adb.server} />
            <ToolLine label="Flutter" value={tools.data.flutter.path} />
            <ToolLine
              label="scrcpy"
              value={tools.data.scrcpy.binary ? `${tools.data.scrcpy.binary}${tools.data.scrcpy.version ? ` (${tools.data.scrcpy.version})` : ""}` : null}
            />
            <ToolLine label="scrcpy server" value={tools.data.scrcpy.server} />
          </div>
        ) : null}
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <Field label="Flutter path override">
            <Input
              value={form.flutter_path}
              onChange={(event) => setForm({ ...form, flutter_path: event.target.value })}
              placeholder={tools.data?.flutter.path ?? "/home/you/flutter"}
            />
          </Field>
          <Field label="adb path override">
            <Input
              value={form.adb_path}
              onChange={(event) => setForm({ ...form, adb_path: event.target.value })}
              placeholder={tools.data?.adb.client ?? "/usr/bin/adb"}
            />
          </Field>
        </div>
        <p className="text-xs text-[var(--color-muted)]">
          Leave blank to detect automatically. A Flutter path may be the SDK directory or the binary itself.
        </p>
        <Button onClick={() => save.mutate()} disabled={save.isPending}>
          Save tool paths
        </Button>
        <ErrorText>{(save.error as Error | null)?.message}</ErrorText>
      </Card>

      <Card className="space-y-3 p-5">
        <h2 className="text-sm font-semibold text-white">Access token</h2>
        <p className="text-xs text-[var(--color-muted)]">
          Used by scripts and the CLI, as <code>Authorization: Bearer …</code>. The owner session cookie is separate.
        </p>
        <pre className="overflow-auto rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] p-3 text-xs text-[var(--color-muted)]">
          {token ?? "(none)"}
        </pre>
        <Button variant="secondary" onClick={() => rotate.mutate()} disabled={rotate.isPending}>
          Rotate token
        </Button>
      </Card>
    </div>
  );
}

function ToolLine({ label, value }: { label: string; value: string | null }) {
  return (
    <div className="flex justify-between border-b border-[var(--color-border)] py-1.5 text-sm last:border-0">
      <span className="text-[var(--color-muted)]">{label}</span>
      <span className={`truncate pl-4 text-right ${value ? "text-white" : "text-amber-300"}`}>{value ?? "not found"}</span>
    </div>
  );
}
