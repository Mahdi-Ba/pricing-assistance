import { signIn } from "@/auth";

function safeCallback(value: string | string[] | undefined): string {
  const path = Array.isArray(value) ? value[0] : value;
  // only same-site relative paths, never another origin
  return path && path.startsWith("/") && !path.startsWith("//") ? path : "/queue";
}

export default async function SignInPage({ searchParams }: PageProps<"/signin">) {
  const callbackUrl = safeCallback((await searchParams).callbackUrl);
  async function login() {
    "use server";
    await signIn("keycloak", { redirectTo: callbackUrl });
  }
  return (
    <main className="grid flex-1 place-items-center bg-gradient-to-br from-indigo-950 via-slate-900 to-indigo-900 px-4 py-16">
      <div className="card flex w-full max-w-md flex-col gap-6 p-8 shadow-2xl">
        <span aria-hidden className="grid size-12 place-items-center rounded-2xl bg-gradient-to-br from-indigo-500 to-violet-500 text-2xl font-bold text-white shadow-lg">
          ق
        </span>
        <div className="flex flex-col gap-2">
          <h1 className="page-title">ورود به دستیار قیمت‌گذاری</h1>
          <p className="page-subtitle">برای ادامه با حساب سازمانی وارد شوید.</p>
        </div>
        <form action={login}>
          <button type="submit" className="btn btn-primary w-full py-2.5">
            ورود با حساب سازمانی
          </button>
        </form>
        <p className="text-xs leading-6 text-slate-500">
          این سامانه فقط پیشنهاد می‌دهد؛ هیچ قیمتی را در فروشگاه تغییر نمی‌دهد.
        </p>
      </div>
    </main>
  );
}
