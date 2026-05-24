import { useState } from "react";
import { Link } from "react-router-dom";
import { useSearch } from "../hooks/api";

export function Search() {
  const [draft, setDraft] = useState("");
  const [query, setQuery] = useState("");
  const { data, isFetching, error } = useSearch(query);

  return (
    <main className="mx-auto max-w-3xl p-8">
      <nav className="mb-4 text-sm text-zinc-700">
        <Link className="underline" to="/">
          ← home
        </Link>
      </nav>

      <h1 className="text-2xl font-semibold text-zinc-900">Search clips</h1>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          setQuery(draft);
        }}
        className="mt-4 flex gap-2"
      >
        <input
          className="flex-1 rounded-md border border-zinc-300 px-3 py-1.5"
          placeholder='e.g. "fundraising in Nepal"'
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
        />
        <button
          type="submit"
          className="rounded-md bg-zinc-900 px-3 py-1.5 text-sm font-medium text-white"
        >
          Search
        </button>
      </form>

      {error && (
        <p className="mt-4 text-red-600 text-sm">{String(error)}</p>
      )}
      {isFetching && <p className="mt-4 text-zinc-500 text-sm">searching…</p>}

      <ul className="mt-6 space-y-4">
        {(data?.results ?? []).map((c) => (
          <li
            key={`${c.video_id}-${c.seq}`}
            className="rounded-md border border-zinc-200 p-4"
          >
            <div className="text-xs text-zinc-500">
              {c.video_id} · {formatMs(c.start_ms)}–{formatMs(c.end_ms)}
            </div>
            <p className="mt-1 text-sm text-zinc-800">{c.text}</p>
            {c.rerank_rationale && (
              <p className="mt-2 text-xs italic text-zinc-500">
                {c.rerank_rationale}
              </p>
            )}
            <a
              className="mt-2 inline-block text-xs underline text-zinc-700"
              href={c.youtube_url}
              target="_blank"
              rel="noreferrer"
            >
              open on YouTube at {Math.floor(c.start_ms / 1000)}s
            </a>
          </li>
        ))}
      </ul>
      {data && data.results.length === 0 && (
        <p className="mt-4 text-zinc-500 text-sm">
          no matches{data.cached ? " (cached)" : ""}.
        </p>
      )}
    </main>
  );
}

function formatMs(ms: number): string {
  const total = Math.floor(ms / 1000);
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m}:${s.toString().padStart(2, "0")}`;
}
