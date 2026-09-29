import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ChevronLeft,
  Download,
  Files as FilesIcon,
  FolderCog,
  Hammer,
  Info,
  Play,
  ShieldCheck,
} from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import {
  artifactUrl,
  getProject,
  keys,
  listBuilds,
  listDevices,
  startBatchRun,
  startRun,
  updateProject,
} from "@/api/queries";
import type { Project } from "@/api/types";
import { PathField } from "@/components/FolderPicker";
import { BuildLauncher, BuildStatus } from "@/components/builds";
import { Tabs } from "@/components/Tabs";
import { Badge, Button, Card, ErrorText, Field, Input, Modal, Select, SkeletonRows } from "@/components/ui";
import { rememberProject } from "@/hooks/useRecentProjects";
import { timeAgo } from "@/lib/format";
import { BuildsPanel } from "./project/BuildsPanel";
import { ProjectFilesPanel } from "./project/ProjectFilesPanel";
import { QualityPanel } from "./project/QualityPanel";

export function ProjectDetailPage() {
  const { name = "" } = useParams();
  const projectId = decodeURIComponent(name);
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const project = useQuery({ queryKey: keys.project(projectId), queryFn: () => getProject(projectId) });
  const devices = useQuery({ queryKey: keys.devices, queryFn: listDevices });
  const builds = useQuery({ queryKey: keys.builds, queryFn: () => listBuilds(projectId) });

  const online = (devices.data?.devices ?? []).filter((device) => device.online && !device.disabled);
  const [device, setDevice] = useState("");
  const [mode, setMode] = useState<"local" | "remote">("local");
  const [editOpen, setEditOpen] = useState(false);

  useEffect(() => {
    if (!device && online.length > 0) setDevice(online[0].id);
  }, [device, online]);

  // Opening a project is what "recent" means, so it is recorded here rather
  // than inferred from a build or a run.
  useEffect(() => {
    if (project.data) rememberProject(projectId);
  }, [project.data, projectId]);

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
    mutationFn: (patch: Partial<Project> & { backend_path?: string }) => updateProject(projectId, patch),
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
    return (
      <Card className="p-4">
        <SkeletonRows rows={4} />
      </Card>
    );
  }
  if (project.error || !project.data) {
    return <ErrorText>{(project.error as Error | null)?.message ?? "Project not found."}</ErrorText>;
  }

  const entry = project.data.project;
  const projectBuilds = builds.data?.builds ?? [];
  const running = projectBuilds.filter((build) => build.status === "running").length;
  const last = projectBuilds[0];
  const lastArtifact = projectBuilds.find((build) => build.status === "succeeded" && build.artifact_name);

  return (
    <div className="space-y-4">
      <div>
        <Link
          to="/projects"
          className="inline-flex items-center gap-1 text-xs text-[var(--color-muted)] transition-colors hover:text-[var(--color-text)]"
        >
          <ChevronLeft size={13} />
          Projects
        </Link>
        <div className="mt-1.5 flex flex-wrap items-center gap-2.5">
          <h1 className="text-lg font-semibold tracking-tight">{projectId}</h1>
          {entry.package ? <Badge tone="accent">{entry.package}</Badge> : null}
          {running ? <Badge tone="accent">{running} building</Badge> : null}
        </div>
        <p className="mt-0.5 truncate font-mono text-xs text-[var(--color-subtle)]">{entry.path}</p>
      </div>

      {/* The actions belong here, not only inside a tab: building is what a
          project page is for, and hunting for it behind a tab is a tax on the
          most common thing anyone does. */}
      <div className="flex flex-wrap items-center gap-2">
        <BuildLauncher project={projectId} kinds={builds.data?.kinds ?? []} busy={running > 0} compact />
        <span className="mx-1 hidden h-5 w-px bg-[var(--color-border)] sm:block" />
        <Button
          size="sm"
          variant="secondary"
          disabled={!device || start.isPending}
          onClick={() => start.mutate()}
          title={online.length ? "Run on the selected device" : "No device is online"}
        >
          <Play size={13} />
          Run
        </Button>
        {lastArtifact ? (
          <a
            href={artifactUrl(lastArtifact.id)}
            download
            className="inline-flex h-7 items-center gap-1.5 rounded-[var(--radius-md)] border border-[var(--color-border)] px-2.5 text-xs font-medium transition-colors hover:border-[var(--color-border-strong)]"
          >
            <Download size={12} />
            {lastArtifact.artifact_name}
          </a>
        ) : null}
      </div>

      <Tabs
        tabs={[
          {
            id: "overview",
            label: "Overview",
            icon: <Info size={15} />,
            render: () => <OverviewPanel entry={entry} last={last} buildCount={projectBuilds.length} />,
          },
          {
            id: "builds",
            label: "Builds",
            icon: <Hammer size={15} />,
            badge: running ? <Badge tone="accent">{running}</Badge> : undefined,
            render: () => <BuildsPanel project={projectId} />,
          },
          {
            id: "quality",
            label: "Quality",
            icon: <ShieldCheck size={15} />,
            render: () => <QualityPanel project={projectId} />,
          },
          {
            id: "files",
            label: "Files",
            icon: <FilesIcon size={15} />,
            render: () => <ProjectFilesPanel project={projectId} />,
          },
          {
            id: "run",
            label: "Run",
            icon: <Play size={15} />,
            render: () => (
              <Card className="p-4">
                <h2 className="text-sm font-semibold">Run on a device</h2>
                <p className="mt-0.5 mb-3 text-xs text-[var(--color-muted)]">
                  Builds, installs and attaches to the Dart VM so reload and restart work.
                </p>
                <div className="flex flex-wrap items-end gap-3">
                  <Field label="Device">
                    <Select value={device} onChange={(event) => setDevice(event.target.value)} disabled={!online.length}>
                      {online.length === 0 ? <option value="">No devices online</option> : null}
                      {online.map((item) => (
                        <option key={item.id} value={item.id}>
                          {item.id}
                        </option>
                      ))}
                    </Select>
                  </Field>
                  <Field label="Backend">
                    <Select value={mode} onChange={(event) => setMode(event.target.value as "local" | "remote")}>
                      <option value="local">Local</option>
                      <option value="remote">Production</option>
                    </Select>
                  </Field>
                  <Button disabled={!device || start.isPending} onClick={() => start.mutate()}>
                    <Play size={14} />
                    {start.isPending ? "Starting…" : "Run"}
                  </Button>
                  <Button
                    variant="secondary"
                    disabled={online.length === 0 || batch.isPending}
                    onClick={() => batch.mutate()}
                  >
                    Run on all ({online.length})
                  </Button>
                </div>
                <ErrorText>
                  {(start.error as Error | null)?.message ?? (batch.error as Error | null)?.message}
                </ErrorText>
                {online.length === 0 ? (
                  <p className="mt-3 text-xs text-[var(--color-subtle)]">
                    No device is online. Plug one in, or connect over wireless debugging.
                  </p>
                ) : null}
              </Card>
            ),
          },
          {
            id: "settings",
            label: "Settings",
            icon: <FolderCog size={15} />,
            render: () => (
              <div className="space-y-4">
                <Card className="p-4">
                  <h2 className="mb-1 text-sm font-semibold">Backend URLs</h2>
                  <p className="mb-3 text-xs text-[var(--color-muted)]">
                    Injected at build and run time. A release build pointing at localhost ships an app that talks to
                    nothing.
                  </p>
                  <BackendUrls
                    local={entry.api_local}
                    production={entry.api_remote ?? ""}
                    saving={urls.isPending}
                    error={(urls.error as Error | null)?.message}
                    onSave={(patch) => urls.mutate(patch)}
                  />
                </Card>
                <Card className="p-4">
                  <div className="mb-3 flex items-center justify-between">
                    <h2 className="text-sm font-semibold">Project</h2>
                    <Button variant="secondary" size="sm" onClick={() => setEditOpen(true)}>
                      Edit project
                    </Button>
                  </div>
                  <dl className="grid grid-cols-1 gap-x-8 gap-y-1.5 text-sm sm:grid-cols-2">
                    <ConfigRow label="Package" value={entry.package ?? "—"} />
                    <ConfigRow label="Port" value={entry.port} />
                    <ConfigRow label="Local socket" value={entry.socket_local ?? "—"} />
                    <ConfigRow label="Remote socket" value={entry.socket_remote ?? "—"} />
                    <ConfigRow
                      label="Backend"
                      value={entry.backend ? `${entry.backend.cmd} (${entry.backend.path})` : "—"}
                    />
                    <ConfigRow label="Extra ports" value={entry.additional_ports?.join(", ") || "—"} />
                  </dl>
                </Card>
              </div>
            ),
          },
        ]}
      />

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

/** A compact summary: what it is, and what happened last. */
function OverviewPanel({
  entry,
  last,
  buildCount,
}: {
  entry: Project;
  last?: { status: "running" | "succeeded" | "failed" | "cancelled"; artifact_name: string; started_at: string };
  buildCount: number;
}) {
  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
      <Card className="p-4 lg:col-span-2">
        <h2 className="mb-3 text-sm font-semibold">Project</h2>
        <dl className="grid grid-cols-1 gap-x-8 gap-y-1.5 text-sm sm:grid-cols-2">
          <ConfigRow label="Package" value={entry.package ?? "—"} />
          <ConfigRow label="Port" value={entry.port} />
          <ConfigRow label="Local API" value={entry.api_local || "—"} />
          <ConfigRow label="Production API" value={entry.api_remote ?? "—"} />
        </dl>
        <p className="mt-3 font-mono text-[11px] break-all text-[var(--color-subtle)]">{entry.path}</p>
      </Card>

      <div className="space-y-4">
        <Card className="p-4">
          <h2 className="mb-2 text-sm font-semibold">Last build</h2>
          {last ? (
            <div className="space-y-2">
              <div className="flex items-center justify-between gap-2">
                <span className="truncate text-sm">{last.artifact_name || "—"}</span>
                <BuildStatus status={last.status} />
              </div>
              <p className="text-xs text-[var(--color-subtle)]">{timeAgo(last.started_at)}</p>
            </div>
          ) : (
            <p className="text-xs text-[var(--color-muted)]">Nothing built yet.</p>
          )}
        </Card>

        <Card className="p-4">
          <h2 className="mb-2 text-sm font-semibold">At a glance</h2>
          <div className="space-y-1.5 text-sm">
            <ConfigRow label="Builds" value={String(buildCount)} />
            <ConfigRow label="Extra ports" value={entry.additional_ports?.join(", ") || "—"} />
          </div>
        </Card>
      </div>
    </div>
  );
}

