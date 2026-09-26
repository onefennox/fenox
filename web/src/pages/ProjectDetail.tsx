import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { getProject, keys, listDevices, startBatchRun, startRun, updateProject } from "@/api/queries";
import type { Project } from "@/api/types";
import { PathField } from "@/components/FolderPicker";
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
  const urls = useMutation({
    mutationFn: (patch: { api_local?: string; api_remote?: string }) => updateProject(projectId, patch),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: keys.project(projectId) }),
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
        <h2 className="mb-1 text-sm font-semibold text-white">Backend URLs</h2>
        <p className="mb-4 text-xs text-[var(--color-muted)]">
          Used by <span className="text-white">local</span> and{" "}
          <span className="text-white">production</span> runs respectively. Change them here rather than
          editing the project.
        </p>
        <BackendUrls
          local={entry.api_local}
          production={entry.api_remote ?? ""}
          saving={urls.isPending}
          error={(urls.error as Error | null)?.message}
          onSave={(patch) => urls.mutate(patch)}
        />
      </Card>

      <Card className="p-5">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-white">Configuration</h2>
          <Button variant="ghost" onClick={() => setEditOpen(true)}>
            Edit project
          </Button>
        </div>
        <dl className="grid grid-cols-1 gap-x-8 gap-y-2 text-sm sm:grid-cols-2">
          <ConfigRow label="Port" value={entry.port} />
          <ConfigRow label="Package" value={entry.package ?? "—"} />
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

/**
 * The two backend URLs, editable in place.
 *
 * These are the fields that change most often and that a wrong value breaks
 * silently — a run against the wrong backend just fails to load data. They get
 * their own panel on the page rather than living behind a dialog, so they are
 * somewhere to go when a run points at the wrong place.
 */
function BackendUrls({
  local,
  production,
  saving,
  error,
  onSave,
}: {
  local: string;
  production: string;
  saving: boolean;
  error?: string;
  onSave: (patch: { api_local?: string; api_remote?: string }) => void;
}) {
  const [values, setValues] = useState({ api_local: local, api_remote: production });

  // Follow the server when it changes elsewhere, without stomping on typing.
  useEffect(() => {
    setValues({ api_local: local, api_remote: production });
  }, [local, production]);

  const dirty = values.api_local !== local || values.api_remote !== production;

  return (
    <form
      className="space-y-3"
      onSubmit={(event) => {
        event.preventDefault();
        onSave({
          api_local: values.api_local.trim(),
          api_remote: values.api_remote.trim(),
        });
      }}
    >
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <Field label="Local backend URL">
          <Input
            value={values.api_local}
            onChange={(event) => setValues({ ...values, api_local: event.target.value })}
            placeholder="http://localhost:1991/api"
          />
        </Field>
        <Field label="Production backend URL">
          <Input
            value={values.api_remote}
            onChange={(event) => setValues({ ...values, api_remote: event.target.value })}
            placeholder="https://api.example.com"
          />
        </Field>
      </div>
      <div className="flex items-center gap-2">
        <Button type="submit" disabled={saving || !dirty}>
          {saving ? "Saving…" : "Save URLs"}
        </Button>
        {dirty ? <span className="text-xs text-[var(--color-muted)]">Unsaved changes</span> : null}
      </div>
      <ErrorText>{error}</ErrorText>
    </form>
  );
}

function ConfigRow({ label, value }: { label: string; value: string }) {  return (
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
  initial: {
    path: string;
    port: string;
    socket_local?: string;
    socket_remote?: string;
    backend?: { path: string; cmd: string };
  };
  saving: boolean;
  error?: string;
  onClose: () => void;
  onSave: (patch: Partial<Project> & { backend_path?: string }) => void;
}) {
  const [form, setForm] = useState({
    path: initial.path,
    port: initial.port,
    socket_local: initial.socket_local ?? "",
    socket_remote: initial.socket_remote ?? "",
    backend_path: initial.backend?.path ?? "",
  });

  return (
    <Modal title="Edit project" onClose={onClose} wide>
      <form
        className="space-y-4"
        onSubmit={(event) => {
          event.preventDefault();
          onSave({
            path: form.path,
            port: form.port,
            socket_local: form.socket_local,
            socket_remote: form.socket_remote,
            backend_path: form.backend_path,
          });
        }}
      >
        <PathField
          label="Project folder"
          value={form.path}
          onChange={(path) => setForm({ ...form, path })}
          browseTitle="Choose the Flutter project folder"
        />
        <Field label="Port">
          <Input value={form.port} onChange={(event) => setForm({ ...form, port: event.target.value })} />
        </Field>
        <Field label="Local socket URL">
          <Input value={form.socket_local} onChange={(event) => setForm({ ...form, socket_local: event.target.value })} />
        </Field>
        <Field label="Remote socket URL">
          <Input value={form.socket_remote} onChange={(event) => setForm({ ...form, socket_remote: event.target.value })} />
        </Field>
        <PathField
          label="Backend folder"
          value={form.backend_path}
          onChange={(backend_path) => setForm({ ...form, backend_path })}
          placeholder="Detected from the project"
          browseTitle="Choose the backend folder"
        />
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
