"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  LineChart,
  Line,
  CartesianGrid,
} from "recharts";

interface DashboardStats {
  total_runs: number;
  labeled_runs: number;
  unlabeled_runs: number;
  in_progress_runs: number;
  scam_type_distribution: { name: string; count: number }[];
  risk_level_distribution: { name: string; count: number }[];
  daily_runs: { date: string; count: number }[];
  labeled_by_type: { name: string; count: number }[];
}

export default function StatsPage() {
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/admin/stats")
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then(setStats)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="p-8 text-gray-500">로딩 중...</div>;
  if (error) return <div className="p-8 text-red-500">오류: {error}</div>;
  if (!stats) return null;

  const labelingRate =
    stats.total_runs > 0
      ? ((stats.labeled_runs / stats.total_runs) * 100).toFixed(1)
      : "0.0";

  return (
    <div className="min-h-screen bg-gray-50 p-6">
      <div className="max-w-6xl mx-auto space-y-6">
        {/* 헤더 */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">DB 대시보드</h1>
            <p className="text-sm text-gray-500 mt-1">분석 데이터 현황</p>
          </div>
          <div className="flex gap-3">
            <Link
              href="/admin/browse"
              className="px-4 py-2 text-sm bg-white border border-gray-300 rounded-lg hover:bg-gray-50"
            >
              DB 브라우저
            </Link>
            <Link
              href="/admin"
              className="px-4 py-2 text-sm bg-blue-600 text-white rounded-lg hover:bg-blue-700"
            >
              라벨링 큐
            </Link>
          </div>
        </div>

        {/* 요약 카드 */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {[
            { label: "전체 분석", value: stats.total_runs, color: "text-blue-600" },
            { label: "라벨 완료", value: stats.labeled_runs, color: "text-green-600" },
            { label: "미완료", value: stats.unlabeled_runs, color: "text-gray-600" },
            { label: "라벨링률", value: `${labelingRate}%`, color: "text-purple-600" },
          ].map((card) => (
            <div key={card.label} className="bg-white rounded-xl border border-gray-200 p-5 shadow-sm">
              <p className="text-xs text-gray-500 uppercase tracking-wide">{card.label}</p>
              <p className={`text-3xl font-bold mt-1 ${card.color}`}>{card.value}</p>
            </div>
          ))}
        </div>

        {/* 일별 분석 추이 */}
        {stats.daily_runs.length > 0 && (
          <div className="bg-white rounded-xl border border-gray-200 p-5 shadow-sm">
            <h2 className="text-base font-semibold text-gray-800 mb-4">일별 분석 수 (최근 30일)</h2>
            <ResponsiveContainer width="100%" height={200}>
              <LineChart data={stats.daily_runs}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                <XAxis
                  dataKey="date"
                  tick={{ fontSize: 11 }}
                  tickFormatter={(v: string) => v.slice(5)}
                />
                <YAxis tick={{ fontSize: 11 }} allowDecimals={false} />
                <Tooltip />
                <Line type="monotone" dataKey="count" stroke="#3b82f6" strokeWidth={2} dot={false} name="분석 수" />
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}

        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {/* 사기 유형 분포 */}
          <div className="bg-white rounded-xl border border-gray-200 p-5 shadow-sm">
            <h2 className="text-base font-semibold text-gray-800 mb-4">사기 유형 분포 (예측)</h2>
            {stats.scam_type_distribution.length === 0 ? (
              <p className="text-sm text-gray-400">데이터 없음</p>
            ) : (
              <ResponsiveContainer width="100%" height={240}>
                <BarChart
                  data={stats.scam_type_distribution}
                  layout="vertical"
                  margin={{ left: 10, right: 20 }}
                >
                  <XAxis type="number" tick={{ fontSize: 11 }} allowDecimals={false} />
                  <YAxis type="category" dataKey="name" tick={{ fontSize: 11 }} width={100} />
                  <Tooltip />
                  <Bar dataKey="count" fill="#3b82f6" radius={[0, 4, 4, 0]} name="건수" />
                </BarChart>
              </ResponsiveContainer>
            )}
          </div>

          {/* (deprecated) 위험도 분포 chart 는 Stage 3 reframe 으로 제거 — ScamGuardian 은 등급 산정 안 함.
              detection_count 기반 차트는 별도 작업. backend 응답 schema 호환을 위해 type 정의는 유지. */}

          {/* 유형별 라벨 완료 */}
          {stats.labeled_by_type.length > 0 && (
            <div className="bg-white rounded-xl border border-gray-200 p-5 shadow-sm md:col-span-2">
              <h2 className="text-base font-semibold text-gray-800 mb-4">유형별 라벨 완료 현황</h2>
              <ResponsiveContainer width="100%" height={200}>
                <BarChart
                  data={stats.labeled_by_type}
                  layout="vertical"
                  margin={{ left: 10, right: 20 }}
                >
                  <XAxis type="number" tick={{ fontSize: 11 }} allowDecimals={false} />
                  <YAxis type="category" dataKey="name" tick={{ fontSize: 11 }} width={100} />
                  <Tooltip />
                  <Bar dataKey="count" fill="#22c55e" radius={[0, 4, 4, 0]} name="라벨 완료" />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
