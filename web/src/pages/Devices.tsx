import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  LayoutGrid,
  MoreHorizontal,
  Pencil,
  Plus,
  Power,
  Rows3,
  Smartphone,
  Trash2,
  Wifi,
  Cable,
} from "lucide-react";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { connectDevice, deleteDevice, keys, listDevices, updateDevice } from "@/api/queries";
import type { Device } from "@/api/types";
import { Menu } from "@/components/Menu";
import { PhoneFrame } from "@/components/PhoneFrame";
import { useActiveDevice } from "@/hooks/useActiveDevice";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorText,
  Field,
  Input,
  Modal,
  SegmentedControl,
  SkeletonRows,
  StatusDot,
} from "@/components/ui";
import { cn } from "@/lib/format";

type View = "table" | "grid";

const VIEW_KEY = "fenox.devices.view";

function initialView(): View {
  try {
    return localStorage.getItem(VIEW_KEY) === "grid" ? "grid" : "table";
  } catch {
    return "table";
  }
}

/** Row actions, behind the shared Menu so nothing clips them. */
function RowMenu({
  device,
  onRename,
  onRemove,
  onToggle,
}: {
  device: Device;
  onRename: () => void;
  onRemove: () => void;
  onToggle: () => void;
}) {
  return (
    <Menu
      label={`Actions for ${device.id}`}
      buttonSize="icon"
      buttonClassName="text-[var(--color-subtle)]"
      widthClass="w-44"
      items={[
        { id: "rename", label: "Rename", icon: <Pencil size={13} />, onSelect: onRename },
        {
          id: "toggle",
          label: device.disabled ? "Enable" : "Disable",
          icon: <Power size={13} />,
          onSelect: onToggle,
        },
        { id: "remove", label: "Remove", icon: <Trash2 size={13} />, danger: true, onSelect: onRemove },
      ]}
    >
      <MoreHorizontal size={15} />
    </Menu>
  );
}

