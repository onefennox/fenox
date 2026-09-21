import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";

import { createProject, deleteProject, keys, listProjects, scanProjects } from "@/api/queries";
import { Badge, Button, Card, ErrorText, Field, Input, Modal, Spinner } from "@/components/ui";

export function ProjectsPage() {
  const queryClient = useQueryClient();
  const { data, isLoading, error } = useQuery({ queryKey: keys.projects, queryFn: listProjects });

  const [addOpen, setAddOpen] = useState(false);
  const [form, setForm] = useState({ name: "", path: "" });
  const [removeName, setRemoveName] = useState<string | null>(null);

  const refresh = () => queryClient.invalidateQueries({ queryKey: keys.projects });
  const create = useMutation({
    mutationFn: () => createProject({ name: form.name.trim(), path: form.path.trim() }),
    onSuccess: () => {
      setAddOpen(false);
      setForm({ name: "", path: "" });
      refresh();
    },
  });
  const scan = useMutation({ mutationFn: scanProjects, onSuccess: refresh });
  const remove = useMutation({
    mutationFn: deleteProject,
    onSuccess: () => {
      setRemoveName(null);
      refresh();
    },
  });

  if (isLoading) {
    return <Spinner label="Loading projects" />;
  }
  if (error) {
    return <p className="text-sm text-red-400">{(error as Error).message}</p>;
  }

  const projects = Object.entries(data?.projects ?? {});

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold text-white">Projects</h1>
          <p className="mt-1 text-sm text-[var(--color-muted)]">
            Register Flutter projects, then run them on any connected device.
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="secondary" onClick={() => scan.mutate()} disabled={scan.isPending}>
            {scan.isPending ? "Scanning…" : "Scan directory"}
          </Button>
          <Button onClick={() => setAddOpen(true)}>Add project</Button>
        </div>
      </div>

      {scan.data && scan.data.added.length > 0 ? (
        <Card className="border-emerald-500/30 p-3 text-sm text-emerald-300">
          Registered {scan.data.added.join(", ")}.
        </Card>
      ) : null}

      {projects.length === 0 ? (
        <Card className="p-8 text-center text-sm text-[var(--color-muted)]">
          No projects yet. Add one by path, or scan your projects directory.
        </Card>
      ) : (
        <Card className="divide-y divide-[var(--color-border)]">
          {projects.map(([name, project]) => (
            <div key={name} className="flex items-center gap-4 p-4">
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <Link to={`/projects/${encodeURIComponent(name)}`} className="font-medium text-white hover:underline">
                    {name}
                  </Link>
                  {project.package ? <Badge tone="accent">{project.package}</Badge> : null}
                </div>
                <div className="truncate text-xs text-[var(--color-muted)]">
                  {project.path} · port {project.port}
                </div>
              </div>
              <Button variant="ghost" onClick={() => setRemoveName(name)}>
                Remove
              </Button>
            </div>
          ))}
        </Card>
      )}

      {addOpen ? (
        <Modal title="Add project" onClose={() => setAddOpen(false)}>
          <form
            className="space-y-4"
            onSubmit={(event) => {
              event.preventDefault();
              create.mutate();
            }}
          >
            <Field label="Name">
              <Input value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} placeholder="demo" />
            </Field>
            <Field label="Project path">
              <Input
                value={form.path}
                onChange={(event) => setForm({ ...form, path: event.target.value })}
                placeholder="~/Projects/demo"
              />
            </Field>
            <p className="text-xs text-[var(--color-muted)]">
              The backend port, API URLs, and Android package are detected from the project.
            </p>
            <ErrorText>{(create.error as Error | null)?.message}</ErrorText>
            <div className="flex justify-end gap-2">
              <Button type="button" variant="ghost" onClick={() => setAddOpen(false)}>
                Cancel
              </Button>
              <Button type="submit" disabled={create.isPending || !form.name || !form.path}>
                Add
              </Button>
            </div>
          </form>
        </Modal>
      ) : null}

      {removeName ? (
        <Modal title="Remove project" onClose={() => setRemoveName(null)}>
          <p className="text-sm text-[var(--color-muted)]">
            Remove <span className="text-white">{removeName}</span> from Fenox? The project files are not touched.
          </p>
          <div className="mt-5 flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setRemoveName(null)}>
              Cancel
            </Button>
            <Button variant="danger" onClick={() => remove.mutate(removeName)} disabled={remove.isPending}>
              Remove
            </Button>
          </div>
        </Modal>
      ) : null}
    </div>
  );
}
