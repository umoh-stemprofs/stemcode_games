import { ApiStatus } from "@/components/ApiStatus";

/**
 * Phase 0 landing page.
 *
 * It exists to prove the skeleton runs end to end: Next renders this, and the
 * badge calls `/api/health` through the dev rewrite. Games arrive in Phase 4.
 */
export default function Home() {
  return (
    <main className="mx-auto flex min-h-screen max-w-2xl flex-col justify-center gap-6 p-6">
      <h1 className="text-heading font-semibold">STEM Games</h1>

      <p className="text-body">
        This is the skeleton. There are no games here yet.
      </p>

      <div className="rounded-lg border border-border bg-surface p-6">
        <ApiStatus />
      </div>

      <p className="text-body-min text-ink-muted">
        Phase 0 of the build plan: the API, the website, and the database are
        connected.
      </p>
    </main>
  );
}
