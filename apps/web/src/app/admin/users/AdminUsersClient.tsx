"use client";

import { useCallback, useEffect, useState } from "react";

type AdminUser = {
  email: string;
  status: "pending" | "approved" | "denied";
  requested_at: string;
  decided_at: string | null;
  decided_by: string | null;
};

type UsersData = {
  masters: string[];
  you: string;
  is_master: boolean;
  users: AdminUser[];
};

const STATUS_STYLE: Record<string, string> = {
  pending: "border-amber-400/40 bg-amber-500/15 text-amber-200",
  approved: "border-emerald-400/40 bg-emerald-500/15 text-emerald-200",
  denied: "border-rose-400/40 bg-rose-500/15 text-rose-200",
};

export default function AdminUsersClient() {
  const [data, setData] = useState<UsersData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const r = await fetch("/api/admin/users", { cache: "no-store" });
      if (r.status === 403) {
        setError("마스터 전용 페이지입니다. (승인/거부 권한은 마스터 계정만)");
        setData(null);
        return;
      }
      if (!r.ok) {
        setError("목록을 불러오지 못했습니다.");
        return;
      }
      setError(null);
      setData(await r.json());
    } catch {
      setError("서버 연결 실패.");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function act(email: string, action: "approve" | "deny" | "revoke") {
    setBusy(email + action);
    try {
      const r = await fetch(`/api/admin/users/${action}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email }),
      });
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        setError(d?.detail ?? `${action} 실패`);
      }
      await load();
    } finally {
      setBusy(null);
    }
  }

  if (error && !data) {
    return (
      <div className="rounded-2xl border border-rose-400/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-100">
        {error}
      </div>
    );
  }
  if (!data) {
    return <p className="text-sm text-slate-400">불러오는 중…</p>;
  }

  const pending = data.users.filter((u) => u.status === "pending");
  const others = data.users.filter((u) => u.status !== "pending");
  const canAct = data.is_master;

  return (
    <div className="space-y-6">
      {error ? (
        <div className="rounded-2xl border border-rose-400/30 bg-rose-500/10 px-4 py-2 text-sm text-rose-100">
          {error}
        </div>
      ) : null}

      <section className="rounded-3xl border border-white/10 bg-white/5 p-6 backdrop-blur">
        <h2 className="text-lg font-semibold text-white">마스터 계정</h2>
        <p className="mt-1 text-xs text-slate-400">
          env(SCAMGUARDIAN_MASTER_EMAILS) 로 관리 · 항상 허용 · 승인/거부 권한 보유
        </p>
        <div className="mt-3 flex flex-wrap gap-2">
          {data.masters.map((m) => (
            <span key={m} className="rounded-xl border border-cyan-400/40 bg-cyan-500/15 px-3 py-1 text-xs text-cyan-200">
              ★ {m}{m === data.you ? " (나)" : ""}
            </span>
          ))}
        </div>
        {!canAct ? (
          <p className="mt-3 text-xs text-amber-300">
            ⚠️ 현재 계정({data.you})은 마스터가 아니라 승인/거부 버튼이 비활성입니다.
          </p>
        ) : null}
      </section>

      <section className="rounded-3xl border border-white/10 bg-white/5 p-6 backdrop-blur">
        <h2 className="text-lg font-semibold text-white">
          승인 대기 <span className="text-amber-300">{pending.length}</span>
        </h2>
        {pending.length === 0 ? (
          <p className="mt-2 text-sm text-slate-500">대기 중인 요청 없음</p>
        ) : (
          <ul className="mt-3 space-y-2">
            {pending.map((u) => (
              <li key={u.email} className="flex items-center justify-between gap-3 rounded-2xl border border-white/10 bg-black/20 px-4 py-2">
                <div>
                  <div className="text-sm text-slate-100">{u.email}</div>
                  <div className="text-xs text-slate-500">요청: {u.requested_at?.slice(0, 19).replace("T", " ")}</div>
                </div>
                {canAct ? (
                  <div className="flex gap-2">
                    <button
                      onClick={() => act(u.email, "approve")}
                      disabled={!!busy}
                      className="rounded-xl bg-emerald-300 px-3 py-1.5 text-xs font-semibold text-slate-950 hover:bg-emerald-200 disabled:opacity-40"
                    >
                      승인
                    </button>
                    <button
                      onClick={() => act(u.email, "deny")}
                      disabled={!!busy}
                      className="rounded-xl border border-rose-400/40 bg-rose-500/10 px-3 py-1.5 text-xs font-semibold text-rose-200 hover:bg-rose-500/20 disabled:opacity-40"
                    >
                      거부
                    </button>
                  </div>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="rounded-3xl border border-white/10 bg-white/5 p-6 backdrop-blur">
        <h2 className="text-lg font-semibold text-white">승인됨 / 거부됨</h2>
        {others.length === 0 ? (
          <p className="mt-2 text-sm text-slate-500">없음</p>
        ) : (
          <ul className="mt-3 space-y-2">
            {others.map((u) => (
              <li key={u.email} className="flex items-center justify-between gap-3 rounded-2xl border border-white/10 bg-black/20 px-4 py-2">
                <div className="flex items-center gap-3">
                  <span className={`rounded-lg border px-2 py-0.5 text-xs font-semibold ${STATUS_STYLE[u.status]}`}>
                    {u.status}
                  </span>
                  <div>
                    <div className="text-sm text-slate-100">{u.email}</div>
                    <div className="text-xs text-slate-500">
                      {u.decided_by ? `결정: ${u.decided_by}` : ""}
                    </div>
                  </div>
                </div>
                {canAct ? (
                  <div className="flex gap-2">
                    {u.status !== "approved" ? (
                      <button
                        onClick={() => act(u.email, "approve")}
                        disabled={!!busy}
                        className="rounded-xl bg-emerald-300 px-3 py-1.5 text-xs font-semibold text-slate-950 hover:bg-emerald-200 disabled:opacity-40"
                      >
                        승인
                      </button>
                    ) : (
                      <button
                        onClick={() => act(u.email, "revoke")}
                        disabled={!!busy}
                        className="rounded-xl border border-rose-400/40 bg-rose-500/10 px-3 py-1.5 text-xs font-semibold text-rose-200 hover:bg-rose-500/20 disabled:opacity-40"
                      >
                        취소
                      </button>
                    )}
                  </div>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
