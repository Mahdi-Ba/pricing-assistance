/** Server-side access to the signed-in user (the Data Access Layer for pages and layouts). */
import { forbidden, redirect } from "next/navigation";
import { auth, type Viewer } from "@/auth";

export async function currentViewer(): Promise<Viewer | null> {
  const session = await auth();
  if (!session?.viewer || session.error) return null;
  return session.viewer;
}

export async function requireViewer(path = "/queue"): Promise<Viewer> {
  const viewer = await currentViewer();
  if (!viewer) redirect(`/signin?callbackUrl=${encodeURIComponent(path)}`);
  return viewer;
}

export async function requireAdmin(path: string): Promise<Viewer> {
  const viewer = await requireViewer(path);
  if (!viewer.roles.includes("admin")) forbidden();
  return viewer;
}
