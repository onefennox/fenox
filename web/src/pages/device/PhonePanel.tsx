import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import {
  getCalls,
  getContacts,
  getConversation,
  getEvents,
  getThreads,
  keys,
  markThreadRead,
} from "@/api/queries";
import type { Device } from "@/api/types";
import { Button, Card, Spinner } from "@/components/ui";

const CALL_FILTERS = [
  { id: "", label: "All" },
  { id: "missed", label: "Missed" },
  { id: "incoming", label: "Incoming" },
  { id: "outgoing", label: "Outgoing" },
];

export function PhonePanel({ device }: { device: Device }) {
  const [section, setSection] = useState<"messages" | "calls" | "contacts" | "calendar">("messages");

  if (!device.online) {
    return <Card className="p-6 text-sm text-[var(--color-muted)]">The device is offline.</Card>;
  }

  return (
    <div className="space-y-4">
      <div className="flex gap-1">
        {(["messages", "calls", "contacts", "calendar"] as const).map((item) => (
          <button
            key={item}
            onClick={() => setSection(item)}
            className={`cursor-pointer rounded-md px-3 py-1.5 text-sm capitalize transition ${
              section === item ? "bg-[var(--color-panel-hover)] text-white" : "text-[var(--color-muted)] hover:text-white"
            }`}
          >
            {item}
          </button>
        ))}
      </div>
      {section === "messages" ? <Messages device={device} /> : null}
      {section === "calls" ? <Calls device={device} /> : null}
      {section === "contacts" ? <Contacts device={device} /> : null}
      {section === "calendar" ? <Calendar device={device} /> : null}
    </div>
  );
}

function Messages({ device }: { device: Device }) {
  const queryClient = useQueryClient();
  const [threadId, setThreadId] = useState<string | null>(null);
  const threads = useQuery({ queryKey: keys.messages(device.id), queryFn: () => getThreads(device.id) });
  const conversation = useQuery({
    queryKey: keys.conversation(device.id, threadId ?? ""),
    queryFn: () => getConversation(device.id, threadId as string),
    enabled: Boolean(threadId),
  });
  const markRead = useMutation({
    mutationFn: (id: string) => markThreadRead(device.id, id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: keys.messages(device.id) }),
  });

  if (threads.isLoading) {
    return <Spinner label="Reading messages" />;
  }
  const error = threads.error as Error | null;
  if (error) {
    return <Card className="p-4 text-sm text-amber-300">{error.message}</Card>;
  }

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
      <Card className="max-h-[560px] divide-y divide-[var(--color-border)] overflow-y-auto">
        {(threads.data?.threads ?? []).map((thread) => (
          <button
            key={thread.thread_id}
            onClick={() => setThreadId(thread.thread_id)}
            className={`block w-full cursor-pointer p-3 text-left transition ${
              threadId === thread.thread_id ? "bg-[var(--color-panel-hover)]" : "hover:bg-[var(--color-panel-hover)]"
            }`}
          >
            <div className="flex items-center justify-between">
              <span className="truncate text-sm text-white">{thread.label}</span>
              <span className="text-xs text-[var(--color-muted)]">{thread.when}</span>
            </div>
            <div className="flex items-center justify-between gap-2">
              <span className="truncate text-xs text-[var(--color-muted)]">{thread.snippet}</span>
              {thread.unread ? <span className="rounded-full bg-[var(--color-accent)] px-1.5 text-xs text-white">{thread.unread}</span> : null}
            </div>
          </button>
        ))}
        {(threads.data?.threads ?? []).length === 0 ? (
          <p className="p-4 text-sm text-[var(--color-muted)]">No conversations.</p>
        ) : null}
      </Card>

      <Card className="flex max-h-[560px] flex-col p-4">
        {threadId ? (
          <>
            <div className="mb-2 flex justify-end">
              <Button variant="ghost" onClick={() => markRead.mutate(threadId)}>
                Mark read
              </Button>
            </div>
            <div className="flex-1 space-y-2 overflow-y-auto">
              {(conversation.data?.messages ?? []).map((message) => (
                <div key={message.id} className={`max-w-[85%] rounded-lg p-2 text-sm ${message.direction === "out" ? "ml-auto bg-[var(--color-accent)]/20" : "bg-[var(--color-panel-hover)]"}`}>
                  <div className="text-white whitespace-pre-wrap">{message.body}</div>
                  <div className="mt-1 text-right text-xs text-[var(--color-muted)]">{message.when}</div>
                </div>
              ))}
            </div>
          </>
        ) : (
          <p className="text-sm text-[var(--color-muted)]">Select a conversation.</p>
        )}
      </Card>
    </div>
  );
}

