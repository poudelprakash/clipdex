import { Link } from "react-router-dom";
import { useGuests } from "../hooks/api";

export function Home() {
  const { data, isLoading, error } = useGuests(12);
  return (
    <main className="mx-auto max-w-3xl p-8">
      <header className="mb-8">
        <h1 className="text-3xl font-semibold">clipdex</h1>
        <p className="mt-2 text-zinc-600">
          Local AI podcast index — guests, topics, clips.
        </p>
        <nav className="mt-4 text-sm text-zinc-700">
          <Link className="underline" to="/search">
            search
          </Link>
        </nav>
      </header>

      <section>
        <h2 className="mb-3 text-sm font-medium uppercase tracking-wide text-zinc-500">
          Popular guests
        </h2>
        {isLoading && <p className="text-zinc-500">loading…</p>}
        {error && (
          <p className="text-red-600">failed to load guests: {String(error)}</p>
        )}
        <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          {(data ?? []).map((g) => (
            <li
              key={g.id}
              className="rounded-md border border-zinc-200 p-3 hover:bg-zinc-50"
            >
              <Link to={`/guests/${g.id}`} className="block">
                <div className="font-medium text-zinc-900">
                  {g.canonical_name}
                </div>
                <div className="mt-1 text-xs text-zinc-500">
                  {g.appearance_count} appearance
                  {g.appearance_count === 1 ? "" : "s"}
                </div>
              </Link>
            </li>
          ))}
        </ul>
      </section>
    </main>
  );
}
