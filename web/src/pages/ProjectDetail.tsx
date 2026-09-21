import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { getProject, keys, listDevices, startBatchRun, startRun, updateProject } from "@/api/queries";
import type { Project } from "@/api/types";
import { Badge, Button, Card, ErrorText, Field, Input, Modal, Spinner } from "@/components/ui";

export function ProjectDetailPage() {
  const { name = "" } = useParams();
  const projectId = decodeURIComponent(name);
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const project = useQuery({ queryKey: keys.project(projectId), queryFn: () => getProject(projectId) });
  const devices = useQuery({ queryKey: keys.devices, queryFn: listDevices });

  const online = (devices.data?.devices ?? []).filter((device) => device.online && !device.disabled);
  const [device, setDevice] = useState("");
  const [mode, setMode] = useState<"local" | "remote">("local");
  const [editOpen, setEditOpen] = useState(false);

  useEffect(() => {
    if (!device && online.length > 0) {
      setDevice(online[0].id);
    }
  }, [device, online]);

  const start = useMutation({
    mutationFn: () => startRun(projectId, device, mode),
    onSuccess: (run) => {
      queryClient.invalidateQueries({ queryKey: keys.runs });
      navigate(`/runs/${run.id}`);
    },
  });
  const batch = useMutation({
    mutationFn: () => startBatchRun(projectId, mode),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: keys.runs });
      navigate("/runs");
    },
  });
  const save = useMutation({
    mutationFn: (patch: Partial<Project>) => updateProject(projectId, patch),
    onSuccess: () => {
      setEditOpen(false);
      queryClient.invalidateQueries({ queryKey: keys.project(projectId) });
    },
  });

  if (project.isLoading) {
    return <Spinner label="Loading project" />;
  }
  if (project.error || !project.data) {
    return <p className="text-sm text-red-400">{(project.error as Error | null)?.message ?? "Project not found."}</p>;
  }

  const entry = project.data.project;

  return (
    <div className="space-y-6">
      <div>
        <Link to="/projects" className="text-xs text-[var(--color-muted)] hover:text-white">
          &larr; Projects
        </Link>
        <div className="mt-2 flex items-center gap-3">
          <h1 className="text-lg font-semibold text-white">{projectId}</h1>
          {entry.package ? <Badge tone="accent">{entry.package}</Badge> : null}
        </div>
        <p className="mt-1 text-sm text-[var(--color-muted)]">{entry.path}</p>
      </div>

      <Card className="p-5">
        <h2 className="mb-4 text-sm font-semibold text-white">Run</h2>
        <div className="flex flex-wrap items-end gap-3">
          <Field label="Device">
            <select
              className="rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-2 text-sm text-white"
              value={device}
              onChange={(event) => setDevice(event.target.value)}
            >
              {online.length === 0 ? <option value="">No devices online</option> : null}
              {online.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.id}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Mode">
            <select
              className="rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-2 text-sm text-white"
              value={mode}
              onChange={(event) => setMode(event.target.value as "local" | "remote")}
            >
              <option value="local">Local</option>
              <option value="remote">Remote</option>
            </select>
          </Field>
          <Button disabled={!device || start.isPending} onClick={() => start.mutate()}>
            {start.isPending ? "Starting…" : "Run"}
          </Button>
          <Button variant="secondary" disabled={online.length === 0 || batch.isPending} onClick={() => batch.mutate()}>
            {batch.isPending ? "Starting…" : `Run on all (${online.length})`}
          </Button>
        </div>
        <ErrorText>{(start.error as Error | null)?.message ?? (batch.error as Error | null)?.message}</ErrorText>
      </Card>

      <Card className="p-5">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-white">Configuration</h2>
          <Button variant="ghost" onClick={() => setEditOpen(true)}>
            Edit
          </Button>
        </div>
        <dl className="grid grid-cols-1 gap-x-8 gap-y-2 text-sm sm:grid-cols-2">
          <ConfigRow label="Port" value={entry.port} />
          <ConfigRow label="Package" value={entry.package ?? "—"} />
          <ConfigRow label="Local API" value={entry.api_local} />
          <ConfigRow label="Remote API" value={entry.api_remote ?? "—"} />
          <ConfigRow label="Local socket" value={entry.socket_local ?? "—"} />
          <ConfigRow label="Remote socket" value={entry.socket_remote ?? "—"} />
          <ConfigRow label="Backend" value={entry.backend ? `${entry.backend.cmd} (${entry.backend.path})` : "—"} />
          <ConfigRow label="Extra ports" value={entry.additional_ports?.join(", ") || "—"} />
        </dl>
      </Card>

      {editOpen ? (
        <EditProjectModal
          initial={entry}
          saving={save.isPending}
          error={(save.error as Error | null)?.message}
          onClose={() => setEditOpen(false)}
          onSave={(patch) => save.mutate(patch)}
        />
      ) : null}
    </div>
  );
}

function ConfigRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between border-b border-[var(--color-border)] py-1.5">
      <dt className="text-[var(--color-muted)]">{label}</dt>
      <dd className="truncate pl-4 text-right text-white">{value}</dd>
    </div>
  );
}

function EditProjectModal({
  initial,
  saving,
  error,
  onClose,
  onSave,
}: {
  initial: { port: string; api_local: string; api_remote?: string; socket_local?: string; socket_remote?: string };
  saving: boolean;
  error?: string;
  onClose: () => void;
  onSave: (patch: Partial<Project>) => void;
}) {
  const [form, setForm] = useState({
    port: initial.port,
    api_local: initial.api_local,
    api_remote: initial.api_remote ?? "",
    socket_local: initial.socket_local ?? "",
    socket_remote: initial.socket_remote ?? "",
  });

  return (
    <Modal title="Edit project" onClose={onClose}>
      <form
        className="space-y-4"
        onSubmit={(event) => {
          event.preventDefault();
          onSave({
            port: form.port,
            api_local: form.api_local,
            api_remote: form.api_remote,
            socket_local: form.socket_local,
            socket_remote: form.socket_remote,
          });
        }}
      >
        <Field label="Port">
          <Input value={form.port} onChange={(event) => setForm({ ...form, port: event.target.value })} />
        </Field>
        <Field label="Local API URL">
          <Input value={form.api_local} onChange={(event) => setForm({ ...form, api_local: event.target.value })} />
        </Field>
        <Field label="Remote API URL">
          <Input value={form.api_remote} onChange={(event) => setForm({ ...form, api_remote: event.target.value })} />
        </Field>
        <Field label="Local socket URL">
          <Input value={form.socket_local} onChange={(event) => setForm({ ...form, socket_local: event.target.value })} />
        </Field>
        <Field label="Remote socket URL">
          <Input value={form.socket_remote} onChange={(event) => setForm({ ...form, socket_remote: event.target.value })} />
        </Field>
        <ErrorText>{error}</ErrorText>
        <div className="flex justify-end gap-2">
          <Button type="button" variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" disabled={saving}>
            Save
          </Button>
        </div>
      </form>
    </Modal>
  );
}
