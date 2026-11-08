import type { ReactNode } from "react";
import type { UseQueryResult } from "@tanstack/react-query";
import { ApiError } from "../api/client";
import { PageSkeleton } from "./Skeleton";
import { ErrorState } from "./States";

interface QueryBoundaryProps<T> {
  query: UseQueryResult<T>;
  children: (data: T) => ReactNode;
  skeleton?: ReactNode;
}

export function QueryBoundary<T>({ query, children, skeleton }: QueryBoundaryProps<T>) {
  if (query.isPending) return <>{skeleton ?? <PageSkeleton />}</>;
  if (query.isError) {
    const error = query.error;
    const isUnavailable = error instanceof ApiError && error.status === 503;
    return (
      <ErrorState
        title={isUnavailable ? "Demo data is not built yet" : "Could not load this page"}
        text={error.message}
        action={
          <button type="button" className="btn" onClick={() => void query.refetch()}>
            Try again
          </button>
        }
      />
    );
  }
  return <>{children(query.data)}</>;
}
