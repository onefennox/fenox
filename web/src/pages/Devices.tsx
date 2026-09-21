import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { connectDevice, deleteDevice, keys, listDevices, updateDevice } from "@/api/queries";
import type { Device } from "@/api/types";
import { PhoneFrame } from "@/components/PhoneFrame";
import { useActiveDevice } from "@/hooks/useActiveDevice";
import { Badge, Button, Card, ErrorText, Field, Input, Modal, Spinner, StatusDot } from "@/components/ui";

export function DevicesPage() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const { setActiveDevice } = useActiveDevice();
  const { data, isLoading, error } = useQuery({ queryKey: keys.devices, queryFn: listDevices });

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

  if (isLoading) {
    return <Spinner label="Loading devices" />;
  }
  if (error) {
    return <p className="text-sm text-red-400">{(error as Error).message}</p>;
  }

  const devices = data?.devices ?? [];
  const pending = data?.pending ?? [];
  const unauthorized = pending.filter((item) => item.state === "unauthorized");

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold text-white">Devices</h1>
          <p className="mt-1 text-sm text-[var(--color-muted)]">
            Your phones. Select one to view its screen and manage it.
          </p>
        </div>
        <Link to="/connect">
          <Button>
            <Plus size={16} />
            Add device
          </Button>
        </Link>
      </div>

      {unauthorized.length > 0 ? (
        <Card className="border-amber-500/30 p-3 text-sm text-amber-300">
          {unauthorized.map((item) => (
            <div key={item.id}>
              {item.id} is waiting for authorization — accept the “Allow USB debugging?” prompt on the phone.
            </div>
          ))}
        </Card>
      ) : null}

      {devices.length === 0 ? (
        <Card className="p-10 text-center">
          <p className="text-sm text-[var(--color-muted)]">No devices yet.</p>
          <Link to="/connect" className="mt-3 inline-block">
            <Button>
              <Plus size={16} />
              Connect a device
            </Button>
          </Link>
        </Card>
      ) : (
        <div className="grid grid-cols-2 gap-x-4 gap-y-7 sm:grid-cols-3 lg:grid-cols-4 2xl:grid-cols-5">
          {devices.map((device) => (
            <div key={device.id} className="flex flex-col items-center gap-2">
              <button
                onClick={() => openDevice(device.id)}
                className="w-full cursor-pointer transition hover:opacity-90"
                aria-label={`Open ${device.id}`}
              >
                <PhoneFrame power slim maxWidth={150}>
                  <div className="flex h-full w-full flex-col items-center justify-center gap-1.5 bg-gradient-to-b from-[#171b25] to-[#0b0d12] px-2 text-center">
                    <StatusDot online={device.online} disabled={device.disabled} />
                    <span className="w-full truncate text-xs font-medium text-white">{device.id}</span>
                    <span className="w-full truncate text-[10px] text-[var(--color-muted)]">
                      {device.model ?? "Android device"}
                    </span>
                    <Badge>{device.type === "wireless" ? "wifi" : device.type === "usb" ? "usb" : device.type ?? "—"}</Badge>
                  </div>
                </PhoneFrame>
              </button>

              <div className="flex flex-wrap items-center justify-center gap-1">
                {!device.online && !device.disabled ? (
                  <Button variant="ghost" onClick={() => connect.mutate(device.id)} disabled={connect.isPending}>
                    Connect
                  </Button>
                ) : null}
                <Button
                  variant="ghost"
                  onClick={() => {
                    setRenameTarget(device);
                    setRenameValue(device.id);
                  }}
                >
                  Rename
                </Button>
                <Button variant="ghost" onClick={() => update.mutate({ id: device.id, patch: { disabled: !device.disabled } })}>
                  {device.disabled ? "Enable" : "Disable"}
                </Button>
                <Button variant="ghost" onClick={() => setRemoveTarget(device)}>
                  Remove
                </Button>
              </div>
            </div>
          ))}
        </div>
      )}

      {(update.error || connect.error) ? (
        <ErrorText>{((update.error ?? connect.error) as Error).message}</ErrorText>
      ) : null}

      {renameTarget ? (
        <Modal title="Rename device" onClose={() => setRenameTarget(null)}>
          <form
            className="space-y-4"
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
            <div className="flex justify-end gap-2">
              <Button type="button" variant="ghost" onClick={() => setRenameTarget(null)}>
                Cancel
              </Button>
              <Button type="submit" disabled={update.isPending}>
                Save
              </Button>
            </div>
          </form>
        </Modal>
      ) : null}

      {removeTarget ? (
        <Modal title="Remove device" onClose={() => setRemoveTarget(null)}>
          <p className="text-sm text-[var(--color-muted)]">
            Remove <span className="text-white">{removeTarget.id}</span> from Fenox? This does not unpair the phone; you can
            connect it again.
          </p>
          <div className="mt-5 flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setRemoveTarget(null)}>
              Cancel
            </Button>
            <Button
              variant="danger"
              onClick={() => remove.mutate(removeTarget.id, { onSuccess: () => setRemoveTarget(null) })}
              disabled={remove.isPending}
            >
              Remove
            </Button>
          </div>
        </Modal>
      ) : null}
    </div>
  );
}
