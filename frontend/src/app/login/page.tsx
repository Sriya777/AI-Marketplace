"use client";
import { useState } from "react";
import { useSession } from "@/lib/session";
import { Alert, Button, Field, inputCls, useAction } from "@/components/ui";

export default function LoginPage() {
  const { login, register } = useSession();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState("developer");
  const { busy, error, run } = useAction();

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    run(() => (mode === "login" ? login(username, password) : register(username, password, role)));
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-900 p-6">
      <div className="w-full max-w-md rounded-2xl border border-slate-800 bg-white p-8 shadow-2xl">
        <div className="mb-6">
          <div className="flex items-center gap-2 mb-2">
            <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-indigo-600 text-xs font-bold text-white">
              AI
            </div>
            <span className="text-xs font-bold uppercase tracking-wider text-indigo-600">Secure Registry</span>
          </div>
          <h1 className="text-2xl font-bold tracking-tight text-slate-900">Decentralized AI Model Marketplace</h1>
        </div>

        <div className="grid grid-cols-2 rounded-lg bg-slate-100 p-1 text-sm font-semibold">
          {(["login", "register"] as const).map((m) => (
            <button
              key={m}
              onClick={() => setMode(m)}
              className={`rounded-md py-2 transition ${
                mode === m
                  ? "bg-white text-slate-900 shadow-xs"
                  : "text-slate-600 hover:text-slate-900"
              }`}
            >
              {m === "login" ? "Sign In" : "Create Account"}
            </button>
          ))}
        </div>

        <form onSubmit={submit} className="mt-6 space-y-4">
          <Field label="Username">
            <input
              className={inputCls}
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoComplete="username"
              placeholder="Enter username"
              required
            />
          </Field>

          <Field
            label="Password"
            hint={mode === "register" ? "Minimum 8 characters. Used to encrypt your private key." : undefined}
          >
            <input
              type="password"
              className={inputCls}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete={mode === "login" ? "current-password" : "new-password"}
              placeholder="Enter password"
              required
            />
          </Field>

          {mode === "register" && (
            <Field label="Account Role">
              <select className={inputCls} value={role} onChange={(e) => setRole(e.target.value)}>
                <option value="developer">Developer — Train, Protect & Publish</option>
                <option value="buyer">Buyer — Verify & Download</option>
              </select>
            </Field>
          )}

          {error && <Alert>{error}</Alert>}

          <Button type="submit" busy={busy} className="w-full py-2.5 text-base">
            {mode === "login" ? "Sign In" : "Register Account"}
          </Button>
        </form>
      </div>
    </div>
  );
}
