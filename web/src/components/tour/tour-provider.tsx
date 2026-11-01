"use client";

import { usePathname, useRouter } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { useIsAdmin } from "@/components/viewer-context";
import { TOURS, tourForPath, type TourId, type TourStep } from "./tour-content";
import { TourOverlay } from "./tour-overlay";

/** Per-browser conveniences only; the tour works the same when storage is unavailable. */
const SEEN_KEY = (id: TourId) => `pa-tour-seen:${id}:v1`;
const AUTOSTART_KEY = "pa-tours:autostart"; // "off" disables automatic first-visit tours

function read(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function write(key: string, value: string): void {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    // private mode or blocked storage: the tour simply may show again
  }
}

/** `path` ties the tour to the page it was started on; navigating away hides it. */
type TourState = { id: TourId; index: number; path: string } | null;

type TourApi = {
  start: (id: TourId) => void;
  active: TourId | null;
};

const TourContext = createContext<TourApi>({ start: () => undefined, active: null });

export function useTour(): TourApi {
  return useContext(TourContext);
}

export function TourProvider({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const isAdmin = useIsAdmin();
  const [state, setState] = useState<TourState>(null);

  const stepsFor = useCallback(
    (id: TourId): TourStep[] => TOURS[id].steps.filter((s) => isAdmin || !s.adminOnly),
    [isAdmin],
  );

  const start = useCallback((id: TourId) => setState({ id, index: 0, path: window.location.pathname }), []);

  const close = useCallback(() => {
    setState((current) => {
      if (current) write(SEEN_KEY(current.id), "1");
      return null;
    });
  }, []);

  // `?tour=<id>` (from the help page) starts that tour; otherwise a page's tour starts once, on the first visit
  useEffect(() => {
    const id = tourForPath(pathname);
    const requested = new URLSearchParams(window.location.search).get("tour");
    let timer: ReturnType<typeof setTimeout> | undefined;
    if (requested && requested === id) {
      const url = new URL(window.location.href);
      url.searchParams.delete("tour");
      router.replace(`${url.pathname}${url.search}`, { scroll: false });
      timer = setTimeout(() => start(id), 300);
    } else if (id && read(AUTOSTART_KEY) !== "off" && !read(SEEN_KEY(id)) && (isAdmin || !TOURS[id].adminOnly)) {
      timer = setTimeout(() => start(id), 600); // let the page render its first content
    }
    return () => clearTimeout(timer);
  }, [pathname, isAdmin, router, start]);

  const visible = state && state.path === pathname ? state : null;
  const api = useMemo(() => ({ start, active: visible?.id ?? null }), [start, visible?.id]);
  const steps = visible ? stepsFor(visible.id) : [];
  return (
    <TourContext.Provider value={api}>
      {children}
      {visible && steps.length > 0 && (
        <TourOverlay
          tourTitle={TOURS[visible.id].title}
          steps={steps}
          index={Math.min(visible.index, steps.length - 1)}
          onIndex={(index) => setState({ ...visible, index })}
          onClose={close}
        />
      )}
    </TourContext.Provider>
  );
}
