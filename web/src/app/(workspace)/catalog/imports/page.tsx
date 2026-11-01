import { requireAdmin } from "@/lib/viewer";
import { ImportsView } from "./imports-view";

export default async function ImportsPage() {
  await requireAdmin("/catalog/imports");
  return <ImportsView />;
}
