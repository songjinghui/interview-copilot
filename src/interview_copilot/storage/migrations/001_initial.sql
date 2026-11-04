-- Runtime migration 001, based on approved design v0.3 (e99aa01).
-- Execute only against an empty isolated SQLite database.
-- UUIDs and canonical UTC timestamps are supplied by the application.
-- JSON shapes and transactional invariants: database-design.md.
PRAGMA foreign_keys = ON;

CREATE TABLE schema_migrations (
    version INTEGER PRIMARY KEY,
    checksum TEXT NOT NULL,
    applied_at TEXT NOT NULL
);
CREATE TABLE settings (
    key TEXT PRIMARY KEY NOT NULL,
    value_json TEXT NOT NULL CHECK(json_valid(value_json)),
    revision INTEGER NOT NULL DEFAULT 1 CHECK(revision > 0),
    updated_at TEXT NOT NULL
);
CREATE TABLE sources (
    key TEXT PRIMARY KEY NOT NULL,
    display_name TEXT NOT NULL,
    adapter_version TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 0 CHECK(enabled IN (0,1)),
    config_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(config_json)),
    credential_ref TEXT,
    connection_state TEXT NOT NULL DEFAULT 'unconfigured'
        CHECK(connection_state IN ('unconfigured','ready','auth_required','error','disabled')),
    revision INTEGER NOT NULL DEFAULT 1 CHECK(revision > 0),
    updated_at TEXT NOT NULL
);
CREATE TABLE source_capabilities (
    source_key TEXT NOT NULL REFERENCES sources(key) ON DELETE RESTRICT,
    capability TEXT NOT NULL CHECK(capability IN ('search_jobs','read_job','read_feedback')),
    enabled INTEGER NOT NULL DEFAULT 0 CHECK(enabled IN (0,1)),
    evidence_status TEXT NOT NULL CHECK(evidence_status IN ('verified','unverified','unsupported')),
    evidence_stage TEXT NOT NULL CHECK(evidence_stage IN ('external_sample','local_script','product')),
    evidence_json TEXT NOT NULL CHECK(json_valid(evidence_json)),
    verified_at TEXT,
    PRIMARY KEY(source_key, capability)
);
CREATE TABLE source_accounts (
    id TEXT PRIMARY KEY NOT NULL,
    source_key TEXT NOT NULL REFERENCES sources(key) ON DELETE RESTRICT,
    account_key TEXT NOT NULL,
    display_name TEXT NOT NULL,
    credential_ref TEXT,
    connection_state TEXT NOT NULL DEFAULT 'unconfigured'
        CHECK(connection_state IN ('unconfigured','ready','auth_required','error','disabled')),
    updated_at TEXT NOT NULL,
    UNIQUE(source_key,account_key), UNIQUE(source_key,id)
);
CREATE TABLE profile_targets (
    id TEXT PRIMARY KEY NOT NULL,
    label TEXT NOT NULL,
    criteria_json TEXT NOT NULL CHECK(json_valid(criteria_json)),
    active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
    revision INTEGER NOT NULL DEFAULT 1 CHECK(revision > 0),
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE profile_facts (
    id TEXT PRIMARY KEY NOT NULL,
    kind TEXT NOT NULL CHECK(kind IN ('employment','project','skill','education','achievement')),
    content_json TEXT NOT NULL CHECK(json_valid(content_json)),
    status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','confirmed','archived')),
    provenance_json TEXT NOT NULL CHECK(json_valid(provenance_json)),
    confirmed_at TEXT,
    revision INTEGER NOT NULL DEFAULT 1 CHECK(revision > 0),
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
    CHECK(status <> 'confirmed' OR confirmed_at IS NOT NULL)
);
-- Staging rows are the import journal; only ready assets may be used as inputs.
CREATE TABLE file_assets (
    id TEXT PRIMARY KEY NOT NULL,
    kind TEXT NOT NULL CHECK(kind IN ('resume','audio','evidence','raw_source','checkpoint','export')),
    status TEXT NOT NULL DEFAULT 'staging' CHECK(status IN ('staging','ready','missing','quarantined')),
    relative_path TEXT NOT NULL UNIQUE,
    original_name TEXT NOT NULL,
    media_type TEXT NOT NULL,
    byte_size INTEGER CHECK(byte_size >= 0),
    sha256 TEXT CHECK(sha256 IS NULL OR length(sha256)=64),
    intent_json TEXT NOT NULL CHECK(json_valid(intent_json)),
    created_at TEXT NOT NULL, finalized_at TEXT,
    CHECK(status <> 'ready' OR (sha256 IS NOT NULL AND byte_size IS NOT NULL AND finalized_at IS NOT NULL))
);
CREATE TABLE materials (
    id TEXT PRIMARY KEY NOT NULL,
    label TEXT NOT NULL,
    archived_at TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE material_versions (
    id TEXT PRIMARY KEY NOT NULL,
    material_id TEXT NOT NULL REFERENCES materials(id) ON DELETE RESTRICT,
    revision INTEGER NOT NULL CHECK(revision > 0),
    file_asset_id TEXT REFERENCES file_assets(id) ON DELETE RESTRICT,
    text_content TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    fact_snapshot_json TEXT NOT NULL CHECK(json_valid(fact_snapshot_json)),
    created_at TEXT NOT NULL,
    UNIQUE(material_id, revision)
);
-- Worker inputs live in input_json, never in an ephemeral HTTP callback.
CREATE TABLE background_tasks (
    id TEXT PRIMARY KEY NOT NULL,
    kind TEXT NOT NULL CHECK(kind IN ('search','read_job','sync_feedback','transcribe','review','material_draft','export')),
    dedup_key TEXT NOT NULL UNIQUE,
    input_json TEXT NOT NULL CHECK(json_valid(input_json)),
    status TEXT NOT NULL DEFAULT 'queued'
        CHECK(status IN ('queued','running','succeeded','retry_wait','needs_attention','paused','cancelled')),
    attempt INTEGER NOT NULL DEFAULT 0 CHECK(attempt >= 0),
    failure_count INTEGER NOT NULL DEFAULT 0 CHECK(failure_count >= 0),
    owner_run_id TEXT,
    heartbeat_at TEXT,
    next_retry_at TEXT,
    checkpoint_asset_id TEXT REFERENCES file_assets(id) ON DELETE RESTRICT,
    progress REAL CHECK(progress BETWEEN 0 AND 1),
    stage TEXT,
    last_error_json TEXT CHECK(last_error_json IS NULL OR json_valid(last_error_json)),
    result_json TEXT CHECK(result_json IS NULL OR json_valid(result_json)),
    revision INTEGER NOT NULL DEFAULT 1 CHECK(revision > 0),
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
    CHECK(status <> 'running' OR (owner_run_id IS NOT NULL AND heartbeat_at IS NOT NULL)),
    CHECK(status <> 'retry_wait' OR next_retry_at IS NOT NULL),
    CHECK(status <> 'succeeded' OR result_json IS NOT NULL)
);
CREATE INDEX tasks_due ON background_tasks(status, next_retry_at, created_at);
CREATE TABLE fetch_runs (
    id TEXT PRIMARY KEY NOT NULL,
    task_id TEXT NOT NULL REFERENCES background_tasks(id) ON DELETE RESTRICT,
    source_key TEXT NOT NULL REFERENCES sources(key) ON DELETE RESTRICT,
    capability TEXT NOT NULL CHECK(capability IN ('search_jobs','read_job','read_feedback')),
    request_json TEXT NOT NULL CHECK(json_valid(request_json)),
    applied_filters_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(applied_filters_json)),
    status TEXT NOT NULL CHECK(status IN ('running','succeeded','partial','failed','interrupted')),
    error_json TEXT CHECK(error_json IS NULL OR json_valid(error_json)),
    started_at TEXT NOT NULL, finished_at TEXT
);
CREATE INDEX fetch_source_time ON fetch_runs(source_key, started_at);
CREATE TABLE jobs (
    id TEXT PRIMARY KEY NOT NULL,
    source_key TEXT NOT NULL REFERENCES sources(key) ON DELETE RESTRICT,
    external_key TEXT NOT NULL,
    current_version_id TEXT,
    last_complete_version_id TEXT,
    first_observed_at TEXT NOT NULL, last_observed_at TEXT NOT NULL,
    archived_at TEXT,
    UNIQUE(source_key, external_key),
    FOREIGN KEY(id,current_version_id) REFERENCES job_versions(job_id,id) DEFERRABLE INITIALLY DEFERRED,
    FOREIGN KEY(id,last_complete_version_id) REFERENCES job_versions(job_id,id) DEFERRABLE INITIALLY DEFERRED
);
CREATE TABLE job_versions (
    id TEXT PRIMARY KEY NOT NULL,
    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE RESTRICT,
    revision INTEGER NOT NULL CHECK(revision > 0),
    title TEXT NOT NULL,
    company_name TEXT NOT NULL,
    original_url TEXT,
    apply_url TEXT,
    locations_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(locations_json)),
    salary_text TEXT, experience_text TEXT, education_text TEXT,
    description_text TEXT,
    requirements_text TEXT,
    completeness TEXT NOT NULL CHECK(completeness IN ('summary','partial','complete')),
    availability TEXT NOT NULL DEFAULT 'unknown' CHECK(availability IN ('open','closed','unknown')),
    content_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(job_id, revision), UNIQUE(job_id,id),
    CHECK(completeness <> 'complete' OR (length(trim(description_text))>0 AND length(trim(requirements_text))>0
        AND description_text IS NOT NULL AND requirements_text IS NOT NULL))
);
CREATE INDEX jobs_recent ON jobs(last_observed_at,id);
CREATE INDEX versions_hash ON job_versions(job_id,content_hash);
CREATE TABLE job_observations (
    id TEXT PRIMARY KEY NOT NULL,
    fetch_run_id TEXT REFERENCES fetch_runs(id) ON DELETE RESTRICT,
    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE RESTRICT,
    version_id TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    method TEXT NOT NULL,
    observed_json TEXT NOT NULL CHECK(json_valid(observed_json)),
    raw_asset_id TEXT REFERENCES file_assets(id) ON DELETE RESTRICT,
    FOREIGN KEY(job_id,version_id) REFERENCES job_versions(job_id,id) ON DELETE RESTRICT
);
CREATE INDEX observations_job_time ON job_observations(job_id,observed_at,id);
CREATE TABLE search_matches (
    task_id TEXT NOT NULL REFERENCES background_tasks(id) ON DELETE RESTRICT,
    job_version_id TEXT NOT NULL REFERENCES job_versions(id) ON DELETE RESTRICT,
    assessment_json TEXT NOT NULL CHECK(json_valid(assessment_json)),
    PRIMARY KEY(task_id,job_version_id)
);
CREATE TABLE opportunities (
    id TEXT PRIMARY KEY NOT NULL,
    title TEXT NOT NULL,
    company_name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'saved'
        CHECK(status IN ('saved','deferred','applying','applied','interviewing','offer','rejected','withdrawn','archived')),
    note TEXT NOT NULL DEFAULT '',
    revision INTEGER NOT NULL DEFAULT 1 CHECK(revision > 0),
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX opportunities_status_time ON opportunities(status,updated_at,id);
CREATE TABLE opportunity_jobs (
    opportunity_id TEXT NOT NULL REFERENCES opportunities(id) ON DELETE RESTRICT,
    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE RESTRICT,
    basis_json TEXT NOT NULL CHECK(json_valid(basis_json)),
    created_at TEXT NOT NULL,
    PRIMARY KEY(opportunity_id, job_id)
);
CREATE TABLE cooldown_notes (
    id TEXT PRIMARY KEY NOT NULL,
    opportunity_id TEXT NOT NULL REFERENCES opportunities(id) ON DELETE RESTRICT,
    scope TEXT NOT NULL CHECK(scope IN ('company','job')),
    status TEXT NOT NULL CHECK(status IN ('present','absent','unknown')),
    explanation TEXT NOT NULL,
    evidence_json TEXT NOT NULL CHECK(json_valid(evidence_json)),
    known_until TEXT,
    checked_at TEXT NOT NULL,
    supersedes_id TEXT REFERENCES cooldown_notes(id) ON DELETE RESTRICT
);
CREATE INDEX cooldown_opportunity_time ON cooldown_notes(opportunity_id,checked_at,id);
CREATE TABLE application_preparations (
    id TEXT PRIMARY KEY NOT NULL,
    opportunity_id TEXT NOT NULL REFERENCES opportunities(id) ON DELETE RESTRICT,
    job_version_id TEXT NOT NULL REFERENCES job_versions(id) ON DELETE RESTRICT,
    resume_version_id TEXT REFERENCES material_versions(id) ON DELETE RESTRICT,
    resume_exception TEXT,
    channel TEXT NOT NULL,
    apply_url TEXT,
    cooldown_snapshot_json TEXT NOT NULL CHECK(json_valid(cooldown_snapshot_json)),
    cooldown_status TEXT NOT NULL CHECK(cooldown_status IN ('present','absent','unknown')),
    status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','ready_for_manual_apply','deferred')),
    material_confirmed_at TEXT,
    cooldown_confirmed_at TEXT,
    revision INTEGER NOT NULL DEFAULT 1 CHECK(revision > 0),
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
    CHECK(cooldown_confirmed_at IS NULL OR material_confirmed_at IS NOT NULL),
    CHECK(material_confirmed_at IS NULL OR resume_version_id IS NOT NULL
        OR (resume_exception IS NOT NULL AND length(trim(resume_exception)) > 0)),
    CHECK(status <> 'ready_for_manual_apply' OR (material_confirmed_at IS NOT NULL
        AND (cooldown_status <> 'present' OR cooldown_confirmed_at IS NOT NULL)))
);
CREATE TABLE applications (
    id TEXT PRIMARY KEY NOT NULL,
    opportunity_id TEXT NOT NULL REFERENCES opportunities(id) ON DELETE RESTRICT,
    preparation_id TEXT REFERENCES application_preparations(id) ON DELETE RESTRICT,
    job_version_id TEXT NOT NULL REFERENCES job_versions(id) ON DELETE RESTRICT,
    resume_version_id TEXT REFERENCES material_versions(id) ON DELETE RESTRICT,
    channel TEXT NOT NULL,
    outcome TEXT NOT NULL CHECK(outcome IN ('submitted','unknown','failed')),
    submitted_at TEXT,
    evidence_json TEXT NOT NULL CHECK(json_valid(evidence_json)),
    revision INTEGER NOT NULL DEFAULT 1 CHECK(revision > 0),
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
    UNIQUE(opportunity_id,id),
    CHECK(outcome <> 'submitted' OR submitted_at IS NOT NULL)
);
CREATE INDEX applications_opportunity_time ON applications(opportunity_id,created_at,id);
CREATE TABLE application_events (
    id TEXT PRIMARY KEY NOT NULL,
    application_id TEXT NOT NULL REFERENCES applications(id) ON DELETE RESTRICT,
    revision INTEGER NOT NULL CHECK(revision > 0),
    snapshot_json TEXT NOT NULL CHECK(json_valid(snapshot_json)),
    reason TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    UNIQUE(application_id,revision)
);
CREATE TABLE feedback_items (
    id TEXT PRIMARY KEY NOT NULL,
    source_key TEXT NOT NULL REFERENCES sources(key) ON DELETE RESTRICT,
    account_id TEXT NOT NULL,
    external_key TEXT NOT NULL,
    opportunity_id TEXT REFERENCES opportunities(id) ON DELETE RESTRICT,
    text_content TEXT NOT NULL,
    evidence_asset_id TEXT REFERENCES file_assets(id) ON DELETE RESTRICT,
    occurred_at TEXT,
    received_at TEXT NOT NULL,
    proposal_json TEXT CHECK(proposal_json IS NULL OR json_valid(proposal_json)),
    status TEXT NOT NULL DEFAULT 'unlinked' CHECK(status IN ('unlinked','pending','accepted','ignored')),
    revision INTEGER NOT NULL DEFAULT 1 CHECK(revision > 0),
    UNIQUE(account_id, external_key), UNIQUE(account_id,id),
    FOREIGN KEY(source_key,account_id) REFERENCES source_accounts(source_key,id) ON DELETE RESTRICT
);
CREATE TABLE sync_cursors (
    account_id TEXT NOT NULL REFERENCES source_accounts(id) ON DELETE RESTRICT,
    stream_key TEXT NOT NULL,
    cursor_json TEXT NOT NULL CHECK(json_valid(cursor_json)),
    last_success_at TEXT,
    PRIMARY KEY(account_id, stream_key)
);
CREATE TABLE interviews (
    id TEXT PRIMARY KEY NOT NULL,
    opportunity_id TEXT NOT NULL REFERENCES opportunities(id) ON DELETE RESTRICT,
    application_id TEXT,
    label TEXT NOT NULL,
    starts_at TEXT, ends_at TEXT,
    time_zone TEXT NOT NULL,
    format TEXT NOT NULL CHECK(format IN ('online','onsite','phone','unknown')),
    location TEXT,
    status TEXT NOT NULL DEFAULT 'planned' CHECK(status IN ('planned','completed','cancelled')),
    source_feedback_id TEXT,
    source_account_id TEXT REFERENCES source_accounts(id) ON DELETE RESTRICT,
    source_event_key TEXT,
    revision INTEGER NOT NULL DEFAULT 1 CHECK(revision > 0),
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
    FOREIGN KEY(opportunity_id,application_id) REFERENCES applications(opportunity_id,id) ON DELETE RESTRICT,
    CHECK(ends_at IS NULL OR (starts_at IS NOT NULL AND ends_at > starts_at)),
    FOREIGN KEY(source_account_id,source_feedback_id) REFERENCES feedback_items(account_id,id) ON DELETE RESTRICT,
    CHECK((source_account_id IS NULL AND source_event_key IS NULL AND source_feedback_id IS NULL)
       OR (source_account_id IS NOT NULL AND source_event_key IS NOT NULL)),
    UNIQUE(source_account_id, source_event_key)
);
CREATE INDEX interviews_schedule ON interviews(status,starts_at,id);
CREATE TABLE interview_context_versions (
    id TEXT PRIMARY KEY NOT NULL,
    interview_id TEXT NOT NULL REFERENCES interviews(id) ON DELETE RESTRICT,
    revision INTEGER NOT NULL CHECK(revision > 0),
    job_title TEXT NOT NULL,
    job_version_id TEXT REFERENCES job_versions(id) ON DELETE RESTRICT,
    resume_version_id TEXT REFERENCES material_versions(id) ON DELETE RESTRICT,
    missing_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(missing_json)),
    created_at TEXT NOT NULL,
    UNIQUE(interview_id,revision), UNIQUE(interview_id,id)
);
CREATE TABLE reminders (
    id TEXT PRIMARY KEY NOT NULL,
    interview_id TEXT REFERENCES interviews(id) ON DELETE RESTRICT,
    cooldown_note_id TEXT REFERENCES cooldown_notes(id) ON DELETE RESTRICT,
    scheduled_for TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','delivered','missed','cancelled','acknowledged')),
    delivered_at TEXT,
    created_at TEXT NOT NULL,
    CHECK((interview_id IS NOT NULL) + (cooldown_note_id IS NOT NULL)=1)
);
CREATE INDEX reminders_due ON reminders(status,scheduled_for,id);
CREATE TABLE audio_assets (
    id TEXT PRIMARY KEY NOT NULL,
    interview_id TEXT NOT NULL REFERENCES interviews(id) ON DELETE RESTRICT,
    revision INTEGER NOT NULL CHECK(revision > 0),
    origin TEXT NOT NULL CHECK(origin IN ('recording','import')),
    status TEXT NOT NULL CHECK(status IN ('capturing','finalized','interrupted','missing')),
    consent_at TEXT,
    duration_ms INTEGER CHECK(duration_ms >= 0),
    completeness TEXT NOT NULL CHECK(completeness IN ('complete','partial')),
    created_at TEXT NOT NULL, finalized_at TEXT,
    UNIQUE(interview_id,id), UNIQUE(id,revision),
    CHECK(origin <> 'recording' OR consent_at IS NOT NULL)
);
CREATE TABLE audio_parts (
    audio_asset_id TEXT NOT NULL REFERENCES audio_assets(id) ON DELETE RESTRICT,
    ordinal INTEGER NOT NULL CHECK(ordinal >= 0),
    file_asset_id TEXT NOT NULL REFERENCES file_assets(id) ON DELETE RESTRICT,
    start_ms INTEGER NOT NULL CHECK(start_ms >= 0),
    end_ms INTEGER NOT NULL CHECK(end_ms >= start_ms),
    PRIMARY KEY(audio_asset_id,ordinal), UNIQUE(audio_asset_id,file_asset_id)
);
CREATE TABLE transcription_jobs (
    task_id TEXT PRIMARY KEY NOT NULL REFERENCES background_tasks(id) ON DELETE RESTRICT,
    audio_asset_id TEXT NOT NULL,
    asset_revision INTEGER NOT NULL,
    config_hash TEXT NOT NULL,
    config_json TEXT NOT NULL CHECK(json_valid(config_json)),
    request_generation INTEGER NOT NULL CHECK(request_generation > 0),
    result_version_id TEXT REFERENCES transcript_versions(id) ON DELETE RESTRICT,
    UNIQUE(audio_asset_id,asset_revision,config_hash,request_generation),
    FOREIGN KEY(audio_asset_id,asset_revision) REFERENCES audio_assets(id,revision) ON DELETE RESTRICT
);
CREATE TABLE transcript_versions (
    id TEXT PRIMARY KEY NOT NULL,
    interview_id TEXT NOT NULL REFERENCES interviews(id) ON DELETE RESTRICT,
    revision INTEGER NOT NULL CHECK(revision > 0),
    audio_asset_id TEXT,
    origin TEXT NOT NULL CHECK(origin IN ('asr','manual','correction','combined')),
    parent_version_id TEXT,
    content_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(interview_id,revision), UNIQUE(interview_id,id),
    FOREIGN KEY(interview_id,audio_asset_id) REFERENCES audio_assets(interview_id,id) ON DELETE RESTRICT,
    FOREIGN KEY(interview_id,parent_version_id) REFERENCES transcript_versions(interview_id,id) ON DELETE RESTRICT,
    CHECK(origin <> 'asr' OR audio_asset_id IS NOT NULL)
);
CREATE TABLE transcript_segments (
    version_id TEXT NOT NULL REFERENCES transcript_versions(id) ON DELETE RESTRICT,
    interview_id TEXT NOT NULL,
    segment_key TEXT NOT NULL,
    ordinal INTEGER NOT NULL CHECK(ordinal >= 0),
    speaker TEXT NOT NULL,
    text_content TEXT NOT NULL,
    audio_asset_id TEXT,
    source_version_id TEXT,
    source_segment_key TEXT,
    start_ms INTEGER, end_ms INTEGER,
    PRIMARY KEY(version_id,segment_key), UNIQUE(version_id,ordinal),
    FOREIGN KEY(interview_id,version_id) REFERENCES transcript_versions(interview_id,id) ON DELETE RESTRICT,
    FOREIGN KEY(interview_id,audio_asset_id) REFERENCES audio_assets(interview_id,id) ON DELETE RESTRICT,
    FOREIGN KEY(interview_id,source_version_id) REFERENCES transcript_versions(interview_id,id) ON DELETE RESTRICT,
    FOREIGN KEY(source_version_id,source_segment_key) REFERENCES transcript_segments(version_id,segment_key) ON DELETE RESTRICT,
    CHECK((source_version_id IS NULL AND source_segment_key IS NULL) OR
        (source_version_id IS NOT NULL AND source_segment_key IS NOT NULL)),
    CHECK(audio_asset_id IS NOT NULL OR (start_ms IS NULL AND end_ms IS NULL)),
    CHECK((start_ms IS NULL AND end_ms IS NULL) OR
        (start_ms IS NOT NULL AND end_ms IS NOT NULL AND start_ms >= 0 AND end_ms >= start_ms))
);
CREATE TABLE review_runs (
    id TEXT PRIMARY KEY NOT NULL,
    task_id TEXT NOT NULL UNIQUE REFERENCES background_tasks(id) ON DELETE RESTRICT,
    interview_id TEXT NOT NULL REFERENCES interviews(id) ON DELETE RESTRICT,
    context_version_id TEXT NOT NULL,
    transcript_version_id TEXT NOT NULL,
    model_config_json TEXT NOT NULL CHECK(json_valid(model_config_json)),
    prompt_revision TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(interview_id,context_version_id) REFERENCES interview_context_versions(interview_id,id) ON DELETE RESTRICT,
    FOREIGN KEY(interview_id,transcript_version_id) REFERENCES transcript_versions(interview_id,id) ON DELETE RESTRICT
);
CREATE TABLE review_reports (
    id TEXT PRIMARY KEY NOT NULL,
    review_run_id TEXT NOT NULL UNIQUE REFERENCES review_runs(id) ON DELETE RESTRICT,
    body_json TEXT NOT NULL CHECK(json_valid(body_json)),
    created_at TEXT NOT NULL
);
CREATE TABLE improvement_items (
    id TEXT PRIMARY KEY NOT NULL,
    opportunity_id TEXT REFERENCES opportunities(id) ON DELETE RESTRICT,
    title TEXT NOT NULL,
    action TEXT NOT NULL,
    category TEXT,
    priority TEXT NOT NULL DEFAULT 'medium' CHECK(priority IN ('high','medium','low')),
    status TEXT NOT NULL DEFAULT 'todo' CHECK(status IN ('todo','doing','done','dismissed')),
    user_note TEXT NOT NULL DEFAULT '',
    usefulness TEXT CHECK(usefulness IN ('helpful','unhelpful','unsure')),
    completed_at TEXT,
    revision INTEGER NOT NULL DEFAULT 1 CHECK(revision > 0),
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
    CHECK((status='done' AND completed_at IS NOT NULL) OR (status<>'done' AND completed_at IS NULL))
);
CREATE INDEX improvement_status_priority ON improvement_items(status,priority,updated_at,id);
CREATE TABLE improvement_origins (
    id TEXT PRIMARY KEY NOT NULL,
    improvement_id TEXT NOT NULL REFERENCES improvement_items(id) ON DELETE RESTRICT,
    review_run_id TEXT REFERENCES review_runs(id) ON DELETE SET NULL,
    suggestion_key TEXT NOT NULL,
    provenance_label TEXT NOT NULL,
    evidence_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(evidence_json)),
    created_at TEXT NOT NULL,
    UNIQUE(review_run_id,suggestion_key)
);
-- No TTL: retains command results for safe retries after window/service restart.
CREATE TABLE command_receipts (
    request_id TEXT PRIMARY KEY NOT NULL,
    command TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    response_json TEXT NOT NULL CHECK(json_valid(response_json)),
    created_at TEXT NOT NULL
);

