import Link from "next/link";

export default function NotFound() {
  return (
    <main className="min-h-dvh grid place-items-center px-6">
      <div className="text-center">
        <p className="num text-5xl font-semibold text-silver-2">404</p>
        <h1 className="mt-3 text-xl font-semibold">This page doesn&apos;t exist</h1>
        <p className="mt-1 text-sm text-muted">Check the link, or go back to your dashboard.</p>
        <Link href="/" className="mt-5 inline-block text-sm text-violet-deep hover:underline">Go to dashboard</Link>
      </div>
    </main>
  );
}