export function DevicesPage() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const { setActiveDevice } = useActiveDevice();
  const { data, isLoading, error } = useQuery({ queryKey: keys.devices, queryFn: listDevices });

  const [view, setView] = useState<View>(initialView);
  const [renameTarget, setRenameTarget] = useState<Device | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [removeTarget, setRemoveTarget] = useState<Device | null>(null);

  const refresh = () => queryClient.invalidateQueries({ queryKey: keys.devices });
  const openDevice = (deviceId: string) => {
    setActiveDevice(deviceId);
    navigate(`/devices/${encodeURIComponent(deviceId)}`);
  };

  const connect = useMutation({ mutationFn: connectDevice, onSuccess: refresh });
  const update = useMutation({
    mutationFn: ({ id, patch }: { id: string; patch: Partial<Device> & { name?: string } }) => updateDevice(id, patch),
    onSuccess: refresh,
  });
  const remove = useMutation({ mutationFn: deleteDevice, onSuccess: refresh });

  const changeView = (next: View) => {
    setView(next);
    try {
      localStorage.setItem(VIEW_KEY, next);
    } catch {
      // Remembering the preference is a convenience.
    }
  };

  const devices = data?.devices ?? [];
  const pending = data?.pending ?? [];
  const unauthorized = pending.filter((item) => item.state === "unauthorized");
  const online = devices.filter((device) => device.online && !device.disabled).length;

  if (error) {
    return <ErrorText>{(error as Error).message}</ErrorText>;
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold tracking-tight">Devices</h1>
          <p className="mt-0.5 text-sm text-[var(--color-muted)]">
            {devices.length === 0
              ? "Connect a phone over USB or wireless debugging."
              : `${online} of ${devices.length} online.`}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {devices.length > 0 ? (
            <SegmentedControl<View>
              value={view}
              onChange={changeView}
              options={[
                { id: "table", label: "Table", icon: <Rows3 size={13} /> },
                { id: "grid", label: "Grid", icon: <LayoutGrid size={13} /> },
              ]}
            />
          ) : null}
          <Link to="/connect">
            <Button size="sm">
              <Plus size={14} />
              Add device
            </Button>
          </Link>
        </div>
      </div>

      {unauthorized.length > 0 ? (
        <Card className="border-[var(--color-warning)]/40 bg-[var(--color-warning)]/5 p-3">
          {unauthorized.map((item) => (
            <p key={item.id} className="text-sm text-[var(--color-warning)]">
              {item.id} is waiting for authorisation — accept the “Allow USB debugging?” prompt on the phone.
            </p>
          ))}
        </Card>
      ) : null}

      {isLoading ? (
        <Card className="p-4">
          <SkeletonRows rows={4} />
        </Card>
      ) : devices.length === 0 ? (
        <Card>
          <EmptyState
            icon={<Smartphone size={22} />}
            title="No devices yet"
            description="Wireless debugging needs nothing installed on this machine. USB on WSL needs the usbipd bridge once."
            action={
              <Link to="/connect">
                <Button>
                  <Plus size={14} />
                  Connect a device
                </Button>
              </Link>
            }
          />
        </Card>
      ) : view === "table" ? (
        <Card className="overflow-hidden">
          {/* Dense rows: a table is the right shape once there are several phones. */}
          <div className="grid grid-cols-[20px_minmax(0,1fr)_minmax(0,1fr)_90px_minmax(0,1fr)_36px] items-center gap-3 border-b border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-2 text-[10px] font-semibold tracking-wider text-[var(--color-subtle)] uppercase max-md:grid-cols-[20px_minmax(0,1fr)_90px_36px]">
            <span />
            <span>Device</span>
            <span className="max-md:hidden">Model</span>
            <span>Transport</span>
            <span className="max-md:hidden">Address</span>
            <span />
          </div>
          <div className="divide-y divide-[var(--color-border)]">
            {devices.map((device) => (
              <div
                key={device.id}
                onClick={() => openDevice(device.id)}
                className="grid cursor-pointer grid-cols-[20px_minmax(0,1fr)_minmax(0,1fr)_90px_minmax(0,1fr)_36px] items-center gap-3 px-3 py-2.5 transition-colors hover:bg-[var(--color-panel-hover)] max-md:grid-cols-[20px_minmax(0,1fr)_90px_36px]"
              >
                <StatusDot online={device.online} disabled={device.disabled} />
                <div className="flex min-w-0 items-center gap-2">
                  <span className={cn("truncate text-sm font-medium", device.disabled && "text-[var(--color-subtle)]")}>
                    {device.id}
                  </span>
                  {!device.online && !device.disabled ? (
                    <button
                      onClick={(event) => {
                        event.stopPropagation();
                        connect.mutate(device.id);
                      }}
                      disabled={connect.isPending}
                      className="shrink-0 cursor-pointer rounded-full border border-[var(--color-accent)]/40 px-1.5 py-0.5 text-[10px] text-[var(--color-accent)] transition-colors hover:bg-[var(--color-accent-soft)]"
                    >
                      Connect
                    </button>
                  ) : null}
                </div>
                <span className="truncate text-sm text-[var(--color-muted)] max-md:hidden">
                  {device.model ?? "Android device"}
                </span>
                <Badge tone={device.type === "wireless" ? "accent" : "default"}>
                  {device.type === "wireless" ? <Wifi size={10} /> : device.type === "usb" ? <Cable size={10} /> : null}
                  {device.type ?? "—"}
                </Badge>
                <span className="truncate font-mono text-xs text-[var(--color-subtle)] max-md:hidden">
                  {device.ip ? `${device.ip}${device.port ? `:${device.port}` : ""}` : (device.serial ?? "—")}
                </span>
                <RowMenu
                  device={device}
                  onRename={() => {
                    setRenameTarget(device);
                    setRenameValue(device.id);
                  }}
                  onRemove={() => setRemoveTarget(device)}
                  onToggle={() => update.mutate({ id: device.id, patch: { disabled: !device.disabled } })}
                />
              </div>
            ))}
          </div>
        </Card>
      ) : (
        <div className="grid grid-cols-2 gap-x-4 gap-y-6 sm:grid-cols-3 lg:grid-cols-4 2xl:grid-cols-5">
          {devices.map((device) => (
            <div key={device.id} className="flex flex-col items-center gap-2">
              <button
                onClick={() => openDevice(device.id)}
                className="w-full cursor-pointer transition hover:opacity-90"
                aria-label={`Open ${device.id}`}
              >
                <PhoneFrame power slim maxWidth={150}>
                  <div className="flex h-full w-full flex-col items-center justify-center gap-1.5 bg-gradient-to-b from-[var(--color-elevated)] to-[var(--color-surface)] px-2 text-center">
                    <StatusDot online={device.online} disabled={device.disabled} />
                    <span className="w-full truncate text-xs font-medium">{device.id}</span>
                    <span className="w-full truncate text-[10px] text-[var(--color-muted)]">
                      {device.model ?? "Android device"}
                    </span>
                    <Badge>{device.type ?? "—"}</Badge>
                  </div>
                </PhoneFrame>
              </button>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => {
                  setRenameTarget(device);
                  setRenameValue(device.id);
                }}
              >
                Rename
              </Button>
            </div>
          ))}
        </div>
      )}

      {update.error || connect.error ? (
        <ErrorText>{((update.error ?? connect.error) as Error).message}</ErrorText>
      ) : null}

      {renameTarget ? (
        <Modal
          title="Rename device"
          description="The name is also the key Fenox stores this device under."
          onClose={() => setRenameTarget(null)}
          footer={
            <>
              <Button variant="ghost" onClick={() => setRenameTarget(null)}>
                Cancel
              </Button>
              <Button
                type="submit"
                form="rename-device"
                disabled={update.isPending || !renameValue.trim() || renameValue.trim() === renameTarget.id}
              >
                {update.isPending ? "Saving…" : "Rename"}
              </Button>
            </>
          }
        >
          <form
            id="rename-device"
            onSubmit={(event) => {
              event.preventDefault();
              if (renameValue.trim() && renameValue.trim() !== renameTarget.id) {
                update.mutate(
                  { id: renameTarget.id, patch: { name: renameValue.trim() } },
                  { onSuccess: () => setRenameTarget(null) },
                );
              }
            }}
          >
            <Field label="Name">
              <Input autoFocus value={renameValue} onChange={(event) => setRenameValue(event.target.value)} />
            </Field>
            <ErrorText>{(update.error as Error | null)?.message}</ErrorText>
          </form>
        </Modal>
      ) : null}

      {removeTarget ? (
        <Modal
          title="Remove device"
          onClose={() => setRemoveTarget(null)}
          footer={
            <>
              <Button variant="ghost" onClick={() => setRemoveTarget(null)}>
                Cancel
              </Button>
              <Button
                variant="danger"
                disabled={remove.isPending}
                onClick={() => remove.mutate(removeTarget.id, { onSuccess: () => setRemoveTarget(null) })}
              >
                {remove.isPending ? "Removing…" : "Remove"}
              </Button>
            </>
          }
        >
          <p className="text-sm text-[var(--color-muted)]">
            Remove <span className="font-medium text-[var(--color-text)]">{removeTarget.id}</span> from Fenox? The phone
            is not touched — you can add it again at any time.
          </p>
        </Modal>
      ) : null}
    </div>
  );
}
