import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ChevronLeft, Download, File, FileText, Folder, FolderOpen, HardDrive, Image, MoreHorizontal,
  Music, Plus, RefreshCw, Trash2, Upload, Video,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useRef, useState } from "react";

import { fileDownloadUrl, keys, listFiles, makeDir, removeFile, uploadFile } from "@/api/queries";
import type { Device, FileEntry } from "@/api/types";
import { Button, Card, ErrorText, Input, Spinner } from "@/components/ui";

const LOCATIONS: Array<{ label: string; path: string; icon: LucideIcon }> = [
  { label: "Internal storage", path: "/sdcard", icon: HardDrive },
  { label: "Downloads", path: "/sdcard/Download", icon: Download },
  { label: "Camera", path: "/sdcard/DCIM", icon: Image },
  { label: "Pictures", path: "/sdcard/Pictures", icon: Image },
  { label: "Videos", path: "/sdcard/Movies", icon: Video },
  { label: "Music", path: "/sdcard/Music", icon: Music },
  { label: "Documents", path: "/sdcard/Documents", icon: FileText },
];

function formatSize(bytes: number): string {
  if (!bytes) return "—";
  const units = ["B", "KB", "MB", "GB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value >= 10 || unit === 0 ? value.toFixed(0) : value.toFixed(1)} ${units[unit]}`;
}

function entryIcon(entry: FileEntry) {
  if (entry.type === "dir") return <Folder size={18} className="fill-[var(--color-accent)]/15 text-[var(--color-accent)]" />;
  const extension = entry.name.split(".").pop()?.toLowerCase();
  if (["jpg", "jpeg", "png", "gif", "webp"].includes(extension ?? "")) return <Image size={18} className="text-emerald-400" />;
  if (["mp4", "mkv", "webm", "mov"].includes(extension ?? "")) return <Video size={18} className="text-violet-400" />;
  if (["mp3", "wav", "m4a", "ogg"].includes(extension ?? "")) return <Music size={18} className="text-pink-400" />;
  return <File size={18} className="text-[var(--color-muted)]" />;
}

export function FilesPanel({ device }: { device: Device }) {
  const queryClient = useQueryClient();
  const uploadInput = useRef<HTMLInputElement>(null);
  const [path, setPath] = useState("/sdcard");
  const [address, setAddress] = useState(path);
  const [newDir, setNewDir] = useState("");
  const [creatingFolder, setCreatingFolder] = useState(false);

  const navigate = (target: string) => {
    setPath(target);
    setAddress(target);
  };
  const listing = useQuery({
    queryKey: [...keys.info(device.id), "files", path],
    queryFn: () => listFiles(device.id, path),
    enabled: device.online,
  });
  const refresh = () => queryClient.invalidateQueries({ queryKey: [...keys.info(device.id), "files"] });
  const act = useMutation({ mutationFn: (action: () => Promise<unknown>) => action(), onSuccess: refresh });

  if (!device.online) return <Card className="p-6 text-sm text-[var(--color-muted)]">Connect the device to browse its files.</Card>;

  return (
    <Card className="overflow-hidden">
      <div className="flex flex-wrap items-center gap-2 border-b border-[var(--color-border)] p-3">
        <Button variant="ghost" title="Back to parent folder" aria-label="Back to parent folder" disabled={path === "/"}
          onClick={() => navigate(listing.data?.parent ?? "/")}>
          <ChevronLeft size={17} />
        </Button>
        <form className="min-w-52 flex-1" onSubmit={(event) => { event.preventDefault(); navigate(address || "/sdcard"); }}>
          <Input value={address} onChange={(event) => setAddress(event.target.value)} aria-label="Current folder" />
        </form>
        <Button variant="ghost" title="Refresh" aria-label="Refresh files" onClick={() => void listing.refetch()}>
          <RefreshCw size={16} className={listing.isFetching ? "animate-spin" : ""} />
        </Button>
        <Button variant="secondary" onClick={() => setCreatingFolder((value) => !value)}><Plus size={16} /> New folder</Button>
        <Button onClick={() => uploadInput.current?.click()} disabled={act.isPending}><Upload size={16} /> Upload files</Button>
        <input ref={uploadInput} className="hidden" type="file" multiple onChange={(event) => {
          const selected = Array.from(event.target.files ?? []);
          if (selected.length) act.mutate(async () => { for (const file of selected) await uploadFile(device.id, file, path); });
          event.target.value = "";
        }} />
      </div>

      {creatingFolder ? (
        <form className="flex items-center gap-2 border-b border-[var(--color-border)] bg-[var(--color-panel-hover)] p-3"
          onSubmit={(event) => {
            event.preventDefault();
            if (!newDir) return;
            act.mutate(async () => { await makeDir(device.id, `${path.replace(/\/$/, "")}/${newDir}`); setNewDir(""); setCreatingFolder(false); });
          }}>
          <FolderOpen size={18} className="text-[var(--color-accent)]" />
          <Input autoFocus className="max-w-sm" value={newDir} onChange={(event) => setNewDir(event.target.value)} placeholder="Folder name" />
          <Button type="submit" disabled={!newDir || act.isPending}>Create</Button>
          <Button type="button" variant="ghost" onClick={() => setCreatingFolder(false)}>Cancel</Button>
        </form>
      ) : null}

      <div className="grid min-h-[470px] grid-cols-1 md:grid-cols-[190px_minmax(0,1fr)]">
        <aside className="hidden border-r border-[var(--color-border)] p-2 md:block">
          <p className="px-3 py-2 text-[10px] font-semibold tracking-wider text-[var(--color-muted)] uppercase">Locations</p>
          {LOCATIONS.map(({ label, path: location, icon: Icon }) => (
            <button key={location} onClick={() => navigate(location)}
              className={`flex w-full cursor-pointer items-center gap-2 rounded-md px-3 py-2 text-left text-sm transition ${path === location ? "bg-[var(--color-panel-hover)] text-white" : "text-[var(--color-muted)] hover:bg-[var(--color-panel-hover)] hover:text-white"}`}>
              <Icon size={16} className={path === location ? "text-[var(--color-accent)]" : ""} /> {label}
            </button>
          ))}
        </aside>

        <div className="min-w-0">
          <div className="grid grid-cols-[minmax(0,1fr)_90px_140px_84px] border-b border-[var(--color-border)] px-4 py-2 text-[10px] font-semibold tracking-wider text-[var(--color-muted)] uppercase max-sm:grid-cols-[minmax(0,1fr)_72px_76px]">
            <span>Name</span><span className="text-right">Size</span><span className="text-right max-sm:hidden">Modified</span><span />
          </div>
          {listing.isLoading ? <div className="p-6"><Spinner label="Opening folder" /></div> : listing.error ? (
            <p className="p-5 text-sm text-amber-300">{(listing.error as Error).message}</p>
          ) : (listing.data?.entries ?? []).length === 0 ? (
            <div className="grid min-h-72 place-items-center p-8 text-center">
              <div><FolderOpen size={32} className="mx-auto mb-3 text-[var(--color-muted)]" /><p className="text-sm text-white">This folder is empty</p><p className="mt-1 text-xs text-[var(--color-muted)]">Upload files or create a folder to get started.</p></div>
            </div>
          ) : (
            <div className="max-h-[520px] divide-y divide-[var(--color-border)] overflow-y-auto">
              {(listing.data?.entries ?? []).map((entry) => (
                <div key={entry.path} className="group grid grid-cols-[minmax(0,1fr)_90px_140px_84px] items-center px-4 py-2.5 text-sm hover:bg-[var(--color-panel-hover)] max-sm:grid-cols-[minmax(0,1fr)_72px_76px]">
                  {entry.type === "dir" ? (
                    <button className="flex min-w-0 cursor-pointer items-center gap-3 text-left text-white" onClick={() => navigate(entry.path)}>
                      {entryIcon(entry)}<span className="truncate">{entry.name}</span>
                    </button>
                  ) : (
                    <a className="flex min-w-0 items-center gap-3 text-white" href={fileDownloadUrl(device.id, entry.path)}>
                      {entryIcon(entry)}<span className="truncate">{entry.name}</span>
                    </a>
                  )}
                  <span className="text-right text-xs text-[var(--color-muted)]">{entry.type === "file" ? formatSize(entry.size) : "—"}</span>
                  <span className="text-right text-xs text-[var(--color-muted)] max-sm:hidden">{entry.modified}</span>
                  <div className="flex justify-end gap-1">
                    {entry.type !== "dir" ? <a className="rounded-md p-2 text-[var(--color-muted)] hover:bg-[var(--color-border)] hover:text-white" title="Download" href={fileDownloadUrl(device.id, entry.path)}><Download size={15} /></a> : null}
                    <button className="cursor-pointer rounded-md p-2 text-[var(--color-muted)] hover:bg-red-500/10 hover:text-red-400" title="Delete"
                      onClick={() => { if (window.confirm(`Delete ${entry.name}?`)) act.mutate(() => removeFile(device.id, entry.path)); }}><Trash2 size={15} /></button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
      <div className="flex items-center justify-between border-t border-[var(--color-border)] px-4 py-2 text-xs text-[var(--color-muted)]">
        <span>{listing.data?.entries.length ?? 0} items</span><span className="flex items-center gap-1"><MoreHorizontal size={14} /> {path}</span>
      </div>
      <div className="px-4 pb-3"><ErrorText>{(act.error as Error | null)?.message}</ErrorText></div>
    </Card>
  );
}
