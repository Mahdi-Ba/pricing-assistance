"use client";

import { createContext, useContext, type ReactNode } from "react";
import type { Viewer } from "@/auth";

const ViewerContext = createContext<Viewer | null>(null);

export function ViewerProvider({ viewer, children }: { viewer: Viewer; children: ReactNode }) {
  return <ViewerContext value={viewer}>{children}</ViewerContext>;
}

export function useViewer(): Viewer {
  const viewer = useContext(ViewerContext);
  if (!viewer) throw new Error("useViewer must be used inside the workspace layout");
  return viewer;
}

export function useIsAdmin(): boolean {
  return useViewer().roles.includes("admin");
}
