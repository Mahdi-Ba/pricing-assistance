import { requireAdmin } from "@/lib/viewer";
import { SettingsView } from "./settings-view";

export default async function SettingsPage() {
  await requireAdmin("/settings");
  return <SettingsView />;
}
