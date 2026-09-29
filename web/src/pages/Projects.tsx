import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ChevronDown,
  ChevronRight,
  Eye,
  EyeOff,
  Folder,
  FolderKanban,
  Hammer,
  MoreHorizontal,
  Pin,
  PinOff,
  Search,
  Settings2,
  Trash2,
  X,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import {
  createProject,
  deleteProject,
  keys,
  listBuilds,
  listProjects,
  scanProjects,
  startBuild,
  updateProject,
} from "@/api/queries";
import type { Build, Project } from "@/api/types";
import { FolderPicker } from "@/components/FolderPicker";
import { BuildStatus } from "@/components/builds";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorText,
  Field,
  Input,
  Modal,
  SkeletonRows,
  Tooltip,
} from "@/components/ui";
import { forgetProject, rememberProject, useRecentProjects } from "@/hooks/useRecentProjects";
import { cn, timeAgo } from "@/lib/format";
import { useUi } from "@/lib/ui-state";
import { toast } from "@/lib/toast";

/** Build actions for one project, behind a button so the row stays a row. */
function BuildMenu({ project, disabled }: { project: string; disabled?: boolean }) {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (event: MouseEvent) => {
      if (ref.current && !ref.current.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);

  const build = useMutation({
    mutationFn: (kind: string) => startBuild(project, kind),
    onSuccess: (started: Build) => {
      toast.info(`Building ${started.label}`, project);
      queryClient.invalidateQueries({ queryKey: keys.builds });
    },
    onError: (error: Error) => toast.error("Could not start the build", error.message),
  });

  const item = (kind: string, label: string, hint: string) => (
    <button
      key={kind}
      onClick={() => {
        setOpen(false);
        build.mutate(kind);
      }}
      className="flex w-full cursor-pointer items-start gap-2 px-3 py-2 text-left transition-colors hover:bg-[var(--color-panel-hover)]"
    >
      <Hammer size={13} className="mt-0.5 shrink-0 text-[var(--color-accent)]" />
      <span className="min-w-0">
        <span className="block text-sm text-[var(--color-text)]">{label}</span>
        <span className="block text-[10px] text-[var(--color-subtle)]">{hint}</span>
      </span>
    </button>
  );

  return (
    <div className="relative" ref={ref} onClick={(event) => event.preventDefault()}>
      <Button
        size="sm"
        variant="secondary"
        disabled={disabled || build.isPending}
        onClick={() => setOpen((current) => !current)}
      >
        <Hammer size={13} />
        {build.isPending ? "Starting…" : "Build"}
      </Button>
      {open ? (
        <div className="animate-in absolute right-0 z-40 mt-1 w-56 overflow-hidden rounded-[var(--radius-md)] border border-[var(--color-border-strong)] bg-[var(--color-panel)] py-1 shadow-xl">
          {item("apk-debug", "Debug APK", "Fastest, for a phone in your hand")}
          {item("apk-release", "Release APK", "Installable by anyone")}
          {item("aab-release", "Release AAB", "The format Google Play accepts")}
        </div>
      ) : null}
    </div>
  );
}

function ProjectRow({
  name,
  project,
  last,
  onRemove,
}: {
  name: string;
  project: Project;
  last?: Build;
  onRemove: () => void;
}) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [menu, setMenu] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!menu) return;
    const onDown = (event: MouseEvent) => {
      if (ref.current && !ref.current.contains(event.target as Node)) setMenu(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [menu]);

  const pin = useMutation({
    mutationFn: (next: boolean) => updateProject(name, { pinned: next }),
    onSuccess: (_result, next) => {
      toast.success(next ? `${name} pinned` : `${name} unpinned`);
      queryClient.invalidateQueries({ queryKey: keys.projects });
    },
    onError: (error: Error) => toast.error("Could not change the pin", error.message),
  });

  const open = () => {
    rememberProject(name);
    navigate(`/projects/${encodeURIComponent(name)}`);
  };

  return (
    <div className="group flex flex-wrap items-center gap-x-3 gap-y-2 px-3 py-2.5 transition-colors hover:bg-[var(--color-panel-hover)]">
      <button
        onClick={() => pin.mutate(!project.pinned)}
        disabled={pin.isPending}
        title={project.pinned ? "Unpin" : "Pin to the top"}
        className={cn(
          "shrink-0 cursor-pointer rounded-[var(--radius-sm)] p-1 transition-colors",
          project.pinned
            ? "text-[var(--color-accent)]"
            : "text-[var(--color-subtle)] opacity-0 group-hover:opacity-100 hover:text-[var(--color-text)]",
        )}
      >
        {project.pinned ? <Pin size={13} /> : <PinOff size={13} />}
      </button>

      <button onClick={open} className="min-w-0 flex-1 cursor-pointer text-left">
        <div className="flex items-center gap-2">
          <span className="truncate text-sm font-medium">{name}</span>
          {project.package ? <Badge tone="accent">{project.package}</Badge> : null}
        </div>
        <p className="truncate text-[11px] text-[var(--color-subtle)]">{project.path}</p>
      </button>

      <div className="flex shrink-0 items-center gap-2">
        {last ? (
          <span
            className="hidden items-center gap-1.5 sm:flex"
            title={`${last.artifact_name} · ${timeAgo(last.started_at)}`}
          >
            <BuildStatus status={last.status} />
            <span className="tnum text-[11px] text-[var(--color-subtle)]">{timeAgo(last.started_at)}</span>
          </span>
        ) : (
          <span className="hidden text-[11px] text-[var(--color-subtle)] sm:inline">never built</span>
        )}

        <BuildMenu project={name} />

        <Button size="sm" variant="ghost" onClick={open}>
          Open
        </Button>

        <div className="relative" ref={ref}>
          <button
            onClick={() => setMenu((current) => !current)}
            aria-label="Project actions"
            className="cursor-pointer rounded-[var(--radius-sm)] p-1.5 text-[var(--color-subtle)] transition-colors hover:bg-[var(--color-panel)] hover:text-[var(--color-text)]"
          >
            <MoreHorizontal size={15} />
          </button>
          {menu ? (
            <div className="animate-in absolute right-0 z-40 mt-1 w-44 overflow-hidden rounded-[var(--radius-md)] border border-[var(--color-border-strong)] bg-[var(--color-panel)] py-1 shadow-xl">
              <button
                onClick={() => {
                  setMenu(false);
                  pin.mutate(!project.pinned);
                }}
                className="flex w-full cursor-pointer items-center gap-2 px-3 py-1.5 text-left text-sm text-[var(--color-muted)] transition-colors hover:bg-[var(--color-panel-hover)] hover:text-[var(--color-text)]"
              >
                {project.pinned ? <PinOff size={13} /> : <Pin size={13} />}
                {project.pinned ? "Unpin" : "Pin to top"}
              </button>
              <button
                onClick={() => {
                  setMenu(false);
                  open();
                }}
                className="flex w-full cursor-pointer items-center gap-2 px-3 py-1.5 text-left text-sm text-[var(--color-muted)] transition-colors hover:bg-[var(--color-panel-hover)] hover:text-[var(--color-text)]"
              >
                <Settings2 size={13} />
                Configure
              </button>
              <button
                onClick={() => {
                  setMenu(false);
                  onRemove();
                }}
                className="flex w-full cursor-pointer items-center gap-2 px-3 py-1.5 text-left text-sm text-[var(--color-danger)] transition-colors hover:bg-[var(--color-danger)]/10"
              >
                <Trash2 size={13} />
                Remove
              </button>
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}

export function ProjectsPage() {
  const queryClient = useQueryClient();
  const projects = useQuery({ queryKey: keys.projects, queryFn: listProjects });
  const builds = useQuery({ queryKey: keys.builds, queryFn: () => listBuilds(), refetchInterval: 8000 });
  const recent = useRecentProjects();

  const [wizardOpen, setWizardOpen] = useState(false);
  const [picking, setPicking] = useState(false);
  const [form, setForm] = useState({ name: "", path: "", api_local: "" });
  const [removeName, setRemoveName] = useState<string | null>(null);
  const [scanning, setScanning] = useState(false);
  const [filter, setFilter] = useState("");
  const revealed = useUi((state) => state.projectsRevealed);
  const setRevealed = useUi((state) => state.setProjectsRevealed);

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
      toast.success("Project added");
      refresh();
    },
  });
  const scan = useMutation({
    mutationFn: (path?: string) => scanProjects(path),
    onSuccess: (result) => {
      toast.success(result.added.length ? `Registered ${result.added.length}` : "Nothing new found");
      refresh();
    },
  });
  const remove = useMutation({
    mutationFn: deleteProject,
    onSuccess: (_result, name) => {
      forgetProject(name);
      setRemoveName(null);
      toast.success("Project removed");
      refresh();
    },
  });

  const entries = Object.entries(projects.data?.projects ?? {});

  // Most recent build per project, so a row says what actually happened.
  const latest = useMemo(() => {
    const map = new Map<string, Build>();
    for (const build of builds.data?.builds ?? []) {
      if (!map.has(build.project)) map.set(build.project, build);
    }
    return map;
  }, [builds.data]);

  const needle = filter.trim().toLowerCase();
  const matching = needle
    ? entries.filter(([name, project]) => `${name} ${project.package ?? ""}`.toLowerCase().includes(needle))
    : entries;
  const byName = new Map(matching);

  const pinned = matching.filter(([, project]) => project.pinned);
  const recentEntries = recent
    .map((name) => [name, byName.get(name)] as const)
    .filter((entry): entry is [string, Project] => Boolean(entry[1]))
    .filter(([name]) => !pinned.some(([pinnedName]) => pinnedName === name));

  const atTop = new Set([...pinned, ...recentEntries].map(([name]) => name));
  const others = matching.filter(([name]) => !atTop.has(name));

  // Collapsed by default, and deliberately not persisted: the safe state is the
  // one you get when you reload, so a reveal cannot be forgotten.
  const showOthers = revealed || Boolean(needle);

  const section = (title: string, rows: Array<[string, Project]>) =>
    rows.length ? (
      <div>
        <h2 className="mb-1.5 text-[10px] font-semibold tracking-wider text-[var(--color-subtle)] uppercase">{title}</h2>
        <Card className="overflow-hidden">
          <div className="divide-y divide-[var(--color-border)]">
            {rows.map(([name, project]) => (
              <ProjectRow
                key={name}
                name={name}
                project={project}
                last={latest.get(name)}
                onRemove={() => setRemoveName(name)}
              />
            ))}
          </div>
        </Card>
      </div>
    ) : null;

  if (projects.error) {
    return <ErrorText>{(projects.error as Error).message}</ErrorText>;
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold tracking-tight">Projects</h1>
          <p className="mt-0.5 text-sm text-[var(--color-muted)]">
            {entries.length === 0
              ? "Register a Flutter project, then build or run it."
              : `${entries.length} registered. Build an APK or AAB without a device.`}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="secondary" size="sm" onClick={() => setScanning(true)} disabled={scan.isPending}>
            {scan.isPending ? "Scanning…" : "Scan a folder…"}
          </Button>
          <Button size="sm" onClick={() => setWizardOpen(true)}>
            Add project
          </Button>
        </div>
      </div>

      {entries.length > 0 ? (
        <Card className="flex flex-wrap items-center gap-2 p-3">
          <div className="relative min-w-48 flex-1">
            <Search size={13} className="absolute top-1/2 left-2.5 -translate-y-1/2 text-[var(--color-subtle)]" />
            <Input
              value={filter}
              onChange={(event) => setFilter(event.target.value)}
              placeholder="Filter projects…"
              className="pl-8"
            />
            {filter ? (
              <button
                onClick={() => setFilter("")}
                aria-label="Clear filter"
                className="absolute top-1/2 right-2 -translate-y-1/2 cursor-pointer text-[var(--color-subtle)] hover:text-[var(--color-text)]"
              >
                <X size={13} />
              </button>
            ) : null}
          </div>
          <Tooltip label={revealed ? "Hide the rest again" : "Show every registered project"}>
            <Button variant="ghost" size="sm" onClick={() => setRevealed(!revealed)}>
              {revealed ? <EyeOff size={13} /> : <Eye size={13} />}
              {revealed ? "Hide others" : `Show all (${others.length})`}
            </Button>
          </Tooltip>
        </Card>
      ) : null}

      {projects.isLoading ? (
        <Card className="p-4">
          <SkeletonRows rows={4} />
        </Card>
      ) : entries.length === 0 ? (
        <Card>
          <EmptyState
            icon={<FolderKanban size={22} />}
            title="No projects yet"
            description="Point Fenox at a folder holding a pubspec.yaml. The port, URLs and Android package are detected for you."
            action={
              <Button size="sm" onClick={() => setWizardOpen(true)}>
                Add your first project
              </Button>
            }
          />
        </Card>
      ) : matching.length === 0 ? (
        <Card>
          <EmptyState title="Nothing matches" description={`No project contains “${filter}”.`} />
        </Card>
      ) : (
        <div className="space-y-5">
          {section("Pinned", pinned)}
          {section("Recent", recentEntries)}

          {others.length > 0 ? (
            <div>
              <button
                onClick={() => setRevealed(!revealed)}
                className="mb-1.5 flex cursor-pointer items-center gap-1.5 text-[10px] font-semibold tracking-wider text-[var(--color-subtle)] uppercase transition-colors hover:text-[var(--color-muted)]"
              >
                {showOthers ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                Other projects · {others.length}
                {showOthers ? null : <span className="normal-case">hidden</span>}
              </button>
              {showOthers ? (
                <Card className="overflow-hidden">
                  <div className="divide-y divide-[var(--color-border)]">
                    {others.map(([name, project]) => (
                      <ProjectRow
                        key={name}
                        name={name}
                        project={project}
                        last={latest.get(name)}
                        onRemove={() => setRemoveName(name)}
                      />
                    ))}
                  </div>
                </Card>
              ) : null}
            </div>
          ) : null}

          {pinned.length === 0 && recentEntries.length === 0 ? (
            <p className="flex items-center gap-1.5 text-xs text-[var(--color-subtle)]">
              <Folder size={12} />
              Pin a project to keep it visible here — handy when sharing your screen.
            </p>
          ) : null}
        </div>
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
        <Modal
          title="Remove project"
          description="The project's files on disk are not touched."
          onClose={() => setRemoveName(null)}
          footer={
            <>
              <Button variant="ghost" onClick={() => setRemoveName(null)}>
                Cancel
              </Button>
              <Button variant="danger" disabled={remove.isPending} onClick={() => remove.mutate(removeName)}>
                {remove.isPending ? "Removing…" : "Remove"}
              </Button>
            </>
          }
        >
          <p className="text-sm text-[var(--color-muted)]">
            Remove <span className="font-medium text-[var(--color-text)]">{removeName}</span> from Fenox?
          </p>
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
    <Modal title="Add project" description="Three questions. Everything else is detected." onClose={onClose}>
      <form
        className="space-y-4"
        onSubmit={(event) => {
          event.preventDefault();
          if (isLast) onSubmit();
          else if (canContinue) setStep(step + 1);
        }}
      >
        <ol className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs">
          {STEPS.map((label, index) => (
            <li key={label} className="flex items-center gap-2">
              <span
                className={cn(
                  "flex h-5 w-5 items-center justify-center rounded-full border text-[11px]",
                  index === step
                    ? "border-[var(--color-accent)] text-[var(--color-accent)]"
                    : index < step
                      ? "border-[var(--color-success)]/60 text-[var(--color-success)]"
                      : "border-[var(--color-border)] text-[var(--color-muted)]",
                )}
              >
                {index < step ? "✓" : index + 1}
              </span>
              <span className={index === step ? "text-[var(--color-text)]" : "text-[var(--color-muted)]"}>
                {label}
              </span>
              {index < STEPS.length - 1 ? <span className="text-[var(--color-border)]">—</span> : null}
            </li>
          ))}
        </ol>

        {step === 0 ? (
          <Field label="Project name" hint="Lowercase; used as the id everywhere.">
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
            <span className="block text-[11px] font-medium tracking-wide text-[var(--color-muted)] uppercase">
              Project directory
            </span>
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
            <p className="text-xs text-[var(--color-subtle)]">
              The folder holding pubspec.yaml. Picking it can fill in the name for you.
            </p>
          </div>
        ) : null}

        {step === 2 ? (
          <Field label="Backend link" hint="Used for local runs. Leave blank to detect it.">
            <Input
              autoFocus
              value={form.api_local}
              onChange={(event) => setForm({ ...form, api_local: event.target.value })}
              placeholder="http://localhost:1991/api"
            />
          </Field>
        ) : null}

        <ErrorText>{error}</ErrorText>

        <div className="flex items-center justify-between gap-2">
          <Button type="button" variant="ghost" onClick={step === 0 ? onClose : () => setStep(step - 1)}>
            {step === 0 ? "Cancel" : "Back"}
          </Button>
          <div className="flex items-center gap-2">
            <span className="text-[11px] text-[var(--color-subtle)]">
              {step + 1} / {STEPS.length}
            </span>
            <Button type="submit" disabled={saving || !canContinue}>
              {isLast ? (saving ? "Adding…" : "Add project") : "Next"}
            </Button>
          </div>
        </div>
      </form>
    </Modal>
  );
}
