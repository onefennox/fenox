import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { getSettings, rotateToken, updateSettings } from "@/api/queries";
import { Button, Card, ErrorText, Field, Input, Spinner } from "@/components/ui";

export function SettingsPage() {
  const queryClient = useQueryClient();
  const settings = useQuery({ queryKey: ["settings"], queryFn: getSettings });
  const [form, setForm] = useState({ reach: "local", port: "8787", remote_domain: "" });
  const [token, setToken] = useState<string | null>(null);

  useEffect(() => {
    if (settings.data) {
      setForm({
        reach: settings.data.reach,
        port: String(settings.data.port),
        remote_domain: settings.data.remote_domain,
      });
      setToken(settings.data.token);
    }
  }, [settings.data]);

  const save = useMutation({
    mutationFn: () =>
      updateSettings({ reach: form.reach, port: Number(form.port), remote_domain: form.remote_domain }),
    onSuccess: (data) => {
      setToken(data.token);
      queryClient.invalidateQueries({ queryKey: ["settings"] });
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
