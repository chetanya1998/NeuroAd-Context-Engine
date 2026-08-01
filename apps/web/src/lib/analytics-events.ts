export type Workflow = "single" | "comparison";

export type AnalyticsEventMap = {
  workflow_selected: { workflow: Workflow; video_count?: number };
  video_upload_started: { workflow: Workflow; video_count: number };
  video_upload_failed: { workflow: Workflow; video_count: number; error_code: string };
  dashboard_viewed: { video_id: string; source_type: string };
  segment_opened: { video_id?: string; segment_id: string; segment_index?: number };
  recommendation_evidence_opened: { video_id: string; tab: string };
  report_exported: {
    target_type: "video" | "comparison" | "insight";
    video_id?: string;
    comparison_id?: string;
    report_id?: string;
    export_format: "csv" | "json" | "pdf";
  };
  comparison_report_viewed: { comparison_id: string; video_count: number; result_status: string };
  individual_report_opened: { comparison_id: string; video_id: string };
  product_fit_result_viewed: {
    video_id: string;
    product_id: string;
    fit_score: number;
    suitability_tier: string;
  };
  insight_report_viewed: { report_id: string; target_type: "video" | "comparison" };
};

export type AnalyticsEvent = keyof AnalyticsEventMap;
