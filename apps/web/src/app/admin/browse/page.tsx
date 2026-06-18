"use client";

import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

interface RunItem {
  id: string;
  created_at: string;
  input_source: string;
  predicted_scam_type: string;
  predicted_confidence: number;
  total_score_predicted: number;
  transcript_preview: string;
  use_llm: boolean;
  labeled: boolean;
  scam_type_gt: string | null;
  labeler: string | null;
}

interface SearchResult {
  total: number;
  items: RunItem[];
  limit: number;
  offset: number;
}

const SCAM_TYPES = [
  "투자 사기", "보이스피싱", "대출 사기", "메신저 피싱",
  "로맨스 스캠", "취업·알바 사기", "납치·협박형", "스미싱",
  "중고거래 사기", "정상",
];

const PAGE_SIZE = 30;

export default function BrowsePage() {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [scamType, setScamType] = useState("");
  const [labeled, setLabeled] = useState("");
  const [offset, setOffset] = useState(0);
  const [result, setResult] = useState<SearchResult | null>(null);
  const [loading, setLoading] = useState(false);

  const fetchRuns = useCallback(
    async (currentOffset = 0) => {
      setLoading(true);
      const params = new URLSearchParams();
      if (query) params.set("q", query);
      if (scamType) params.set("scam_type", scamType);
      if (labeled) params.set("labeled", labeled);
      params.set("limit", String(PAGE_SIZE));
      params.set("offset", String(currentOffset));

      try {
        const res = await fetch(`/api/admin/runs/search?${params}`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        setResult(await res.json());
      } catch (e) {
        console.error(e);
      } finally {
        setLoading(false);
      }
    },
    [query, scamType, labeled]
  );

  useEffect(() => {
    setOffset(0);
    fetchRuns(0);
  }, [scamType, labeled, fetchRuns]);

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    setOffset(0);
    fetchRuns(0);
  };

  const goPage = (newOffset: number) => {
    setOffset(newOffset);
    fetchRuns(newOffset);
  };

  const totalPages = result ? Math.ceil(result.total / PAGE_SIZE) : 0;
  const currentPage = Math.floor(offset / PAGE_SIZE);

  return (
    <div className="min-h-screen bg-gray-50 p-6">
      <div className="max-w-6xl mx-auto space-y-5">
        {/* 헤더 */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">DB 브라우저</h1>
            <p className="text-sm text-gray-500 mt-1">분석 기록 검색 및 탐색</p>
          </div>
          <div className="flex gap-3">
            <Link
              href="/admin"
              className="px-4 py-2 text-sm bg-blue-600 text-white rounded-lg hover:bg-blue-700"
            >
              라벨링 큐
            </Link>
          </div>
        </div>

        {/* 검색 필터 */}
        <div className="bg-white rounded-xl border border-gray-200 p-4 shadow-sm">
          <form onSubmit={handleSearch} className="flex flex-wrap gap-3 items-end">
            <div className="flex-1 min-w-48">
              <label className="block text-xs text-gray-500 mb-1">텍스트 검색</label>
              <input
                type="text"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="발화 내용 검색..."
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>
            <div>
              <label className="block text-xs text-gray-500 mb-1">사기 유형</label>
              <select
                value={scamType}
                onChange={(e) => setScamType(e.target.value)}
                className="border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                <option value="">전체</option>
                {SCAM_TYPES.map((t) => (
                  <option key={t} value={t}>{t}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-xs text-gray-500 mb-1">라벨 상태</label>
              <select
                value={labeled}
                onChange={(e) => setLabeled(e.target.value)}
                className="border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                <option value="">전체</option>
                <option value="true">완료</option>
                <option value="false">미완료</option>
              </select>
            </div>
            <button
              type="submit"
              className="px-5 py-2 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700"
            >
              검색
            </button>
          </form>
        </div>

        {/* 결과 */}
        {loading ? (
          <div className="text-center py-12 text-gray-400">검색 중...</div>
        ) : result ? (
          <>
            <p className="text-sm text-gray-500">
              총 <strong>{result.total}</strong>건
            </p>
            <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
              <table className="w-full text-sm">
                <thead className="bg-gray-50 border-b border-gray-200">
                  <tr>
                    <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase">생성일</th>
                    <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase">사기 유형</th>
                    <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase">검출 신호 수</th>
                    <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase">라벨</th>
                    <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase">미리보기</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {result.items.length === 0 ? (
                    <tr>
                      <td colSpan={6} className="text-center py-10 text-gray-400">
                        결과가 없습니다.
                      </td>
                    </tr>
                  ) : (
                    result.items.map((item) => (
                      <tr
                        key={item.id}
                        className="hover:bg-blue-50 cursor-pointer"
                        onClick={() => router.push(`/admin/${item.id}`)}
                      >
                        <td className="px-4 py-3 text-gray-500 whitespace-nowrap">
                          {item.created_at.slice(0, 10)}
                        </td>
                        <td className="px-4 py-3 font-medium text-gray-800">
                          {item.predicted_scam_type || "—"}
                        </td>
                        <td className="px-4 py-3 text-gray-700">
                          {item.total_score_predicted}개
                        </td>
                        <td className="px-4 py-3">
                          {item.labeled ? (
                            <span className="px-2 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-700">
                              완료{item.labeler ? ` · ${item.labeler}` : ""}
                            </span>
                          ) : (
                            <span className="px-2 py-0.5 rounded-full text-xs font-medium bg-gray-100 text-gray-500">
                              미완료
                            </span>
                          )}
                        </td>
                        <td className="px-4 py-3 text-gray-500 max-w-xs truncate">
                          {item.transcript_preview}
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>

            {/* 페이지네이션 */}
            {totalPages > 1 && (
              <div className="flex items-center justify-center gap-2">
                <button
                  onClick={() => goPage(Math.max(0, offset - PAGE_SIZE))}
                  disabled={offset === 0}
                  className="px-3 py-1.5 text-sm border border-gray-300 rounded-lg disabled:opacity-40 hover:bg-gray-50"
                >
                  이전
                </button>
                <span className="text-sm text-gray-600">
                  {currentPage + 1} / {totalPages}
                </span>
                <button
                  onClick={() => goPage(offset + PAGE_SIZE)}
                  disabled={offset + PAGE_SIZE >= (result?.total ?? 0)}
                  className="px-3 py-1.5 text-sm border border-gray-300 rounded-lg disabled:opacity-40 hover:bg-gray-50"
                >
                  다음
                </button>
              </div>
            )}
          </>
        ) : null}
      </div>
    </div>
  );
}
