import { createContext, useCallback, useContext, useState, type ReactNode } from "react";

/**
 * The device currently selected in the UI. The right-hand rail follows this, so
 * selecting a phone anywhere turns the rail into that phone's live pane.
 */
interface ActiveDeviceValue {
  activeId: string | null;
  setActiveDevice: (id: string | null) => void;
}

const ActiveDeviceContext = createContext<ActiveDeviceValue>({ activeId: null, setActiveDevice: () => undefined });

const STORAGE_KEY = "fenox.activeDevice";

export function ActiveDeviceProvider({ children }: { children: ReactNode }) {
  const [activeId, setActiveId] = useState<string | null>(() => {
    try {
      return localStorage.getItem(STORAGE_KEY);
    } catch {
      return null;
    }
  });

  const setActiveDevice = useCallback((id: string | null) => {
    setActiveId(id);
    try {
      if (id) {
        localStorage.setItem(STORAGE_KEY, id);
      } else {
        localStorage.removeItem(STORAGE_KEY);
      }
    } catch {
      // Storage can be unavailable (private mode); selection still works in memory.
    }
  }, []);

  return <ActiveDeviceContext.Provider value={{ activeId, setActiveDevice }}>{children}</ActiveDeviceContext.Provider>;
}

export function useActiveDevice(): ActiveDeviceValue {
  return useContext(ActiveDeviceContext);
}
