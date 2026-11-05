export type Values = Record<string, string>;
export type Envelope = {
  request_id: string;
  command: string;
  input: Record<string, unknown>;
  expected_revision?: number;
};
export type ApiError = {
  code?: string;
  message: string;
  details?: { revision?: number; parent_version_id?: string };
};
export interface CommandApi {
  command(envelope: Envelope): Promise<{ data: Record<string, unknown> }>;
}
export interface ApiPort extends CommandApi {
  query<T>(path: string): Promise<T>;
}
export type Page<T> = { items: T[]; next_cursor: string | null; as_of: string };
export interface Version {
  id: string;
  job_id: string;
  title: string;
  company_name: string;
  revision: number;
  original_url: string | null;
  description_text: string | null;
  requirements_text: string | null;
  completeness: string;
  locations?: string[];
  salary_text?: string | null;
  experience_text?: string | null;
  education_text?: string | null;
  observed_at?: string;
}
export interface Job {
  id: string;
  source_key: string;
  current_version: Version;
  last_complete_version?: Version | null;
  versions: Version[];
  current_observation?: { observed_at: string };
}
export interface MaterialVersion {
  id: string;
  material_id: string;
  revision: number;
  text_content: string;
  created_at: string;
  fact_snapshot?: { facts: { id: string }[] };
}
export interface Profile {
  targets: {
    id: string;
    revision: number;
    label: string;
    active: boolean;
    criteria: {
      keywords: string[];
      cities?: string[];
      any_city: boolean;
      conditions?: {
        field: string;
        operator: string;
        value: unknown;
        importance: string;
      }[];
    };
  }[];
  facts: {
    id: string;
    revision: number;
    status: string;
    kind: string;
    content: {
      title: string;
      description: string;
      organization?: string;
      start_date?: string;
      end_date?: string;
      result?: string;
    };
  }[];
  materials: { id: string; label: string; latest_version: MaterialVersion }[];
}
export interface Prep {
  id: string;
  revision: number;
  job_version_id: string;
  resume_version_id: string | null;
  resume_exception?: string;
  channel: string;
  apply_url?: string;
  next_step: string;
  cooldown_status: string;
  cooldown_snapshot: { status: string; explanation: string };
  job: Version;
  resume: MaterialVersion | null;
}
export interface Application {
  id: string;
  revision: number;
  opportunity_id: string;
  preparation_id: string | null;
  job_version_id: string;
  resume_version_id: string | null;
  channel: string;
  outcome: string;
  submitted_at: string | null;
  evidence: { statement?: string; asset_ids?: string[] };
  events: { revision: number; reason: string; recorded_at: string }[];
}
export interface Opportunity {
  id: string;
  revision: number;
  title: string;
  company_name: string;
  note: string;
  status: string;
  jobs: Job[];
  preparations: Prep[];
  applications: Application[];
  cooldown: { status: string; explanation: string };
}