function Calls({ device }: { device: Device }) {
  const [filter, setFilter] = useState("");
  const calls = useQuery({ queryKey: [...keys.calls(device.id), filter], queryFn: () => getCalls(device.id, filter || undefined) });

  return (
    <div className="space-y-3">
      <div className="flex gap-1">
        {CALL_FILTERS.map((item) => (
          <button
            key={item.id}
            onClick={() => setFilter(item.id)}
            className={`cursor-pointer rounded-md px-3 py-1 text-sm transition ${
              filter === item.id ? "bg-[var(--color-panel-hover)] text-white" : "text-[var(--color-muted)] hover:text-white"
            }`}
          >
            {item.label}
          </button>
        ))}
      </div>
      {calls.isLoading ? (
        <Spinner label="Reading the call log" />
      ) : calls.error ? (
        <Card className="p-4 text-sm text-amber-300">{(calls.error as Error).message}</Card>
      ) : (
        <Card className="max-h-[520px] divide-y divide-[var(--color-border)] overflow-y-auto">
          {(calls.data?.calls ?? []).map((call) => (
            <div key={call.id} className="flex items-center gap-3 p-3 text-sm">
              <span className="w-20 text-xs text-[var(--color-muted)]">{call.kind}</span>
              <span className="min-w-0 flex-1 truncate text-white">{call.label}</span>
              <span className="text-xs text-[var(--color-muted)]">{call.duration}</span>
              <span className="text-xs text-[var(--color-muted)]">{call.when}</span>
              {call.new ? <span className="h-2 w-2 rounded-full bg-[var(--color-accent)]" /> : null}
            </div>
          ))}
        </Card>
      )}
    </div>
  );
}

function Contacts({ device }: { device: Device }) {
  const [search, setSearch] = useState("");
  const contacts = useQuery({ queryKey: [...keys.contacts(device.id), search], queryFn: () => getContacts(device.id, search || undefined) });

  return (
    <div className="space-y-3">
      <input
        value={search}
        onChange={(event) => setSearch(event.target.value)}
        placeholder="Search contacts"
        className="w-full rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-2 text-sm text-white"
      />
      {contacts.isLoading ? (
        <Spinner label="Reading contacts" />
      ) : contacts.error ? (
        <Card className="p-4 text-sm text-amber-300">{(contacts.error as Error).message}</Card>
      ) : (
        <Card className="max-h-[520px] divide-y divide-[var(--color-border)] overflow-y-auto">
          {(contacts.data?.contacts ?? []).map((contact) => (
            <div key={`${contact.id}-${contact.number}`} className="flex items-center justify-between p-3 text-sm">
              <span className="text-white">{contact.name}</span>
              <span className="text-[var(--color-muted)]">{contact.number}</span>
            </div>
          ))}
        </Card>
      )}
    </div>
  );
}

function Calendar({ device }: { device: Device }) {
  const events = useQuery({ queryKey: keys.events(device.id), queryFn: () => getEvents(device.id, 14) });

  if (events.isLoading) {
    return <Spinner label="Reading the calendar" />;
  }
  if (events.error) {
    return <Card className="p-4 text-sm text-amber-300">{(events.error as Error).message}</Card>;
  }
  return (
    <Card className="max-h-[520px] divide-y divide-[var(--color-border)] overflow-y-auto">
      {(events.data?.events ?? []).map((event) => (
        <div key={event.id} className="flex items-center gap-3 p-3 text-sm">
          <span className="w-28 text-xs text-[var(--color-muted)]">{event.when}</span>
          <span className="min-w-0 flex-1 truncate text-white">{event.title}</span>
          {event.where ? <span className="text-xs text-[var(--color-muted)]">{event.where}</span> : null}
        </div>
      ))}
      {(events.data?.events ?? []).length === 0 ? (
        <p className="p-4 text-sm text-[var(--color-muted)]">No upcoming events.</p>
      ) : null}
    </Card>
  );
}
