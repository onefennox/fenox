import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { keys, setupOwner } from "@/api/queries";
import { Button, Card, ErrorText, Field, Input } from "@/components/ui";

export function SetupPage() {
  const queryClient = useQueryClient();
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");

  const create = useMutation({
    mutationFn: () => setupOwner(password),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: keys.auth }),
  });

  const validation =
    password.length < 6
      ? "Password must be at least 6 characters."
      : password !== confirm
        ? "Passwords do not match."
        : "";

  const submit = () => {
    if (!validation) {
      create.mutate();
    }
  };

  return (
    <div className="grid min-h-full place-items-center p-6">
      <Card className="w-full max-w-md p-8">
        <h1 className="text-xl font-semibold text-white">Set up Fenox</h1>
        <p className="mt-2 text-sm text-[var(--color-muted)]">
          Choose the password that protects this installation. There is a single owner account; you will use it to sign in.
        </p>
        <form
          className="mt-6 space-y-4"
          onSubmit={(event) => {
            event.preventDefault();
            submit();
          }}
        >
          <Field label="Owner password">
            <Input
              type="password"
              autoFocus
              autoComplete="new-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
          </Field>
          <Field label="Confirm password">
            <Input
              type="password"
              autoComplete="new-password"
              value={confirm}
              onChange={(event) => setConfirm(event.target.value)}
            />
          </Field>
          <ErrorText>{validation || (create.error as Error | null)?.message}</ErrorText>
          <Button type="submit" className="w-full justify-center" disabled={create.isPending || Boolean(validation)}>
            {create.isPending ? "Setting up…" : "Set password"}
          </Button>
        </form>
      </Card>
    </div>
  );
}
