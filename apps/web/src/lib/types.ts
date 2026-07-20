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
  ad_slot_score?: number;
  ad_slot_reasons?: string[];
  is_best_ad_slot?: boolean;
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
  source?: string;
  language?: string | null;
  language_probability?: number;
  word_confidence?: number;
  avg_logprob?: number | null;
  no_speech_probability?: number | null;
  timestamp_coverage?: number;
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
  ad_slot_score?: number;
  ad_slot_reasons?: string[];
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

export type ComparisonVideo = {
  video_id: string;
  title: string;
  status: "uploaded" | "processing" | "completed" | "failed" | string;
  error?: string | null;
  duration?: number;
  thumbnail?: string | null;
  individual_report_url?: string | null;
  category?: string;
  category_confidence?: number;
  evidence_confidence?: number;
  score?: number;
  normalized_score?: number;
  percentile?: number;
  rank?: number;
  metrics?: Record<string, number>;
  strongest_ad_slot?: {
    start: number;
    end: number;
    score: number;
    ad_fit_score: number;
    reasons: string[];
  } | null;
  keywords?: Array<{ keyword: string; type: string; confidence: number; evidence: string[] }>;
};

export type ComparisonPayload = {
  comparison: {
    id: string;
    title: string;
    status: string;
    comparison_mode: "same_category" | "mixed" | "pending" | string;
    inferred_category: string;
    total_videos: number;
    completed_videos: number;
    failed_videos: number;
  };
  rankings: ComparisonVideo[];
  videos: ComparisonVideo[];
  metric_comparison: Array<{ metric: string; values: Array<{ video_id: string; value: number; rank: number }> }>;
  shared_keywords: string[];
  ab?: {
    video_a_id: string;
    video_b_id: string;
    winner: "A" | "B" | "tie";
    confidence: number;
    deltas: Array<{ metric: string; video_a: number; video_b: number; delta: number; winner: "A" | "B" | "tie" }>;
  } | null;
  recommendations: Recommendation[];
  caveats: string[];
};

export type ComparisonStatus = {
  comparison_id: string;
  status: string;
  total_videos: number;
  completed_videos: number;
  failed_videos: number;
  consolidated_report_ready: boolean;
  videos: Array<{ video_id: string; status: string; progress: number; job_id?: string | null; error?: string | null }>;
};

export type ProductProfile = {
  id?: string;
  source_url: string;
  canonical_url?: string | null;
  name: string;
  brand_name?: string | null;
  description?: string | null;
  category?: string | null;
  keywords: string[];
  features: string[];
  use_cases: string[];
  audience: string[];
  prohibited_contexts: string[];
  image_url?: string | null;
  extraction_confidence?: number;
  field_sources?: Record<string, string>;
  field_confidence?: Record<string, number>;
  warnings?: string[];
  profile_fingerprint?: string;
  profile_version?: string;
  cache_status?: "hit" | "miss" | string;
  status?: string;
  created_at?: string;
  updated_at?: string;
};

export type ProductPlacement = {
  id: string;
  segment_id: string;
  placement_score: number;
  placement_type: string;
  recommendation: string;
  reasons: string[];
  is_best_placement: boolean;
  start: number;
  end: number;
  summary: string;
  thumbnail_url?: string | null;
  product_relevance_score: number;
  placement_readiness_score: number;
  component_breakdown: Record<string, number>;
  positive_evidence: string[];
  conflicting_evidence: string[];
  limitations: string[];
  evidence_coverage: {
    transcript_matches?: number;
    topic_matches?: number;
    visual_matches?: number;
    modalities?: number;
  };
  transcript_excerpt?: string | null;
  relevant_topics: string[];
  relevant_objects: string[];
  suggested_duration?: string | null;
};

export type ProductFitPayload = {
  fit_run_id: string;
  video_id: string;
  video_title: string;
  product: ProductProfile;
  overall_fit_score: number;
  fit_confidence: number;
  suitability_tier: "Strong fit" | "Conditional fit" | "Weak fit" | "Not suitable" | string;
  summary: string;
  created_at: string;
  placements: ProductPlacement[];
  product_relevance_score: number;
  placement_readiness_score: number;
  component_scores: Record<string, number>;
  evidence_coverage: {
    transcript_matches?: number;
    topic_matches?: number;
    visual_matches?: number;
    modalities?: number;
  };
  positive_evidence: string[];
  conflicting_evidence: string[];
  limitations: string[];
  missing_input_warnings: string[];
  recommended_action: string;
  cache_status: "hit" | "miss" | string;
  scoring_version: string;
};
