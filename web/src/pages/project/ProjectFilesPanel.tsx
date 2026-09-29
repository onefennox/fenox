import { useQuery } from "@tanstack/react-query";
import { ChevronUp, FileCode, FileText, Folder, Loader2 } from "lucide-react";
import { useState } from "react";

import { getProjectFile, getProjectTree, keys } from "@/api/queries";
import { Card, EmptyState, SkeletonRows } from "@/components/ui";
import { cn, formatBytes } from "@/lib/format";

/**
 * The project's own files.
 *
 * Read-only and confined to the project directory on the server — the guard is
 * there, not here, because a client-side check is a suggestion. Worth having in
 * the same place as the builds and the runs: looking at `pubspec.yaml` or an
 * `AndroidManifest.xml` is usually the next thing after a build fails.
 */
export function ProjectFilesPanel({ project }: { project: string }) {
  const [path, setPath] = useState("");
  const [openFile, setOpenFile] = useState<string | null>(null);

  const tree = useQuery({
    queryKey: keys.tree(project, path),
    queryFn: () => getProjectTree(project, path),
  });

  const file = useQuery({
    queryKey: ["project-file", project, openFile],
    queryFn: () => getProjectFile(project, openFile as string),
    enabled: Boolean(openFile),
  });

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-5">
      <Card className="lg:col-span-2">
        <div className="flex items-center justify-between border-b border-[var(--color-border)] px-3 py-2">
          <span className="font-mono text-[11px] text-[var(--color-muted)]">/{path}</span>
          {path ? (
            <button
              onClick={() => {
                setPath(tree.data?.parent ?? "");
                setOpenFile(null);
              }}
              className="flex cursor-pointer items-center gap-1 text-[11px] text-[var(--color-muted)] transition-colors hover:text-[var(--color-text)]"
            >
              <ChevronUp size={12} />
              up
            </button>
          ) : null}
        </div>

        {tree.isLoading ? (
          <div className="p-3">
            <SkeletonRows rows={6} />
          </div>
        ) : tree.error ? (
          <p className="p-3 text-sm text-[var(--color-danger)]">{(tree.error as Error).message}</p>
        ) : (tree.data?.entries.length ?? 0) === 0 ? (
          <EmptyState title="Empty folder" description="Nothing here to show." />
        ) : (
          <ul className="max-h-[60vh] overflow-y-auto py-1">
            {(tree.data?.entries ?? []).map((entry) => (
              <li key={entry.path}>
                <button
                  onClick={() => {
                    if (entry.dir) {
                      setPath(entry.path);
                      setOpenFile(null);
                    } else {
                      setOpenFile(entry.path);
                    }
                  }}
                  className={cn(
                    "flex w-full cursor-pointer items-center gap-2 px-3 py-1.5 text-left text-sm transition-colors",
                    openFile === entry.path ? "bg-[var(--color-accent-soft)]" : "hover:bg-[var(--color-panel-hover)]",
                  )}
                >
                  {entry.dir ? (
                    <Folder size={14} className="shrink-0 text-[var(--color-accent)]" />
                  ) : entry.name.endsWith(".dart") ? (
                    <FileCode size={14} className="shrink-0 text-[var(--color-muted)]" />
                  ) : (
                    <FileText size={14} className="shrink-0 text-[var(--color-subtle)]" />
                  )}
                  <span className="flex-1 truncate">{entry.name}</span>
                  {!entry.dir ? (
                    <span className="tnum shrink-0 text-[10px] text-[var(--color-subtle)]">
                      {formatBytes(entry.size, 0)}
                    </span>
                  ) : null}
                </button>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Card className="overflow-hidden lg:col-span-3">
        <div className="flex items-center justify-between border-b border-[var(--color-border)] px-3 py-2">
          <span className="truncate font-mono text-[11px] text-[var(--color-muted)]">
            {openFile ?? "Select a file"}
          </span>
          {file.isFetching ? <Loader2 size={12} className="animate-spin text-[var(--color-subtle)]" /> : null}
        </div>
        {!openFile ? (
          <EmptyState title="No file open" description="Pick a file on the left to read it here." />
        ) : file.error ? (
          <p className="p-3 text-sm text-[var(--color-danger)]">{(file.error as Error).message}</p>
        ) : (
          <pre className="scroll-thin max-h-[60vh] overflow-auto bg-[var(--color-surface)] p-3 font-mono text-[11px] leading-relaxed whitespace-pre text-[var(--color-muted)]">
            {file.data?.text ?? ""}
          </pre>
        )}
      </Card>
    </div>
  );
}
