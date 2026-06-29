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
  label: string;
  summary: string;
  transcript: string;
  recommendation: string;
  thumbnail_url?: string | null;
  objects: DetectedObject[];
  topics: Topic[];
  ad_matches: AdMatch[];
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
    best_hook: SummaryMoment | null;
    best_ad_slot: (SummaryMoment & { category?: string }) | null;
    weakest_segment: SummaryMoment | null;
    top_ad_category: string | null;
  };
  segments: Segment[];
  objects: DetectedObject[];
  topics: Topic[];
  ad_matches: AdMatch[];
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
};

export type Recommendation = {
  title: string;
  timestamp: string;
  body: string;
};

export type JobStatus = {
  id: string;
  video_id: string;
  status: "queued" | "processing" | "completed" | "failed";
  progress: number;
  current_step: string;
  error?: string | null;
};
