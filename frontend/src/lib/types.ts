/** Response shapes of the SafeFace API (mirror of backend/app/api/schemas.py). */

export interface Me {
  user: { id: string; username: string; display_name: string; roles: string[] };
  roles: string[];
}

export interface CaseSummary {
  id: string;
  case_no: string;
  fir_no: string | null;
  crime_head: string;
  investigating_officer: string;
  description: string | null;
  status: string;
  created_at: string;
  created_by_id: string;
  assigned_examiner_id: string | null;
  my_permission: string | null;
}

export interface Evidence {
  id: string;
  case_id: string;
  kind: "questioned" | "reference";
  media_type: string;
  detected_mime: string;
  original_filename: string;
  size_bytes: number;
  sha256: string;
  md5: string;
  source_url: string | null;
  source_platform: string | null;
  source_device: string | null;
  complainant: string | null;
  collected_by: string | null;
  collected_at: string | null;
  upload_method: string;
  ingested_at: string;
  reference_ids: string[];
  questioned_ids: string[];
  last_verification: { ok: boolean; verified_at: string; reason: string } | null;
}

export interface Member {
  user_id: string;
  permission: string;
  added_at: string;
  username: string;
  display_name: string;
}

export interface CaseDetail extends CaseSummary {
  evidence: Evidence[];
  members: Member[];
}

export interface EvidenceMetadata {
  filename: string;
  kind: "questioned" | "reference";
  source_url?: string | null;
  source_platform?: string | null;
  source_device?: string | null;
  complainant?: string | null;
  collected_by?: string | null;
  collected_at?: string | null;
  upload_method?: string;
  reference_for?: string[];
}

export interface UploadResult {
  evidence: Evidence;
  sha256: string;
  md5: string;
  size_bytes: number;
  triage_job_ids: string[];
}

export interface ScoreOut {
  name: string;
  value: number | null;
  range: [number, number] | null;
  meaning: string;
  unit: string | null;
}

export interface ArtefactOut {
  name: string;
  key: string;
  kind: "heatmap" | "image" | "plot" | "json";
  description: string;
  content_type: string;
  sha256: string;
}

export interface Finding {
  id: string;
  job_id: string;
  evidence_id: string;
  module_id: string;
  module_version: string;
  module_name: string;
  family: string;
  tier: number;
  scores: ScoreOut[];
  summary: string;
  details: Record<string, unknown>;
  artefacts: ArtefactOut[];
  limitations: string;
  provenance: Record<string, unknown>;
  created_at: string;
  triage_indicator: boolean;
}

export interface Job {
  id: string;
  evidence_id: string;
  module_id: string;
  module_version: string;
  status: "queued" | "running" | "succeeded" | "failed" | "unavailable";
  queued_at: string;
  finished_at: string | null;
  error: string | null;
  reference_ids: string[];
}

export interface FindingsResponse {
  evidence_id: string;
  groups: { family: string; label: string; findings: Finding[] }[];
  jobs: Job[];
  notice: string;
}

export interface ModuleInfo {
  id: string;
  version: string;
  name: string;
  description: string;
  family: string;
  family_label: string;
  tier: number;
  requires_gpu: boolean;
  requires_reference: boolean;
  limitations: string;
  triage_indicator: boolean;
  available: boolean;
  unavailable_reason: string;
  media_types: string[];
  validation: Record<string, unknown>[];
}

export interface Note {
  id: string;
  evidence_id: string;
  finding_id: string | null;
  author_name: string;
  text: string;
  created_at: string;
}

export interface Conclusion {
  id: string;
  evidence_id: string;
  scale_value: string;
  scale_label: string;
  rationale: string;
  author_id: string;
  author_name: string;
  created_at: string;
  approved_by_name: string | null;
  approved_at: string | null;
  approval_comment: string | null;
  case_id: string | null;
  case_no: string | null;
  evidence_filename: string | null;
}

export interface Report {
  id: string;
  case_id: string;
  /** null = combined case report; otherwise the questioned item this report covers. */
  evidence_id: string | null;
  version: number;
  status: "draft" | "final";
  pdf_sha256: string;
  evidence_hashes: { evidence_id: string; filename: string; sha256: string; md5: string; verified_at: string }[];
  generated_at: string;
  signed_by: { examiner: string; supervisor: string; approved_at: string }[];
}

export interface PerItemReports {
  generated: Report[];
  refused: { evidence_id: string; filename: string; failed_evidence: string[] }[];
}

export interface CustodyEntry {
  seq: number;
  ts: string;
  actor: string;
  action: string;
  details: Record<string, unknown>;
  entry_hash: string;
}

export interface RegistryEntry {
  name: string;
  module_id: string;
  version: string;
  weights_path: string;
  weights_sha256: string | null;
  licence: string;
  source: string | null;
  validation_summary: Record<string, unknown>;
  enabled: boolean;
  installed: boolean;
  status: string;
}

export interface RegistryChange {
  id: string;
  name: string;
  enabled_requested: boolean;
  reason: string;
  requested_at: string;
  status: string;
}

export interface AuditVerify {
  ok: boolean;
  entries_checked: number;
  head_seq: number;
  head_hash: string;
  first_bad_seq: number | null;
  problem: string | null;
  verified_at: string;
}

export interface ScreeningResult {
  evidence_id: string;
  status: "doubt_raised" | "no_doubt_raised" | "incomplete";
  headline: string;
  flags: { module_id: string; check: string; reason: string; finding_id: string }[];
  checks_run: string[];
  answer_line: string;
  questions: {
    key: "ai_generated" | "edited" | "face_swap" | "voice"; question: string; short: string;
    answer: "signs_found" | "no_signs" | "partly_checked" | "not_checked";
    checks_run: number; checks_flagged: number; reasons: string[]; checks: string[];
    likelihood: number | null; likelihood_band: "low" | "medium" | "high" | null; likelihood_source: string | null;
    detector_scores: { detector: string; module_id: string; likelihood: number }[];
  }[];
  missing_checks: string[];
  overall_likelihood: number | null;
  overall_band: "low" | "medium" | "high" | null;
  overall_question: string | null;
  checks: {
    module_id: string; check: string; family: string; plain: string; triage_indicator: boolean;
    score_name: string | null; value: number | null; range: [number, number] | null; meaning: string;
    threshold: number | null; flagged: boolean; reason: string; summary: string;
  }[];
  detectors_without_result: string[];
  pending: string[];
  caveat: string;
}

export const CONCLUSION_SCALE: { value: string; label: string }[] = [
  { value: "strong_support_manipulation", label: "Strong support for manipulation" },
  { value: "moderate_support_manipulation", label: "Moderate support for manipulation" },
  { value: "inconclusive", label: "Inconclusive" },
  { value: "moderate_support_authentic", label: "Moderate support for authenticity" },
  { value: "strong_support_authentic", label: "Strong support for authenticity" },
];
