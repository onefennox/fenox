import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { keys, mirrorStatus, sendInput } from "@/api/queries";
import type { Device } from "@/api/types";
import { MirrorStream, type MirrorPhase } from "@/components/MirrorStream";
import { PhoneFrame } from "@/components/PhoneFrame";
import { Button, Card, ErrorText, Skeleton } from "@/components/ui";

export function MirrorPanel({ device }: { device: Device }) {
  const status = useQuery({ queryKey: [...keys.info(device.id), "mirror"], queryFn: () => mirrorStatus(device.id) });
  const [phase, setPhase] = useState<MirrorPhase>("connecting");
  const [error, setError] = useState("");
  const [aspect, setAspect] = useState(9 / 19.5);

  if (!device.online) {
    return <Card className="p-6 text-sm text-[var(--color-muted)]">The device is offline.</Card>;
  }
  if (status.isLoading) {
    return (
      <Card className="space-y-3 p-4">
        <Skeleton className="h-4 w-48" />
        <Skeleton className="h-64 w-full" />
      </Card>
    );
  }
  if (status.data && !status.data.available) {
    return (
      <Card className="p-6 text-sm text-[var(--color-warning)]">
        Mirroring is unavailable: {status.data.reason}. Install adb and reload.
      </Card>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <span className={`text-sm ${phase === "live" ? "text-[var(--color-success)]" : "text-[var(--color-muted)]"}`}>
          {phase === "live" ? "Live" : phase === "error" ? "Unavailable" : "Connecting…"}
        </span>
        <span className="text-xs text-[var(--color-muted)]">scrcpy server {status.data?.server_version}</span>
        <div className="ml-auto flex gap-1">
          <Button variant="ghost" onClick={() => sendInput(device.id, { type: "key", key: "BACK" })}>
            Back
          </Button>
          <Button variant="ghost" onClick={() => sendInput(device.id, { type: "key", key: "HOME" })}>
            Home
          </Button>
          <Button variant="ghost" onClick={() => sendInput(device.id, { type: "key", key: "APP_SWITCH" })}>
            Recents
          </Button>
        </div>
      </div>
      <ErrorText>{error}</ErrorText>

      <Card className="grid place-items-center p-6">
        <PhoneFrame power aspect={aspect} maxWidth={300}>
          <MirrorStream
            deviceId={device.id}
            onPhaseChange={setPhase}
            onError={setError}
            onSizeChange={(width, height) => setAspect(width / height)}
          />
        </PhoneFrame>
      </Card>
      <p className="text-xs text-[var(--color-muted)]">
        Tap and swipe the screen to control the phone; input is sent through the device actions.
      </p>
    </div>
  );
}
