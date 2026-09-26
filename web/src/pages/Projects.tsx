import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Folder } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";

import { createProject, deleteProject, keys, listProjects, scanProjects } from "@/api/queries";
import { FolderPicker } from "@/components/FolderPicker";
import { Badge, Button, Card, ErrorText, Field, Input, Modal, Spinner } from "@/components/ui";

export function ProjectsPage() {
  const queryClient = useQueryClient();
  const { data, isLoading, error } = useQuery({ queryKey: keys.projects, queryFn: listProjects });

  const [wizardOpen, setWizardOpen] = useState(false);
  const [picking, setPicking] = useState(false);
  const [form, setForm] = useState({ name: "", path: "", api_local: "" });
  const [removeName, setRemoveName] = useState<string | null>(null);
  const [scanning, setScanning] = useState(false);

  const refresh = () => queryClient.invalidateQueries({ queryKey: keys.projects });
  const create = useMutation({
    mutationFn: () =>
      createProject({
        name: form.name.trim() || undefined,
        path: form.path.trim(),
        api_local: form.api_local.trim() || undefined,
      }),
    onSuccess: () => {
      setWizardOpen(false);
      setPicking(false);
      setForm({ name: "", path: "", api_local: "" });
      refresh();
    },
  });
  const scan = useMutation({ mutationFn: (path?: string) => scanProjects(path), onSuccess: refresh });
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
          <Button variant="secondary" onClick={() => setScanning(true)} disabled={scan.isPending}>
            {scan.isPending ? "Scanning…" : "Scan a folder…"}
          </Button>
          <Button onClick={() => setWizardOpen(true)}>Add project</Button>
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

      {wizardOpen ? (
        <AddProjectWizard
          form={form}
          setForm={setForm}
          onBrowse={() => setPicking(true)}
          saving={create.isPending}
          error={(create.error as Error | null)?.message}
          onClose={() => setWizardOpen(false)}
          onSubmit={() => create.mutate()}
        />
      ) : null}

      {/* Kept a sibling of the wizard, not nested inside it, so the picker is
          always the topmost dialog. */}
      {picking ? (
        <FolderPicker
          title="Choose the project directory"
          initialPath={form.path}
          onSelect={(path, suggested) => {
            setForm((current) => ({
              ...current,
              path,
              // Only fill the name if they have not typed one already.
              name: current.name.trim() || suggested || "",
            }));
            setPicking(false);
          }}
          onClose={() => setPicking(false)}
        />
      ) : null}

      {scanning ? (
        <FolderPicker
          title="Scan a folder for Flutter projects"
          onSelect={(path) => {
            setScanning(false);
            scan.mutate(path);
          }}
          onClose={() => setScanning(false)}
        />
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

/** The three answers a new project needs, in the order they are asked for. */
interface AddForm {
  name: string;
  path: string;
  api_local: string;
}

const STEPS = ["Project name", "Project directory", "Backend link"] as const;

/**
 * Add-project wizard: name, then directory, then the backend link. Nothing
 * else, and nothing that can be worked out later. The directory step opens a
 * folder browser rather than asking for a path, and the port, remote URL and
 * package name are detected from the project instead of being asked for.
 */
function AddProjectWizard({
  form,
  setForm,
  onBrowse,
  saving,
  error,
  onClose,
  onSubmit,
}: {
  form: AddForm;
  setForm: React.Dispatch<React.SetStateAction<AddForm>>;
  onBrowse: () => void;
  saving: boolean;
  error?: string;
  onClose: () => void;
  onSubmit: () => void;
}) {
  const [step, setStep] = useState(0);
  const canContinue = step === 0 ? form.name.trim().length > 0 : step === 1 ? form.path.trim().length > 0 : true;
  const isLast = step === STEPS.length - 1;

  return (
    <Modal title="Add project" onClose={onClose}>
      <form
        className="space-y-4"
        onSubmit={(event) => {
          event.preventDefault();
          if (isLast) {
            onSubmit();
          } else if (canContinue) {
            setStep(step + 1);
          }
        }}
      >
        <ol className="flex items-center gap-2 text-xs">
          {STEPS.map((label, index) => (
            <li key={label} className="flex items-center gap-2">
              <span
                className={`flex h-5 w-5 items-center justify-center rounded-full border ${
                  index === step
                    ? "border-[var(--color-accent)] text-[var(--color-accent)]"
                    : index < step
                      ? "border-emerald-500/60 text-emerald-400"
                      : "border-[var(--color-border)] text-[var(--color-muted)]"
                }`}
              >
                {index + 1}
              </span>
              <span className={index === step ? "text-white" : "text-[var(--color-muted)]"}>{label}</span>
              {index < STEPS.length - 1 ? <span className="text-[var(--color-border)]">—</span> : null}
            </li>
          ))}
        </ol>

        {step === 0 ? (
          <Field label="Project name">
            <Input
              autoFocus
              value={form.name}
              onChange={(event) => setForm({ ...form, name: event.target.value })}
              placeholder="paylesa"
            />
          </Field>
        ) : null}

        {step === 1 ? (
          <div className="space-y-1.5">
            <span className="text-xs font-medium tracking-wide text-[var(--color-muted)] uppercase">Project directory</span>
            <div className="flex gap-2">
              <Input
                value={form.path}
                onChange={(event) => setForm({ ...form, path: event.target.value })}
                placeholder="~/Projects/paylesa/frontend/mobile-app"
                aria-label="Project directory"
              />
              <Button type="button" variant="secondary" className="shrink-0" onClick={onBrowse}>
                <Folder size={14} />
                Browse
              </Button>
            </div>
            <p className="text-xs text-[var(--color-muted)]">
              The folder holding pubspec.yaml. Picking it can fill in the name for you.
            </p>
          </div>
        ) : null}

        {step === 2 ? (
          <Field label="Backend link">
            <Input
              autoFocus
              value={form.api_local}
              onChange={(event) => setForm({ ...form, api_local: event.target.value })}
              placeholder="http://localhost:1991/api"
            />
          </Field>
        ) : null}

        <p className="text-xs text-[var(--color-muted)]">
          {step === 2
            ? "Used for local runs. Leave it blank to detect it, and change it any time from the project page."
            : "Step " + (step + 1) + " of " + STEPS.length}
        </p>

        <ErrorText>{error}</ErrorText>

        <div className="flex justify-between gap-2">
          <Button type="button" variant="ghost" onClick={step === 0 ? onClose : () => setStep(step - 1)}>
            {step === 0 ? "Cancel" : "Back"}
          </Button>
          <Button type="submit" disabled={saving || !canContinue}>
            {isLast ? (saving ? "Adding…" : "Add project") : "Next"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}
