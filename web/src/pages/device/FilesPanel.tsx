import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { fileDownloadUrl, keys, listFiles, makeDir, pushFile, removeFile } from "@/api/queries";
import type { Device } from "@/api/types";
import { Button, Card, ErrorText, Input, Spinner } from "@/components/ui";

export function FilesPanel({ device }: { device: Device }) {
  const queryClient = useQueryClient();
  const [path, setPath] = useState("/sdcard");
  const [pushLocal, setPushLocal] = useState("");
  const [newDir, setNewDir] = useState("");

  const listing = useQuery({
    queryKey: [...keys.info(device.id), "files", path],
    queryFn: () => listFiles(device.id, path),
    enabled: device.online,
  });

  const refresh = () => queryClient.invalidateQueries({ queryKey: [...keys.info(device.id), "files"] });
  const act = useMutation({
    mutationFn: (action: () => Promise<unknown>) => action(),
    onSuccess: refresh,
  });

  if (!device.online) {
    return <Card className="p-6 text-sm text-[var(--color-muted)]">The device is offline.</Card>;
  }

  const segments = path.split("/").filter(Boolean);

  return (
    <div className="space-y-4">
      <Card className="flex flex-wrap items-center gap-2 p-3 text-sm">
        <button className="cursor-pointer text-[var(--color-accent)] hover:underline" onClick={() => setPath("/")}>
          /
        </button>
        {segments.map((segment, index) => {
          const target = "/" + segments.slice(0, index + 1).join("/");
          return (
            <span key={target} className="flex items-center gap-2">
              <button className="cursor-pointer text-[var(--color-accent)] hover:underline" onClick={() => setPath(target)}>
                {segment}
              </button>
              {index < segments.length - 1 ? <span className="text-[var(--color-muted)]">/</span> : null}
            </span>
          );
        })}
        <div className="ml-auto flex gap-2">
          <Button variant="ghost" onClick={() => setPath(listing.data?.parent ?? "/")}>
            Up
          </Button>
        </div>
      </Card>

      <Card className="flex flex-wrap items-end gap-2 p-3">
        <div className="min-w-48 flex-1">
          <Input value={pushLocal} onChange={(event) => setPushLocal(event.target.value)} placeholder="Local path on this machine" />
        </div>
        <Button disabled={!pushLocal || act.isPending} onClick={() => act.mutate(() => pushFile(device.id, pushLocal, path))}>
          Push here
        </Button>
        <div className="w-40">
          <Input value={newDir} onChange={(event) => setNewDir(event.target.value)} placeholder="New folder" />
        </div>
        <Button
          variant="secondary"
          disabled={!newDir || act.isPending}
          onClick={() =>
            act.mutate(async () => {
              await makeDir(device.id, `${path.replace(/\/$/, "")}/${newDir}`);
              setNewDir("");
            })
          }
        >
          Create
        </Button>
      </Card>

      <ErrorText>{(act.error as Error | null)?.message}</ErrorText>

      {listing.isLoading ? (
        <Spinner label="Listing files" />
      ) : listing.error ? (
        <Card className="p-4 text-sm text-amber-300">{(listing.error as Error).message}</Card>
      ) : (
        <Card className="max-h-[520px] divide-y divide-[var(--color-border)] overflow-y-auto">
          {(listing.data?.entries ?? []).map((entry) => (
            <div key={entry.path} className="flex items-center gap-3 p-2.5 text-sm">
              {entry.type === "dir" ? (
                <button className="min-w-0 flex-1 cursor-pointer truncate text-left text-white hover:underline" onClick={() => setPath(entry.path)}>
                  {entry.name}/
                </button>
              ) : (
                <a className="min-w-0 flex-1 truncate text-white hover:underline" href={fileDownloadUrl(device.id, entry.path)}>
                  {entry.name}
                </a>
              )}
              <span className="w-20 text-right text-xs text-[var(--color-muted)]">
                {entry.type === "file" ? `${entry.size} B` : entry.type}
              </span>
              <span className="hidden w-32 text-right text-xs text-[var(--color-muted)] sm:inline">{entry.modified}</span>
              <Button variant="ghost" onClick={() => act.mutate(() => removeFile(device.id, entry.path))}>
                Delete
              </Button>
            </div>
          ))}
          {(listing.data?.entries ?? []).length === 0 ? (
            <p className="p-4 text-sm text-[var(--color-muted)]">This folder is empty.</p>
          ) : null}
        </Card>
      )}
    </div>
  );
}