CREATE INDEX material_asset ON material_versions(file_asset_id);
CREATE INDEX observations_run ON job_observations(fetch_run_id);
CREATE INDEX opportunity_job_reverse ON opportunity_jobs(job_id);
CREATE INDEX preparations_opportunity ON application_preparations(opportunity_id,updated_at);
CREATE INDEX feedback_account_status ON feedback_items(account_id,status,received_at);
CREATE INDEX feedback_opportunity ON feedback_items(opportunity_id);
CREATE INDEX contexts_job ON interview_context_versions(job_version_id);
CREATE INDEX contexts_resume ON interview_context_versions(resume_version_id);
CREATE INDEX origins_item ON improvement_origins(improvement_id);
CREATE INDEX tasks_checkpoint ON background_tasks(checkpoint_asset_id);

-- Content revisions cannot be edited in place. Explicit purge uses DELETE,
-- after a reference preview; routine UI actions archive instead.
CREATE TRIGGER immutable_job_version BEFORE UPDATE ON job_versions
BEGIN SELECT RAISE(ABORT, 'immutable job version'); END;
CREATE TRIGGER immutable_material_version BEFORE UPDATE ON material_versions
BEGIN SELECT RAISE(ABORT, 'immutable material version'); END;
CREATE TRIGGER immutable_context_version BEFORE UPDATE ON interview_context_versions
BEGIN SELECT RAISE(ABORT, 'immutable interview context'); END;
CREATE TRIGGER immutable_transcript_version BEFORE UPDATE ON transcript_versions
BEGIN SELECT RAISE(ABORT, 'immutable transcript version'); END;
CREATE TRIGGER immutable_transcript_segment BEFORE UPDATE ON transcript_segments
BEGIN SELECT RAISE(ABORT, 'immutable transcript segment'); END;
CREATE TRIGGER immutable_review_report BEFORE UPDATE ON review_reports
BEGIN SELECT RAISE(ABORT, 'immutable review report'); END;
CREATE TRIGGER immutable_application_event BEFORE UPDATE ON application_events
BEGIN SELECT RAISE(ABORT, 'immutable application event'); END;
CREATE TRIGGER immutable_cooldown_note BEFORE UPDATE ON cooldown_notes
BEGIN SELECT RAISE(ABORT, 'append cooldown correction'); END;