/**
 * The two backend URLs, editable in place.
 *
 * These change most often and a wrong value breaks silently — the app runs and
 * talks to the wrong server — so they get their own panel rather than living
 * behind a dialog.
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

  useEffect(() => {
    setValues({ api_local: local, api_remote: production });
  }, [local, production]);

  const dirty = values.api_local !== local || values.api_remote !== production;

  return (
    <form
      className="space-y-3"
      onSubmit={(event) => {
        event.preventDefault();
        onSave({ api_local: values.api_local.trim(), api_remote: values.api_remote.trim() });
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
        <Button type="submit" size="sm" disabled={saving || !dirty}>
          {saving ? "Saving…" : "Save URLs"}
        </Button>
        {dirty ? <span className="text-xs text-[var(--color-subtle)]">Unsaved changes</span> : null}
      </div>
      <ErrorText>{error}</ErrorText>
    </form>
  );
}

function ConfigRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-4 border-b border-[var(--color-border)] py-1.5 last:border-0">
      <dt className="shrink-0 text-[var(--color-muted)]">{label}</dt>
      <dd className="truncate text-right text-[var(--color-text)]">{value}</dd>
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
    <Modal
      title="Edit project"
      description="How this project is found, run and built."
      onClose={onClose}
      size="lg"
      footer={
        <>
          <Button type="button" variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" form="edit-project" disabled={saving}>
            {saving ? "Saving…" : "Save"}
          </Button>
        </>
      }
    >
      <form
        id="edit-project"
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
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <Field label="Port">
            <Input value={form.port} onChange={(event) => setForm({ ...form, port: event.target.value })} />
          </Field>
          <PathField
            label="Backend folder"
            value={form.backend_path}
            onChange={(backend_path) => setForm({ ...form, backend_path })}
            placeholder="Detected from the project"
            browseTitle="Choose the backend folder"
          />
        </div>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <Field label="Local socket URL">
            <Input
              value={form.socket_local}
              onChange={(event) => setForm({ ...form, socket_local: event.target.value })}
            />
          </Field>
          <Field label="Remote socket URL">
            <Input
              value={form.socket_remote}
              onChange={(event) => setForm({ ...form, socket_remote: event.target.value })}
            />
          </Field>
        </div>
        <ErrorText>{error}</ErrorText>
      </form>
    </Modal>
  );
}
