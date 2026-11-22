export type Me = {
  id: string;
  email: string;
  email_verified: boolean;
  locale: "en" | "hi";
  created_at: string;
  consent_active: boolean;
};

export type ConsentNotice = { version: string; text_en: string; text_hi: string };

export type TokenOut = { access_token: string; expires_in: number };

export type FileKind = "pdf" | "csv" | "xls" | "xlsx";

export type PresignOut = {
  statement_id: string;
  duplicate: boolean;
  status: string;
  upload_url: string | null;
  content_type: string;
  expires_in: number;
};

export type Statement = {
  id: string;
  status: string;
  failure_code: string | null;
  file_kind: string;
  bank_code: string | null;
  rows_parsed: number | null;
  reconciled: boolean | null;
  period_from: string | null;
  period_to: string | null;
  created_at: string;
  analysis_note: string | null;
};

export type Level = "claim" | "worth_checking" | "needs_user_input" | "needs_review" | "historical" | "informational";

export type Question = "payee_was_merchant" | "payment_failed" | "mandate_revoked";

export type Finding = {
  id: string;
  detector: string;
  level: Level;
  confidence: "high" | "medium" | "low";
  status: "open" | "confirmed" | "dismissed";
  rule_id: string | null;
  letter_scope: string | null;
  question: Question | null;
  t_date: string | null;
  r_date: string | null;
  delay_days: number | null;
  amount_owed_paise: number | null;
  already_paid_paise: number;
  accruing: boolean;
  why: string;
  created_at: string;
  feedback: Verdict | null;
};

export type CaseState =
  | "draft"
  | "sent_to_bank"
  | "awaiting_reply"
  | "resolved"
  | "escalation_eligible"
  | "escalated"
  | "closed"
  | "expired";

export type CaseSummary = {
  id: string;
  state: CaseState;
  bank_code: string;
  language: "en" | "hi";
  finding_ids: string[];
  sent_on: string | null;
  bank_received_on: string | null;
  last_communication_on: string | null;
  escalation_eligible_on: string | null;
  filing_deadline_on: string | null;
  days_left: number | null;
  escalated_on: string | null;
  recovered_paise: number | null;
  recovered_on: string | null;
  created_at: string;
};

export type Letter = {
  id: string;
  kind: "bank" | "cms";
  language: string;
  text: string;
  polished: boolean;
  guardrail_note: string;
  approved_at: string | null;
};

export type CaseEvent = { seq: number; type: string; payload: Record<string, unknown>; at: string };

export type CaseDetail = CaseSummary & { events: CaseEvent[]; letters: Letter[] };

export type Notification = {
  id: string;
  case_id: string | null;
  kind: string;
  message: string;
  created_at: string;
  read_at: string | null;
};

export type Verdict = "correct" | "wrong" | "not_sure";
