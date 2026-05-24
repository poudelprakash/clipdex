import { Link, useParams } from "react-router-dom";
import { useGenerateQuestions, useGuest } from "../hooks/api";

export function GuestPage() {
  const { guestId } = useParams<{ guestId: string }>();
  const { data, isLoading, error } = useGuest(guestId);
  const gen = useGenerateQuestions(guestId);

  if (isLoading) return <p className="p-8 text-zinc-500">loading…</p>;
  if (error)
    return <p className="p-8 text-red-600">failed: {String(error)}</p>;
  if (!data) return null;

  return (
    <main className="mx-auto max-w-3xl p-8">
      <nav className="mb-4 text-sm text-zinc-700">
        <Link className="underline" to="/">
          ← home
        </Link>
      </nav>

      <h1 className="text-2xl font-semibold text-zinc-900">
        {data.canonical_name}
      </h1>
      <p className="mt-1 text-sm text-zinc-500">
        {data.appearances.length} appearance
        {data.appearances.length === 1 ? "" : "s"}
      </p>

      <section className="mt-6">
        <h2 className="mb-2 text-sm font-medium uppercase tracking-wide text-zinc-500">
          Appearances
        </h2>
        <ul className="space-y-1 text-sm">
          {data.appearances.map((a) => (
            <li key={`${a.video_id}-${a.alias_name}`}>
              <a
                className="underline text-zinc-800"
                href={a.youtube_url}
                target="_blank"
                rel="noreferrer"
              >
                {a.alias_name}
              </a>{" "}
              <span className="text-zinc-500">— {a.video_id}</span>
            </li>
          ))}
        </ul>
      </section>

      {data.topics.length > 0 && (
        <section className="mt-6">
          <h2 className="mb-2 text-sm font-medium uppercase tracking-wide text-zinc-500">
            Topics
          </h2>
          <ul className="flex flex-wrap gap-2 text-xs">
            {data.topics.map((t) => (
              <li
                key={t.name}
                className="rounded-full border border-zinc-200 px-2 py-1 text-zinc-700"
              >
                {t.name}
                {t.count > 1 ? ` · ${t.count}` : ""}
              </li>
            ))}
          </ul>
        </section>
      )}

      {data.quotes.length > 0 && (
        <section className="mt-6">
          <h2 className="mb-2 text-sm font-medium uppercase tracking-wide text-zinc-500">
            Quotes
          </h2>
          <ul className="space-y-3 text-sm text-zinc-800">
            {data.quotes.map((q, i) => (
              <li key={i} className="border-l-2 border-zinc-200 pl-3 italic">
                “{q.text}”{" "}
                <a
                  className="not-italic underline text-zinc-500"
                  href={q.youtube_url}
                  target="_blank"
                  rel="noreferrer"
                >
                  source
                </a>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="mt-8 border-t border-zinc-200 pt-6">
        <button
          className="rounded-md bg-zinc-900 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
          disabled={gen.isPending}
          onClick={() => gen.mutate()}
        >
          {gen.isPending ? "generating…" : "generate questions for return episode"}
        </button>
        {gen.error && (
          <p className="mt-2 text-red-600 text-sm">{String(gen.error)}</p>
        )}
        {gen.data && (
          <ol className="mt-4 list-decimal space-y-2 pl-5 text-sm text-zinc-800">
            {gen.data.questions.map((q, i) => (
              <li key={i} title={q.rationale}>
                {q.text}
                {q.grounded_in.length > 0 && (
                  <div className="mt-1 text-xs text-zinc-500">
                    grounded in:{" "}
                    {q.grounded_in.map((g, j) => (
                      <a
                        key={j}
                        className="underline"
                        href={g.youtube_url}
                        target="_blank"
                        rel="noreferrer"
                      >
                        “{g.text.slice(0, 80)}{g.text.length > 80 ? "…" : ""}”
                      </a>
                    ))}
                  </div>
                )}
              </li>
            ))}
          </ol>
        )}
      </section>
    </main>
  );
}
