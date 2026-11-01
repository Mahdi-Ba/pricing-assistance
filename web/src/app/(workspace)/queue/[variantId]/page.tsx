import { DetailView } from "./detail-view";

export default async function DetailPage({ params }: PageProps<"/queue/[variantId]">) {
  const { variantId } = await params;
  return <DetailView variantId={variantId} />;
}
