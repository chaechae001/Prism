import { useCallback, useEffect, useState } from "react";
import type { Story } from "../api/types";
import {
  activityKey,
  addRead,
  emptyReader,
  restoreReader,
  type ReaderState,
} from "../presentation/reading";

export function useReaderActivity() {
  const [reader, setReader] = useState<ReaderState>(() => {
    try {
      return restoreReader(localStorage.getItem(activityKey));
    } catch {
      return emptyReader();
    }
  });
  const [storageError, setStorageError] = useState(false);
  useEffect(() => {
    try {
      localStorage.setItem(activityKey, JSON.stringify(reader));
      setStorageError(false);
    } catch {
      setStorageError(true);
    }
  }, [reader]);
  const recordRead = useCallback(
    (story: Story) =>
      setReader((current) => addRead(current, story, new Date().toISOString())),
    [],
  );
  const setPreferences = useCallback(
    (displayName: string, trackingEnabled: boolean) =>
      setReader((current) => ({
        ...current,
        displayName: displayName.trim().slice(0, 20) || "독자",
        trackingEnabled,
      })),
    [],
  );
  const clearHistory = useCallback(
    () => setReader((current) => ({ ...current, events: [] })),
    [],
  );
  return { reader, storageError, recordRead, setPreferences, clearHistory };
}
