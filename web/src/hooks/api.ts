/**
 * TanStack Query hooks, one per endpoint. All response shapes are typed off
 * `generated/schema.ts` so a backend rename breaks the frontend compile.
 */
import { useQuery, useMutation } from "@tanstack/react-query";
import type {
  GuestDetail,
  GuestSummary,
  QuestionSet,
  SearchResponse,
} from "../generated/schema";

async function fetchJson<T>(url: string): Promise<T> {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${url} -> ${r.status}`);
  return (await r.json()) as T;
}

export function useGuests(limit = 12) {
  return useQuery<GuestSummary[]>({
    queryKey: ["guests", limit],
    queryFn: () => fetchJson<GuestSummary[]>(`/api/guests?limit=${limit}`),
  });
}

export function useGuest(guestId: string | undefined) {
  return useQuery<GuestDetail>({
    enabled: !!guestId,
    queryKey: ["guest", guestId],
    queryFn: () => fetchJson<GuestDetail>(`/api/guests/${guestId}`),
  });
}

export function useSearch(query: string) {
  return useQuery<SearchResponse>({
    enabled: query.trim().length > 0,
    queryKey: ["search", query],
    queryFn: () =>
      fetchJson<SearchResponse>(
        `/api/search?q=${encodeURIComponent(query)}&n=10`,
      ),
  });
}

export function useGenerateQuestions(guestId: string | undefined) {
  return useMutation<QuestionSet, Error, void>({
    mutationFn: async () => {
      if (!guestId) throw new Error("guestId required");
      const r = await fetch(`/api/guests/${guestId}/questions`, {
        method: "POST",
      });
      if (!r.ok) throw new Error(`questions -> ${r.status}`);
      return (await r.json()) as QuestionSet;
    },
  });
}
