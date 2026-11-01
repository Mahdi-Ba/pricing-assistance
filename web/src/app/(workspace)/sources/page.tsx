import { requireAdmin } from "@/lib/viewer";
import { SourcesView } from "./sources-view";

export default async function SourcesPage() {
  await requireAdmin("/sources");
  return <SourcesView />;
}
