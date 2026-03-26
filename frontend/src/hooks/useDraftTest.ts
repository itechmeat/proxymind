import { useCallback, useState } from "react";
import { useToast } from "@/hooks/useToast";
import { testDraftSnapshot } from "@/lib/admin-api";
import { translate } from "@/lib/i18n";
import type { DraftTestResponse, RetrievalMode } from "@/types/admin";

export function useDraftTest() {
  const { pushToast } = useToast();
  const [isLoading, setIsLoading] = useState(false);
  const [result, setResult] = useState<DraftTestResponse | null>(null);

  const runDraftTest = useCallback(
    async ({
      mode,
      query,
      snapshotId,
      topN = 5,
    }: {
      mode: RetrievalMode;
      query: string;
      snapshotId: string;
      topN?: number;
    }) => {
      setIsLoading(true);
      try {
        const response = await testDraftSnapshot(snapshotId, {
          mode,
          query,
          top_n: topN,
        });
        setResult(response);
        return response;
      } catch (error) {
        const message =
          error instanceof Error
            ? error.message
            : translate("admin.draftTest.failed");
        pushToast({ message, tone: "error" });
        throw error;
      } finally {
        setIsLoading(false);
      }
    },
    [pushToast],
  );

  return {
    isLoading,
    result,
    runDraftTest,
    setResult,
  };
}
