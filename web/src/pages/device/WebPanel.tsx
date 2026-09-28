import { ExternalLink, Globe, RotateCw } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import type { Device } from "@/api/types";
import { Button, Card, Input } from "@/components/ui";

/** Turn whatever was typed into something loadable. */
function normalise(raw: string): string {
  const value = raw.trim();
  if (!value) return "";
  if (/^https?:\/\//i.test(value)) return value;
  // Looks like a hostname rather than a search term.
  if (/^[\w.-]+\.[a-z]{2,}([/:?#]|$)/i.test(value)) return `https://${value}`;
  return `https://duckduckgo.com/?q=${encodeURIComponent(value)}`;
}

/**
 * A browser panel for the device page.
 *
 * The page is embedded in an iframe so it uses *this* browser's cookies and
 * logins rather than starting a fresh session. That is the whole point, and also
 * the limitation: a great many sites send `X-Frame-Options: DENY` or a
 * `frame-ancestors` policy and will simply refuse to load. That refusal cannot
 * be detected reliably from JavaScript, so rather than pretend, the panel says
 * so up front and offers to open the address in a real tab, where anything loads.
 */
export function WebPanel({ device }: { device: Device }) {
  const storageKey = `fenox.web.${device.id}`;
  const [input, setInput] = useState("");
  const [url, setUrl] = useState("");
  const [nonce, setNonce] = useState(0);
  const [showNotice, setShowNotice] = useState(false);
  const frame = useRef<HTMLIFrameElement>(null);

  // Remember the last address per device, so returning to the tab resumes where
  // it was rather than showing an empty box.
  useEffect(() => {
    const saved = localStorage.getItem(storageKey);
    if (saved) {
      setUrl(saved);
      setInput(saved);
    }
  }, [storageKey]);

  const go = (raw: string) => {
    const target = normalise(raw);
    if (!target) return;
    setUrl(target);
    setInput(target);
    setNonce((count) => count + 1);
    setShowNotice(true); // most sites refuse framing; say so rather than leave a blank panel
    try {
      localStorage.setItem(storageKey, target);
    } catch {
      // Private mode or a full quota: remembering is a convenience, not a requirement.
    }
  };

  return (
    <div className="space-y-3">
      <form
        className="flex gap-2"
        onSubmit={(event) => {
          event.preventDefault();
          go(input);
        }}
      >
        <Input
          value={input}
          onChange={(event) => setInput(event.target.value)}
          placeholder="example.com — or a search"
          aria-label="Address"
          spellCheck={false}
          autoComplete="off"
        />
        <Button type="submit" className="shrink-0">
          <Globe size={14} />
          Go
        </Button>
        {url ? (
          <Button
            type="button"
            variant="ghost"
            className="shrink-0"
            title="Reload"
            onClick={() => {
              setNonce((count) => count + 1);
              setShowNotice(true);
            }}
          >
            <RotateCw size={14} />
          </Button>
        ) : null}
      </form>

      {showNotice && url ? (
        <Card className="flex flex-wrap items-center gap-3 p-3 text-xs text-[var(--color-muted)]">
          <span className="min-w-0 flex-1">
            Some sites refuse to be shown inside another page. If this stays blank, open it in a real
            tab — it will work there.
          </span>
          <Button
            type="button"
            variant="secondary"
            className="shrink-0"
            onClick={() => window.open(url, "_blank", "noopener,noreferrer")}
          >
            <ExternalLink size={14} />
            Open in a tab
          </Button>
        </Card>
      ) : null}

      {url ? (
        <div className="overflow-hidden rounded-xl border border-[var(--color-border)] bg-white">
          <iframe
            // A fresh key per navigation so the frame is recreated rather than
            // relying on the browser to honour a same-URL reload.
            key={`${url}#${nonce}`}
            ref={frame}
            src={url}
            title="Web"
            className="h-[70vh] w-full border-0 bg-white"
            // Same-origin is not needed and only narrows what loads; the panel
            // never reads the document, it only displays it.
            sandbox="allow-forms allow-modals allow-popups allow-same-origin allow-scripts"
            referrerPolicy="no-referrer-when-downgrade"
          />
        </div>
      ) : (
        <Card className="p-8 text-center text-sm text-[var(--color-muted)]">
          <Globe size={20} className="mx-auto mb-3 opacity-60" />
          Type an address above to browse here, using this browser's own logins.
          <div className="mt-2 text-xs">
            Sites that block embedding — Google, most banks — will need the “open in a tab” button.
          </div>
        </Card>
      )}
    </div>
  );
}
