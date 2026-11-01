import { requireAdmin } from "@/lib/viewer";
import { RulesView } from "./rules-view";

export default async function RulesPage() {
  await requireAdmin("/rules");
  return <RulesView />;
}
