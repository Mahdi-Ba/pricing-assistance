import { Suspense } from "react";
import { Loading } from "@/components/notices";
import { QueueView } from "./queue-view";

export default function QueuePage() {
  return (
    <Suspense fallback={<Loading />}>
      <QueueView />
    </Suspense>
  );
}
