export type DetectedObject = {
  id?: string;
  label: string;
  confidence: number;
  bbox?: number[] | null;
  frame_timestamp?: number;
};

export type Topic = {
  id?: string;
  label: string;
  confidence: number;
};

export type AdMatch = {
  id?: string;
  ad_category: string;
  ad_fit_score: number;
  reason: string;
  confidence: number;
};

export type Segment = {
  id: string;
  start: number;
  end: number;
  attention_score: number;
  ad_fit_score: number;
  drop_risk_score: number;
  brand_safety_score: number;
  label: string;
  summary: string;
  transcript: string;
  transcript_insights: TranscriptInsights;
  visual_evidence: VisualEvidence;
  score_reasons: string[];
  recommendation: string;
  recommendation_tier?: RecommendationTier;
  recommendation_confidence?: number;
  evidence_mode?: EvidenceMode;
  strong_signals?: string[];
  failed_or_weak_signals?: string[];
  thumbnail_url?: string | null;
  objects: DetectedObject[];
  topics: Topic[];
  ad_matches: AdMatch[];
};

export type TranscriptInsights = {
  word_count?: number;
  words_per_second?: number;
  clarity_score?: number;
  transcript_confidence?: number;
  transcript_quality_flags?: string[];
  hook_terms?: string[];
  cta_terms?: string[];
  claim_terms?: string[];
  risk_flags?: Record<string, string[]>;
  filler_count?: number;
  repetition_penalty?: number;
  silence_penalty?: number;
  early_hook?: boolean;
};

export type VisualEvidence = {
  sampled_frames?: number;
  visual_novelty?: number;
  motion?: number;
  visual_quality?: number;
  brightness?: number;
  contrast?: number;
  sharpness?: number;
  object_count?: number;
  top_objects?: string[];
  blur_penalty?: number;
};

export type AnalysisPayload = {
  video: {
    id: string;
    title: string;
    description?: string;
    duration: number;
    thumbnail?: string | null;
    source_type: "upload" | "url" | "youtube" | "youtube_ingest";
    source_url?: string | null;
    file_url?: string | null;
    embed_url?: string | null;
    status: string;
  };
  summary: {
    overall_attention_score: number;
    monetization_opportunity_score: number;
    overall_drop_risk_score?: number;
    brand_safety_score?: number;
    transcript_clarity_score?: number;
    visual_quality_score?: number;
    creator_readiness_score?: number;
    ad_catalog_size?: number;
    best_hook: SummaryMoment | null;
    best_ad_slot: (SummaryMoment & { category?: string }) | null;
    best_content_window?: SummaryMoment | null;
    best_recommendation_tier?: RecommendationTier;
    recommendation_status?: string;
    recommendation_message?: string;
    weakest_segment: SummaryMoment | null;
    top_ad_category: string | null;
  };
  segments: Segment[];
  objects: DetectedObject[];
  topics: Topic[];
  ad_matches: AdMatch[];
  ad_categories?: string[];
  recommendations: Recommendation[];
  exports: {
    csv?: string | null;
    json?: string | null;
  };
};

export type SummaryMoment = {
  start: number;
  end: number;
  score: number;
  ad_fit_score: number;
  label: string;
  recommendation_tier?: RecommendationTier;
  recommendation_confidence?: number;
};

export type Recommendation = {
  title: string;
  timestamp: string;
  body: string;
};

export type RecommendationTier = "Strong ad slot" | "Conditional ad slot" | "Edit before monetization" | "Avoid";

export type EvidenceMode = "transcript_visual" | "visual_only" | "audio_visual" | "weak_evidence";

export type JobStatus = {
  id: string;
  video_id: string;
  status: "queued" | "processing" | "completed" | "failed";
  progress: number;
  current_step: string;
  error?: string | null;
};
