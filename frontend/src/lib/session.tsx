"use client";
import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { api, Json, tokenStore } from "./api";

type Session = {
  user: Json | null;
  ready: boolean;
  activeModelId: string;
  setActiveModelId: (id: string) => void;
  login: (username: string, password: string) => Promise<void>;
  register: (username: string, password: string, role: string) => Promise<void>;
  logout: () => Promise<void>;
  refreshUser: () => Promise<void>;
};

const Ctx = createContext<Session>(null as unknown as Session);
export const useSession = () => useContext(Ctx);
const MODEL_KEY = "aimkt.activeModel";

export function SessionProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<Json | null>(null);
  const [ready, setReady] = useState(false);
  const [activeModelId, setActive] = useState("");

  const refreshUser = useCallback(async () => {
    if (!tokenStore.get()) { setUser(null); return; }
    try { setUser(await api.get("/auth/me")); } catch { tokenStore.clear(); setUser(null); }
  }, []);

  useEffect(() => {
    setActive(localStorage.getItem(MODEL_KEY) || "");
    refreshUser().finally(() => setReady(true));
  }, [refreshUser]);

  const setActiveModelId = (id: string) => { setActive(id); localStorage.setItem(MODEL_KEY, id); };

  const login = async (username: string, password: string) => {
    const r = await api.post("/auth/login", { username, password });
    tokenStore.set(r.token);
    await refreshUser();
  };
  const register = async (username: string, password: string, role: string) => {
    await api.post("/auth/register", { username, password, role });
    await login(username, password);
  };
  const logout = async () => {
    try { await api.post("/auth/logout"); } catch { /* token may already be invalid */ }
    tokenStore.clear(); setUser(null); setActiveModelId("");
  };

  return (
    <Ctx.Provider value={{ user, ready, activeModelId, setActiveModelId, login, register, logout, refreshUser }}>
      {children}
    </Ctx.Provider>
  );
}
