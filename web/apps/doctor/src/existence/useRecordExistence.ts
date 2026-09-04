// The patient-search screen's state: one search at a time, and its outcome.
//
// Not the shared useApiResource: that hook loads a resource when its inputs change, and a
// search runs when a clinician presses a button. The states are also different — "nothing
// searched yet" is not "loading". What is shared is everything underneath: the client, the
// result contract and the error wording.

import { useState } from "react";

import { api } from "@/api";

import { searchRecordExistence } from "./api";
import {
  INVALID_HEALTH_ID,
  looksLikeHealthId,
  normalizeHealthId,
  outcomeFor,
  type SearchOutcome,
} from "./view";

export interface RecordExistenceSearch {
  outcome: SearchOutcome;
  /** True while a request is in flight — the form disables itself. */
  searching: boolean;
  search: (rawHealthId: string) => void;
  reset: () => void;
}

export function useRecordExistence(): RecordExistenceSearch {
  const [outcome, setOutcome] = useState<SearchOutcome>({ kind: "idle" });
  const [searching, setSearching] = useState(false);

  async function run(rawHealthId: string): Promise<void> {
    const healthId = normalizeHealthId(rawHealthId);
    // Caught before the round trip; the server still validates independently.
    if (!looksLikeHealthId(healthId)) {
      setOutcome({ kind: "error", message: INVALID_HEALTH_ID });
      return;
    }
    setSearching(true);
    setOutcome({ kind: "searching" });

    const controller = new AbortController();
    const result = await searchRecordExistence(api, healthId, controller.signal);

    setSearching(false);
    setOutcome(
      result.status === "error"
        ? { kind: "error", message: result.message }
        : outcomeFor(healthId, result.data.items),
    );
  }

  return {
    outcome,
    searching,
    search: (rawHealthId) => void run(rawHealthId),
    reset: () => setOutcome({ kind: "idle" }),
  };
}
