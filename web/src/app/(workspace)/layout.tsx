import { Nav } from "@/components/nav";
import { TourProvider } from "@/components/tour/tour-provider";
import { ViewerProvider } from "@/components/viewer-context";
import { requireViewer } from "@/lib/viewer";

export default async function WorkspaceLayout({ children }: LayoutProps<"/">) {
  const viewer = await requireViewer();
  return (
    <ViewerProvider viewer={viewer}>
      <TourProvider>
        <div className="flex min-h-screen flex-1 flex-col md:flex-row">
          <Nav viewer={viewer} />
          <main className="min-w-0 flex-1">
            <div className="mx-auto w-full max-w-7xl px-4 py-6 md:px-8 md:py-8">{children}</div>
          </main>
        </div>
      </TourProvider>
    </ViewerProvider>
  );
}
