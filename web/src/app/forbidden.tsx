import Link from "next/link";

export default function Forbidden() {
  return (
    <main className="grid flex-1 place-items-center px-4 py-16">
      <div className="card flex w-full max-w-md flex-col gap-4 p-8 text-center">
        <span aria-hidden className="mx-auto grid size-12 place-items-center rounded-full bg-rose-50 text-xl text-rose-600">
          ⊘
        </span>
        <h1 className="page-title">دسترسی ندارید</h1>
        <p className="text-slate-600">این بخش فقط برای مدیران است.</p>
        <Link href="/queue" className="btn btn-secondary self-center">
          بازگشت به صف بررسی
        </Link>
      </div>
    </main>
  );
}
