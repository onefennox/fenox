import { useQuery } from "@tanstack/react-query";
import { ChevronUp, Folder, FolderOpen, RefreshCw } from "lucide-react";
import { useEffect, useState } from "react";

import { browseDirs, keys } from "@/api/queries";
import { Button, ErrorText, Input, Modal, Spinner } from "@/components/ui";

/**
 * A real folder browser for the host machine, so choosing a directory never
 * means typing a path. Subdirectories come from the hub (`/api/system/browse`),
 * which marks the ones that are Flutter app roots so the right folder is easy
 * to spot.
 */
export function FolderPicker({
  initialPath,
  title = "Choose a folder",
  onSelect,
  onClose,
}: {
  initialPath?: string;
  title?: string;
  onSelect: (path: string, suggestedName?: string) => void;
  onClose: () => void;
}) {
  const [path, setPath] = useState(initialPath?.trim() || "");
  const { data, isLoading, error, refetch, isFetching } = useQuery({
    queryKey: keys.browse(path),
    queryFn: () => browseDirs(path || undefined),
  });

  // Jump to a listing the moment one is chosen from the quick links.
  useEffect(() => {
    if (data?.path) {
      setPath(data.path);
    }
  }, [data?.path]);

  const listing = data;

  return (
    <Modal title={title} onClose={onClose} wide>
      <div className="space-y-3">
        <div className="flex gap-2">
          <Input
            value={path}
            onChange={(event) => setPath(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                void refetch();
              }
            }}
            placeholder="~/Projects"
            aria-label="Path"
          />
          <Button
            type="button"
            variant="secondary"
            onClick={() => void refetch()}
            disabled={isFetching}
            title="Go to this path"
          >
            <RefreshCw size={14} />
            Go
          </Button>
        </div>

        {listing?.quick?.length ? (
          <div className="flex flex-wrap gap-1.5">
            {listing.quick.map((entry) => (
              <Button
                key={entry.path}
                type="button"
                variant="ghost"
                className="border border-[var(--color-border)]"
                onClick={() => setPath(entry.path)}
              >
                {entry.label}
              </Button>
            ))}
          </div>
        ) : null}

        {error ? <ErrorText>{(error as Error).message}</ErrorText> : null}

        {isLoading ? (
          <Spinner label="Reading folder" />
        ) : (
          <div className="min-h-64 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)]">
            {listing?.parent ? (
              <button
                type="button"
                onClick={() => setPath(listing.parent as string)}
                className="flex w-full cursor-pointer items-center gap-2 border-b border-[var(--color-border)] px-3 py-2 text-left text-sm text-[var(--color-muted)] hover:bg-[var(--color-panel-hover)] hover:text-white"
              >
                <ChevronUp size={16} />
                <span className="truncate">Up to {listing.parent.split("/").filter(Boolean).pop()}</span>
              </button>
            ) : null}

            {listing?.dirs.length ? (
              <ul className="max-h-72 overflow-y-auto">
                {listing.dirs.map((dir) => (
                  <li key={dir.path}>
                    <button
                      type="button"
                      onClick={() => setPath(dir.path)}
                      className="flex w-full cursor-pointer items-center gap-2 px-3 py-2 text-left text-sm text-white hover:bg-[var(--color-panel-hover)]"
                    >
                      {dir.flutter ? (
                        <FolderOpen size={16} className="shrink-0 text-[var(--color-accent)]" />
                      ) : (
                        <Folder size={16} className="shrink-0 text-[var(--color-muted)]" />
                      )}
                      <span className="truncate">{dir.name}</span>
                      {dir.flutter ? (
                        <span className="ml-auto shrink-0 rounded-full border border-[var(--color-accent)]/40 px-2 py-0.5 text-xs text-[var(--color-accent)]">
                          Flutter
                        </span>
                      ) : null}
                    </button>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="px-3 py-6 text-center text-sm text-[var(--color-muted)]">No subfolders here.</p>
            )}
          </div>
        )}

        {listing?.truncated ? (
          <p className="text-xs text-amber-400">This folder has a lot of subfolders; only the first are shown.</p>
        ) : null}
        {listing?.flutter ? (
          <p className="text-xs text-emerald-400">This folder is a Flutter project.</p>
        ) : null}

        <div className="flex justify-end gap-2">
          <Button type="button" variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button type="button" onClick={() => listing && onSelect(listing.path, listing.suggested_name)} disabled={!listing}>
            Select this folder
          </Button>
        </div>
      </div>
    </Modal>
  );
}

/**
 * A path input with a Browse button, so every folder field in the app can be
 * filled by clicking rather than typing. The text stays editable as an escape
 * hatch for paths the browser cannot reach.
 */
export function PathField({
  label,
  value,
  onChange,
  placeholder,
  browseTitle,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  browseTitle?: string;
}) {
  const [picking, setPicking] = useState(false);

  return (
    <div className="space-y-1.5">
      <span className="text-xs font-medium tracking-wide text-[var(--color-muted)] uppercase">{label}</span>
      <div className="flex gap-2">
        <Input
          value={value}
          onChange={(event) => onChange(event.target.value)}
          placeholder={placeholder}
          aria-label={label}
        />
        <Button type="button" variant="secondary" onClick={() => setPicking(true)} className="shrink-0">
          <Folder size={14} />
          Browse
        </Button>
      </div>
      {picking ? (
        <FolderPicker
          title={browseTitle ?? `Choose ${label.toLowerCase()}`}
          initialPath={value}
          onSelect={(path) => {
            onChange(path);
            setPicking(false);
          }}
          onClose={() => setPicking(false)}
        />
      ) : null}
    </div>
  );
}
