import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { getDoctor, installTool } from "@/api/queries";
import type { ToolCheck } from "@/api/types";
import { Badge, Button, Card, Spinner } from "@/components/ui";

export function SystemPage() {
  const queryClient = useQueryClient();
  const doctor = useQuery({ queryKey: ["doctor"], queryFn: getDoctor });
  const [command, setCommand] = useState<{ tool: string; command: string } | null>(null);

  const install = useMutation({
    mutationFn: installTool,
    onSuccess: (result, tool) => {
      if (result.requires_sudo && result.command) {
        setCommand({ tool, command: result.command });
      } else {
        setCommand(null);
        queryClient.invalidateQueries({ queryKey: ["doctor"] });
      }
    },
  });

  if (doctor.isLoading) {
    return <Spinner label="Checking the environment" />;
  }
  if (doctor.error || !doctor.data) {
    return <p className="text-sm text-red-400">{(doctor.error as Error | null)?.message ?? "Doctor unavailable."}</p>;
  }

  const report = doctor.data;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-lg font-semibold text-white">System</h1>
        <p className="mt-1 text-sm text-[var(--color-muted)]">
          Tools Fenox uses, and what is missing. Installations that need root are shown as a command for you to run.
        </p>
      </div>

      <Card className="p-5">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-white">Environment</h2>
          <Button variant="ghost" onClick={() => queryClient.invalidateQueries({ queryKey: ["doctor"] })}>
            Re-check
          </Button>
        </div>
        <div className="text-sm text-[var(--color-muted)]">
          {report.platform.wsl ? "WSL" : report.platform.linux ? "Linux" : "Unknown"} · adb server port{" "}
          {report.adb.server_port} · Windows adb {report.adb.windows_exe ? "found" : "not found"}
        </div>
        {report.notes.map((note) => (
          <p key={note.text} className={`mt-2 text-sm ${note.tone === "warn" ? "text-amber-300" : "text-emerald-300"}`}>
            {note.text}
          </p>
        ))}
      </Card>

      <Card className="divide-y divide-[var(--color-border)]">
        {report.tools.map((tool) => (
          <ToolRow key={tool.name} tool={tool} onInstall={() => install.mutate(tool.name)} busy={install.isPending} />
        ))}
      </Card>

      {command ? (
        <Card className="border-amber-500/30 p-4">
          <p className="text-sm text-amber-300">
            Installing {command.tool} needs root. Run this yourself:
          </p>
          <pre className="mt-2 overflow-auto rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] p-3 text-xs text-white">
            {command.command}
          </pre>
        </Card>
      ) : null}
      {install.data?.output ? (
        <Card className="p-4">
          <pre className="max-h-48 overflow-auto text-xs text-[var(--color-muted)]">{install.data.output}</pre>
        </Card>
      ) : null}
    </div>
  );
}

function ToolRow({ tool, onInstall, busy }: { tool: ToolCheck; onInstall: () => void; busy: boolean }) {
  return (
    <div className="flex items-center gap-4 p-3 text-sm">
      <span className={`h-2 w-2 rounded-full ${tool.present ? "bg-emerald-500" : tool.required ? "bg-red-500" : "bg-[var(--color-muted)]"}`} />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="text-white">{tool.name}</span>
          {tool.required ? <Badge tone="accent">required</Badge> : <Badge>optional</Badge>}
        </div>
        <div className="truncate text-xs text-[var(--color-muted)]">
          {tool.present ? tool.version || tool.path : tool.purpose}
        </div>
      </div>
      {!tool.present ? (
        tool.manual ? (
          <a className="text-xs text-[var(--color-accent)] hover:underline" href={tool.manual} target="_blank" rel="noreferrer">
            Install guide
          </a>
        ) : (
          <Button variant="secondary" onClick={onInstall} disabled={busy}>
            Install
          </Button>
        )
      ) : null}
    </div>
  );
}
