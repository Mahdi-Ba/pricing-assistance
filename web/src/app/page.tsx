import Link from "next/link";

export default function Home() {
  return (
    <main className="grid flex-1 place-items-center bg-gradient-to-br from-indigo-950 via-slate-900 to-indigo-900 px-4 py-16">
      <div className="card flex w-full max-w-xl flex-col gap-5 p-8 shadow-2xl">
        <span aria-hidden className="grid size-12 place-items-center rounded-2xl bg-gradient-to-br from-indigo-500 to-violet-500 text-2xl font-bold text-white shadow-lg">
          ق
        </span>
        <h1 className="page-title">دستیار کارشناس قیمت‌گذاری</h1>
        <p className="leading-7 text-slate-600">
          صف تصمیم‌های قیمت، شواهد بازار و ثبت تصمیم کارشناس. این سامانه هیچ قیمتی را در فروشگاه تغییر
          نمی‌دهد.
        </p>
        <Link href="/queue" className="btn btn-primary self-start">
          ورود به صف بررسی
        </Link>
      </div>
    </main>
  );
}
