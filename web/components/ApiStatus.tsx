"use client";

import { useQuery } from "@tanstack/react-query";

import { getHealth } from "@/lib/api/client";

/**
 * Small readiness badge for the Phase 0 skeleton.
 *
 * Copy follows Appendix D.2: one short sentence, plain words, no error codes.
 */
export function ApiStatus() {
  const { data, isPending, isError } = useQuery({
    queryKey: ["health"],
    queryFn: getHealth,
  });

  if (isPending) {
    return <p className="text-body">Checking the server…</p>;
  }

  if (isError) {
    return (
      <p className="text-body" role="status">
        The server is not answering yet.
      </p>
    );
  }

  return (
    <p className="text-body" role="status">
      The server is ready. {data?.status === "ok" ? "" : ""}
    </p>
  );
}
