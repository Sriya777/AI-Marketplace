"use client";
import { useEffect, useState } from "react";
import { api, Json } from "./api";

/** Contract address + ABI come from the backend, so a redeployed contract is picked up automatically. */
export function useChainConfig() {
  const [cfg, setCfg] = useState<Json | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    api.get("/chain/config").then(setCfg).catch((e) => setError(e.message));
  }, []);
  return { cfg, error };
}
