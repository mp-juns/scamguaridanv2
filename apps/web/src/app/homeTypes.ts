export type Entity = {
  label: string;
  text: string;
  score: number;
  start?: number;
  end?: number;
  source?: string;
};

export type DetectedSignal = {
  flag: string;
  label_ko: string;
  rationale?: string;
  source?: string;
  detection_source?: string;
  evidence?: string[];
  description?: string;
};

export type LlmSuggestedEntity = {
  text: string;
  label: string;
  reason: string;
  confidence: number;
};

export type LlmSuggestedFlag = {
  flag: string;
  reason: string;
  evidence: string;
  confidence: number;
};

export type LlmAssessment = {
  model: string;
  summary: string;
  reasoning?: string[];
  suggested_entities: LlmSuggestedEntity[];
  suggested_flags: LlmSuggestedFlag[];
  error: string;
};

export type RagSimilarCase = {
  run_id: string;
  scam_type_gt: string;
  distance: number;
  transcript_excerpt: string;
};

export type RagContext = {
  enabled: boolean;
  similar_cases: RagSimilarCase[];
};

export type ContentType = {
  bucket?: string;
  label_ko?: string;
};

export type AnalysisReport = {
  scam_type: string;
  /** 대표 카테고리 — scam_type 의 결정적 매핑(표시 전용). 분류 skip 시 빈 값 */
  scam_category?: string;
  scam_category_source?: string;
  classification_confidence: number;
  is_uncertain: boolean;
  transcript_preview: string;
  transcript_text?: string;
  detected_signals: DetectedSignal[];
  summary?: string;
  disclaimer?: string;
  entities: Entity[];
  verification_count: number;
  llm_assessment?: LlmAssessment | null;
  rag_context?: RagContext | null;
  analysis_run_id?: string;
  content_type?: ContentType | null;
  /** 게이트 normal vs 룰 신호 충돌 — 심층 분석 강한 권장 (백엔드가 설정) */
  deep_recommended?: boolean;
  deep_recommended_reason?: string;
};

export type TranscriptSpan = {
  start: number;
  end: number;
  kind: "entity" | "evidence";
  label?: string;
};
