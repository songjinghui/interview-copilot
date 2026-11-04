# 数据字段字典（由 SQL 派生）

生成源：[schema.sql](schema.sql)。业务语义、JSON 形状与事务见[数据库设计](database-design.md)。

重新生成：`python -X utf8 docs/design-checks/validate_design.py --write-reference`。
程序先运行设计检查，仅成功时更新本文。NOT NULL / 默认值按 SQLite 实际 schema 读取；联合唯一、CHECK 与触发器以 SQL 为准。

## application_events

| 字段 | 类型 | 必填 | 默认 | 主键次序 |
|---|---|---|---|---|
| `id` | TEXT | 是 | `None` | 1 |
| `application_id` | TEXT | 是 | `None` | — |
| `revision` | INTEGER | 是 | `None` | — |
| `snapshot_json` | TEXT | 是 | `None` | — |
| `reason` | TEXT | 是 | `None` | — |
| `recorded_at` | TEXT | 是 | `None` | — |

外键（同一编号为复合外键）：

- 0.0 `application_id` → `applications.id`；ON DELETE RESTRICT

索引：

- `sqlite_autoindex_application_events_2`：(application_id, revision)；唯一
- `sqlite_autoindex_application_events_1`：(id)；唯一

## application_preparations

| 字段 | 类型 | 必填 | 默认 | 主键次序 |
|---|---|---|---|---|
| `id` | TEXT | 是 | `None` | 1 |
| `opportunity_id` | TEXT | 是 | `None` | — |
| `job_version_id` | TEXT | 是 | `None` | — |
| `resume_version_id` | TEXT | 否 | `None` | — |
| `resume_exception` | TEXT | 否 | `None` | — |
| `channel` | TEXT | 是 | `None` | — |
| `apply_url` | TEXT | 否 | `None` | — |
| `cooldown_snapshot_json` | TEXT | 是 | `None` | — |
| `cooldown_status` | TEXT | 是 | `None` | — |
| `status` | TEXT | 是 | `'draft'` | — |
| `material_confirmed_at` | TEXT | 否 | `None` | — |
| `cooldown_confirmed_at` | TEXT | 否 | `None` | — |
| `revision` | INTEGER | 是 | `1` | — |
| `created_at` | TEXT | 是 | `None` | — |
| `updated_at` | TEXT | 是 | `None` | — |

外键（同一编号为复合外键）：

- 0.0 `resume_version_id` → `material_versions.id`；ON DELETE RESTRICT
- 1.0 `job_version_id` → `job_versions.id`；ON DELETE RESTRICT
- 2.0 `opportunity_id` → `opportunities.id`；ON DELETE RESTRICT

索引：

- `preparations_opportunity`：(opportunity_id, updated_at)
- `sqlite_autoindex_application_preparations_1`：(id)；唯一

## applications

| 字段 | 类型 | 必填 | 默认 | 主键次序 |
|---|---|---|---|---|
| `id` | TEXT | 是 | `None` | 1 |
| `opportunity_id` | TEXT | 是 | `None` | — |
| `preparation_id` | TEXT | 否 | `None` | — |
| `job_version_id` | TEXT | 是 | `None` | — |
| `resume_version_id` | TEXT | 否 | `None` | — |
| `channel` | TEXT | 是 | `None` | — |
| `outcome` | TEXT | 是 | `None` | — |
| `submitted_at` | TEXT | 否 | `None` | — |
| `evidence_json` | TEXT | 是 | `None` | — |
| `revision` | INTEGER | 是 | `1` | — |
| `created_at` | TEXT | 是 | `None` | — |
| `updated_at` | TEXT | 是 | `None` | — |

外键（同一编号为复合外键）：

- 0.0 `resume_version_id` → `material_versions.id`；ON DELETE RESTRICT
- 1.0 `job_version_id` → `job_versions.id`；ON DELETE RESTRICT
- 2.0 `preparation_id` → `application_preparations.id`；ON DELETE RESTRICT
- 3.0 `opportunity_id` → `opportunities.id`；ON DELETE RESTRICT

索引：

- `applications_opportunity_time`：(opportunity_id, created_at, id)
- `sqlite_autoindex_applications_2`：(opportunity_id, id)；唯一
- `sqlite_autoindex_applications_1`：(id)；唯一

## audio_assets

| 字段 | 类型 | 必填 | 默认 | 主键次序 |
|---|---|---|---|---|
| `id` | TEXT | 是 | `None` | 1 |
| `interview_id` | TEXT | 是 | `None` | — |
| `revision` | INTEGER | 是 | `None` | — |
| `origin` | TEXT | 是 | `None` | — |
| `status` | TEXT | 是 | `None` | — |
| `consent_at` | TEXT | 否 | `None` | — |
| `duration_ms` | INTEGER | 否 | `None` | — |
| `completeness` | TEXT | 是 | `None` | — |
| `created_at` | TEXT | 是 | `None` | — |
| `finalized_at` | TEXT | 否 | `None` | — |

外键（同一编号为复合外键）：

- 0.0 `interview_id` → `interviews.id`；ON DELETE RESTRICT

索引：

- `sqlite_autoindex_audio_assets_3`：(id, revision)；唯一
- `sqlite_autoindex_audio_assets_2`：(interview_id, id)；唯一
- `sqlite_autoindex_audio_assets_1`：(id)；唯一

## audio_parts

| 字段 | 类型 | 必填 | 默认 | 主键次序 |
|---|---|---|---|---|
| `audio_asset_id` | TEXT | 是 | `None` | 1 |
| `ordinal` | INTEGER | 是 | `None` | 2 |
| `file_asset_id` | TEXT | 是 | `None` | — |
| `start_ms` | INTEGER | 是 | `None` | — |
| `end_ms` | INTEGER | 是 | `None` | — |

外键（同一编号为复合外键）：

- 0.0 `file_asset_id` → `file_assets.id`；ON DELETE RESTRICT
- 1.0 `audio_asset_id` → `audio_assets.id`；ON DELETE RESTRICT

索引：

- `sqlite_autoindex_audio_parts_2`：(audio_asset_id, file_asset_id)；唯一
- `sqlite_autoindex_audio_parts_1`：(audio_asset_id, ordinal)；唯一

## background_tasks

| 字段 | 类型 | 必填 | 默认 | 主键次序 |
|---|---|---|---|---|
| `id` | TEXT | 是 | `None` | 1 |
| `kind` | TEXT | 是 | `None` | — |
| `dedup_key` | TEXT | 是 | `None` | — |
| `input_json` | TEXT | 是 | `None` | — |
| `status` | TEXT | 是 | `'queued'` | — |
| `attempt` | INTEGER | 是 | `0` | — |
| `failure_count` | INTEGER | 是 | `0` | — |
| `owner_run_id` | TEXT | 否 | `None` | — |
| `heartbeat_at` | TEXT | 否 | `None` | — |
| `next_retry_at` | TEXT | 否 | `None` | — |
| `checkpoint_asset_id` | TEXT | 否 | `None` | — |
| `progress` | REAL | 否 | `None` | — |
| `stage` | TEXT | 否 | `None` | — |
| `last_error_json` | TEXT | 否 | `None` | — |
| `result_json` | TEXT | 否 | `None` | — |
| `revision` | INTEGER | 是 | `1` | — |
| `created_at` | TEXT | 是 | `None` | — |
| `updated_at` | TEXT | 是 | `None` | — |

外键（同一编号为复合外键）：

- 0.0 `checkpoint_asset_id` → `file_assets.id`；ON DELETE RESTRICT

索引：

- `tasks_checkpoint`：(checkpoint_asset_id)
- `tasks_due`：(status, next_retry_at, created_at)
- `sqlite_autoindex_background_tasks_2`：(dedup_key)；唯一
- `sqlite_autoindex_background_tasks_1`：(id)；唯一

## command_receipts

| 字段 | 类型 | 必填 | 默认 | 主键次序 |
|---|---|---|---|---|
| `request_id` | TEXT | 是 | `None` | 1 |
| `command` | TEXT | 是 | `None` | — |
| `request_hash` | TEXT | 是 | `None` | — |
| `response_json` | TEXT | 是 | `None` | — |
| `created_at` | TEXT | 是 | `None` | — |

外键（同一编号为复合外键）：

无。

索引：

- `sqlite_autoindex_command_receipts_1`：(request_id)；唯一

## cooldown_notes

| 字段 | 类型 | 必填 | 默认 | 主键次序 |
|---|---|---|---|---|
| `id` | TEXT | 是 | `None` | 1 |
| `opportunity_id` | TEXT | 是 | `None` | — |
| `scope` | TEXT | 是 | `None` | — |
| `status` | TEXT | 是 | `None` | — |
| `explanation` | TEXT | 是 | `None` | — |
| `evidence_json` | TEXT | 是 | `None` | — |
| `known_until` | TEXT | 否 | `None` | — |
| `checked_at` | TEXT | 是 | `None` | — |
| `supersedes_id` | TEXT | 否 | `None` | — |

外键（同一编号为复合外键）：

- 0.0 `supersedes_id` → `cooldown_notes.id`；ON DELETE RESTRICT
- 1.0 `opportunity_id` → `opportunities.id`；ON DELETE RESTRICT

索引：

- `cooldown_opportunity_time`：(opportunity_id, checked_at, id)
- `sqlite_autoindex_cooldown_notes_1`：(id)；唯一

## feedback_items

| 字段 | 类型 | 必填 | 默认 | 主键次序 |
|---|---|---|---|---|
| `id` | TEXT | 是 | `None` | 1 |
| `source_key` | TEXT | 是 | `None` | — |
| `account_id` | TEXT | 是 | `None` | — |
| `external_key` | TEXT | 是 | `None` | — |
| `opportunity_id` | TEXT | 否 | `None` | — |
| `text_content` | TEXT | 是 | `None` | — |
| `evidence_asset_id` | TEXT | 否 | `None` | — |
| `occurred_at` | TEXT | 否 | `None` | — |
| `received_at` | TEXT | 是 | `None` | — |
| `proposal_json` | TEXT | 否 | `None` | — |
| `status` | TEXT | 是 | `'unlinked'` | — |
| `revision` | INTEGER | 是 | `1` | — |

外键（同一编号为复合外键）：

- 0.0 `source_key` → `source_accounts.source_key`；ON DELETE RESTRICT
- 0.1 `account_id` → `source_accounts.id`；ON DELETE RESTRICT
- 1.0 `evidence_asset_id` → `file_assets.id`；ON DELETE RESTRICT
- 2.0 `opportunity_id` → `opportunities.id`；ON DELETE RESTRICT
- 3.0 `source_key` → `sources.key`；ON DELETE RESTRICT

索引：

- `feedback_opportunity`：(opportunity_id)
- `feedback_account_status`：(account_id, status, received_at)
- `sqlite_autoindex_feedback_items_3`：(account_id, id)；唯一
- `sqlite_autoindex_feedback_items_2`：(account_id, external_key)；唯一
- `sqlite_autoindex_feedback_items_1`：(id)；唯一

## fetch_runs

| 字段 | 类型 | 必填 | 默认 | 主键次序 |
|---|---|---|---|---|
| `id` | TEXT | 是 | `None` | 1 |
| `task_id` | TEXT | 是 | `None` | — |
| `source_key` | TEXT | 是 | `None` | — |
| `capability` | TEXT | 是 | `None` | — |
| `request_json` | TEXT | 是 | `None` | — |
| `applied_filters_json` | TEXT | 是 | `'{}'` | — |
| `status` | TEXT | 是 | `None` | — |
| `error_json` | TEXT | 否 | `None` | — |
| `started_at` | TEXT | 是 | `None` | — |
| `finished_at` | TEXT | 否 | `None` | — |

外键（同一编号为复合外键）：

- 0.0 `source_key` → `sources.key`；ON DELETE RESTRICT
- 1.0 `task_id` → `background_tasks.id`；ON DELETE RESTRICT

索引：

- `fetch_source_time`：(source_key, started_at)
- `sqlite_autoindex_fetch_runs_1`：(id)；唯一

## file_assets

| 字段 | 类型 | 必填 | 默认 | 主键次序 |
|---|---|---|---|---|
| `id` | TEXT | 是 | `None` | 1 |
| `kind` | TEXT | 是 | `None` | — |
| `status` | TEXT | 是 | `'staging'` | — |
| `relative_path` | TEXT | 是 | `None` | — |
| `original_name` | TEXT | 是 | `None` | — |
| `media_type` | TEXT | 是 | `None` | — |
| `byte_size` | INTEGER | 否 | `None` | — |
| `sha256` | TEXT | 否 | `None` | — |
| `intent_json` | TEXT | 是 | `None` | — |
| `created_at` | TEXT | 是 | `None` | — |
| `finalized_at` | TEXT | 否 | `None` | — |

外键（同一编号为复合外键）：

无。

索引：

- `sqlite_autoindex_file_assets_2`：(relative_path)；唯一
- `sqlite_autoindex_file_assets_1`：(id)；唯一

## improvement_items

| 字段 | 类型 | 必填 | 默认 | 主键次序 |
|---|---|---|---|---|
| `id` | TEXT | 是 | `None` | 1 |
| `opportunity_id` | TEXT | 否 | `None` | — |
| `title` | TEXT | 是 | `None` | — |
| `action` | TEXT | 是 | `None` | — |
| `category` | TEXT | 否 | `None` | — |
| `priority` | TEXT | 是 | `'medium'` | — |
| `status` | TEXT | 是 | `'todo'` | — |
| `user_note` | TEXT | 是 | `''` | — |
| `usefulness` | TEXT | 否 | `None` | — |
| `completed_at` | TEXT | 否 | `None` | — |
| `revision` | INTEGER | 是 | `1` | — |
| `created_at` | TEXT | 是 | `None` | — |
| `updated_at` | TEXT | 是 | `None` | — |

外键（同一编号为复合外键）：

- 0.0 `opportunity_id` → `opportunities.id`；ON DELETE RESTRICT

索引：

- `improvement_status_priority`：(status, priority, updated_at, id)
- `sqlite_autoindex_improvement_items_1`：(id)；唯一

## improvement_origins

| 字段 | 类型 | 必填 | 默认 | 主键次序 |
|---|---|---|---|---|
| `id` | TEXT | 是 | `None` | 1 |
| `improvement_id` | TEXT | 是 | `None` | — |
| `review_run_id` | TEXT | 否 | `None` | — |
| `suggestion_key` | TEXT | 是 | `None` | — |
| `provenance_label` | TEXT | 是 | `None` | — |
| `evidence_json` | TEXT | 是 | `'[]'` | — |
| `created_at` | TEXT | 是 | `None` | — |

外键（同一编号为复合外键）：

- 0.0 `review_run_id` → `review_runs.id`；ON DELETE SET NULL
- 1.0 `improvement_id` → `improvement_items.id`；ON DELETE RESTRICT

索引：

- `origins_item`：(improvement_id)
- `sqlite_autoindex_improvement_origins_2`：(review_run_id, suggestion_key)；唯一
- `sqlite_autoindex_improvement_origins_1`：(id)；唯一

## interview_context_versions

| 字段 | 类型 | 必填 | 默认 | 主键次序 |
|---|---|---|---|---|
| `id` | TEXT | 是 | `None` | 1 |
| `interview_id` | TEXT | 是 | `None` | — |
| `revision` | INTEGER | 是 | `None` | — |
| `job_title` | TEXT | 是 | `None` | — |
| `job_version_id` | TEXT | 否 | `None` | — |
| `resume_version_id` | TEXT | 否 | `None` | — |
| `missing_json` | TEXT | 是 | `'[]'` | — |
| `created_at` | TEXT | 是 | `None` | — |

外键（同一编号为复合外键）：

- 0.0 `resume_version_id` → `material_versions.id`；ON DELETE RESTRICT
- 1.0 `job_version_id` → `job_versions.id`；ON DELETE RESTRICT
- 2.0 `interview_id` → `interviews.id`；ON DELETE RESTRICT

索引：

- `contexts_resume`：(resume_version_id)
- `contexts_job`：(job_version_id)
- `sqlite_autoindex_interview_context_versions_3`：(interview_id, id)；唯一
- `sqlite_autoindex_interview_context_versions_2`：(interview_id, revision)；唯一
- `sqlite_autoindex_interview_context_versions_1`：(id)；唯一

## interviews

| 字段 | 类型 | 必填 | 默认 | 主键次序 |
|---|---|---|---|---|
| `id` | TEXT | 是 | `None` | 1 |
| `opportunity_id` | TEXT | 是 | `None` | — |
| `application_id` | TEXT | 否 | `None` | — |
| `label` | TEXT | 是 | `None` | — |
| `starts_at` | TEXT | 否 | `None` | — |
| `ends_at` | TEXT | 否 | `None` | — |
| `time_zone` | TEXT | 是 | `None` | — |
| `format` | TEXT | 是 | `None` | — |
| `location` | TEXT | 否 | `None` | — |
| `status` | TEXT | 是 | `'planned'` | — |
| `source_feedback_id` | TEXT | 否 | `None` | — |
| `source_account_id` | TEXT | 否 | `None` | — |
| `source_event_key` | TEXT | 否 | `None` | — |
| `revision` | INTEGER | 是 | `1` | — |
| `created_at` | TEXT | 是 | `None` | — |
| `updated_at` | TEXT | 是 | `None` | — |

外键（同一编号为复合外键）：

- 0.0 `source_account_id` → `feedback_items.account_id`；ON DELETE RESTRICT
- 0.1 `source_feedback_id` → `feedback_items.id`；ON DELETE RESTRICT
- 1.0 `opportunity_id` → `applications.opportunity_id`；ON DELETE RESTRICT
- 1.1 `application_id` → `applications.id`；ON DELETE RESTRICT
- 2.0 `source_account_id` → `source_accounts.id`；ON DELETE RESTRICT
- 3.0 `opportunity_id` → `opportunities.id`；ON DELETE RESTRICT

索引：

- `interviews_schedule`：(status, starts_at, id)
- `sqlite_autoindex_interviews_2`：(source_account_id, source_event_key)；唯一
- `sqlite_autoindex_interviews_1`：(id)；唯一

## job_observations

| 字段 | 类型 | 必填 | 默认 | 主键次序 |
|---|---|---|---|---|
| `id` | TEXT | 是 | `None` | 1 |
| `fetch_run_id` | TEXT | 否 | `None` | — |
| `job_id` | TEXT | 是 | `None` | — |
| `version_id` | TEXT | 是 | `None` | — |
| `observed_at` | TEXT | 是 | `None` | — |
| `method` | TEXT | 是 | `None` | — |
| `observed_json` | TEXT | 是 | `None` | — |
| `raw_asset_id` | TEXT | 否 | `None` | — |

外键（同一编号为复合外键）：

- 0.0 `job_id` → `job_versions.job_id`；ON DELETE RESTRICT
- 0.1 `version_id` → `job_versions.id`；ON DELETE RESTRICT
- 1.0 `raw_asset_id` → `file_assets.id`；ON DELETE RESTRICT
- 2.0 `job_id` → `jobs.id`；ON DELETE RESTRICT
- 3.0 `fetch_run_id` → `fetch_runs.id`；ON DELETE RESTRICT

索引：

- `observations_run`：(fetch_run_id)
- `observations_job_time`：(job_id, observed_at, id)
- `sqlite_autoindex_job_observations_1`：(id)；唯一

## job_versions

| 字段 | 类型 | 必填 | 默认 | 主键次序 |
|---|---|---|---|---|
| `id` | TEXT | 是 | `None` | 1 |
| `job_id` | TEXT | 是 | `None` | — |
| `revision` | INTEGER | 是 | `None` | — |
| `title` | TEXT | 是 | `None` | — |
| `company_name` | TEXT | 是 | `None` | — |
| `original_url` | TEXT | 否 | `None` | — |
| `apply_url` | TEXT | 否 | `None` | — |
| `locations_json` | TEXT | 是 | `'[]'` | — |
| `salary_text` | TEXT | 否 | `None` | — |
| `experience_text` | TEXT | 否 | `None` | — |
| `education_text` | TEXT | 否 | `None` | — |
| `description_text` | TEXT | 否 | `None` | — |
| `requirements_text` | TEXT | 否 | `None` | — |
| `completeness` | TEXT | 是 | `None` | — |
| `availability` | TEXT | 是 | `'unknown'` | — |
| `content_hash` | TEXT | 是 | `None` | — |
| `created_at` | TEXT | 是 | `None` | — |

外键（同一编号为复合外键）：

- 0.0 `job_id` → `jobs.id`；ON DELETE RESTRICT

索引：

- `versions_hash`：(job_id, content_hash)
- `sqlite_autoindex_job_versions_3`：(job_id, id)；唯一
- `sqlite_autoindex_job_versions_2`：(job_id, revision)；唯一
- `sqlite_autoindex_job_versions_1`：(id)；唯一

## jobs

| 字段 | 类型 | 必填 | 默认 | 主键次序 |
|---|---|---|---|---|
| `id` | TEXT | 是 | `None` | 1 |
| `source_key` | TEXT | 是 | `None` | — |
| `external_key` | TEXT | 是 | `None` | — |
| `current_version_id` | TEXT | 否 | `None` | — |
| `last_complete_version_id` | TEXT | 否 | `None` | — |
| `first_observed_at` | TEXT | 是 | `None` | — |
| `last_observed_at` | TEXT | 是 | `None` | — |
| `archived_at` | TEXT | 否 | `None` | — |

外键（同一编号为复合外键）：

- 0.0 `id` → `job_versions.job_id`；ON DELETE NO ACTION
- 0.1 `last_complete_version_id` → `job_versions.id`；ON DELETE NO ACTION
- 1.0 `id` → `job_versions.job_id`；ON DELETE NO ACTION
- 1.1 `current_version_id` → `job_versions.id`；ON DELETE NO ACTION
- 2.0 `source_key` → `sources.key`；ON DELETE RESTRICT

索引：

- `jobs_recent`：(last_observed_at, id)
- `sqlite_autoindex_jobs_2`：(source_key, external_key)；唯一
- `sqlite_autoindex_jobs_1`：(id)；唯一

## material_versions

| 字段 | 类型 | 必填 | 默认 | 主键次序 |
|---|---|---|---|---|
| `id` | TEXT | 是 | `None` | 1 |
| `material_id` | TEXT | 是 | `None` | — |
| `revision` | INTEGER | 是 | `None` | — |
| `file_asset_id` | TEXT | 否 | `None` | — |
| `text_content` | TEXT | 是 | `None` | — |
| `content_hash` | TEXT | 是 | `None` | — |
| `fact_snapshot_json` | TEXT | 是 | `None` | — |
| `created_at` | TEXT | 是 | `None` | — |

外键（同一编号为复合外键）：

- 0.0 `file_asset_id` → `file_assets.id`；ON DELETE RESTRICT
- 1.0 `material_id` → `materials.id`；ON DELETE RESTRICT

索引：

- `material_asset`：(file_asset_id)
- `sqlite_autoindex_material_versions_2`：(material_id, revision)；唯一
- `sqlite_autoindex_material_versions_1`：(id)；唯一

## materials

| 字段 | 类型 | 必填 | 默认 | 主键次序 |
|---|---|---|---|---|
| `id` | TEXT | 是 | `None` | 1 |
| `label` | TEXT | 是 | `None` | — |
| `archived_at` | TEXT | 否 | `None` | — |
| `created_at` | TEXT | 是 | `None` | — |

外键（同一编号为复合外键）：

无。

索引：

- `sqlite_autoindex_materials_1`：(id)；唯一

## opportunities

| 字段 | 类型 | 必填 | 默认 | 主键次序 |
|---|---|---|---|---|
| `id` | TEXT | 是 | `None` | 1 |
| `title` | TEXT | 是 | `None` | — |
| `company_name` | TEXT | 是 | `None` | — |
| `status` | TEXT | 是 | `'saved'` | — |
| `note` | TEXT | 是 | `''` | — |
| `revision` | INTEGER | 是 | `1` | — |
| `created_at` | TEXT | 是 | `None` | — |
| `updated_at` | TEXT | 是 | `None` | — |

外键（同一编号为复合外键）：

无。

索引：

- `opportunities_status_time`：(status, updated_at, id)
- `sqlite_autoindex_opportunities_1`：(id)；唯一

## opportunity_jobs

| 字段 | 类型 | 必填 | 默认 | 主键次序 |
|---|---|---|---|---|
| `opportunity_id` | TEXT | 是 | `None` | 1 |
| `job_id` | TEXT | 是 | `None` | 2 |
| `basis_json` | TEXT | 是 | `None` | — |
| `created_at` | TEXT | 是 | `None` | — |

外键（同一编号为复合外键）：

- 0.0 `job_id` → `jobs.id`；ON DELETE RESTRICT
- 1.0 `opportunity_id` → `opportunities.id`；ON DELETE RESTRICT

索引：

- `opportunity_job_reverse`：(job_id)
- `sqlite_autoindex_opportunity_jobs_1`：(opportunity_id, job_id)；唯一

## profile_facts

| 字段 | 类型 | 必填 | 默认 | 主键次序 |
|---|---|---|---|---|
| `id` | TEXT | 是 | `None` | 1 |
| `kind` | TEXT | 是 | `None` | — |
| `content_json` | TEXT | 是 | `None` | — |
| `status` | TEXT | 是 | `'draft'` | — |
| `provenance_json` | TEXT | 是 | `None` | — |
| `confirmed_at` | TEXT | 否 | `None` | — |
| `revision` | INTEGER | 是 | `1` | — |
| `created_at` | TEXT | 是 | `None` | — |
| `updated_at` | TEXT | 是 | `None` | — |

外键（同一编号为复合外键）：

无。

索引：

- `sqlite_autoindex_profile_facts_1`：(id)；唯一

## profile_targets

| 字段 | 类型 | 必填 | 默认 | 主键次序 |
|---|---|---|---|---|
| `id` | TEXT | 是 | `None` | 1 |
| `label` | TEXT | 是 | `None` | — |
| `criteria_json` | TEXT | 是 | `None` | — |
| `active` | INTEGER | 是 | `1` | — |
| `revision` | INTEGER | 是 | `1` | — |
| `created_at` | TEXT | 是 | `None` | — |
| `updated_at` | TEXT | 是 | `None` | — |

外键（同一编号为复合外键）：

无。

索引：

- `sqlite_autoindex_profile_targets_1`：(id)；唯一

## reminders

| 字段 | 类型 | 必填 | 默认 | 主键次序 |
|---|---|---|---|---|
| `id` | TEXT | 是 | `None` | 1 |
| `interview_id` | TEXT | 否 | `None` | — |
| `cooldown_note_id` | TEXT | 否 | `None` | — |
| `scheduled_for` | TEXT | 是 | `None` | — |
| `status` | TEXT | 是 | `'pending'` | — |
| `delivered_at` | TEXT | 否 | `None` | — |
| `created_at` | TEXT | 是 | `None` | — |

外键（同一编号为复合外键）：

- 0.0 `cooldown_note_id` → `cooldown_notes.id`；ON DELETE RESTRICT
- 1.0 `interview_id` → `interviews.id`；ON DELETE RESTRICT

索引：

- `reminders_due`：(status, scheduled_for, id)
- `sqlite_autoindex_reminders_1`：(id)；唯一

## review_reports

| 字段 | 类型 | 必填 | 默认 | 主键次序 |
|---|---|---|---|---|
| `id` | TEXT | 是 | `None` | 1 |
| `review_run_id` | TEXT | 是 | `None` | — |
| `body_json` | TEXT | 是 | `None` | — |
| `created_at` | TEXT | 是 | `None` | — |

外键（同一编号为复合外键）：

- 0.0 `review_run_id` → `review_runs.id`；ON DELETE RESTRICT

索引：

- `sqlite_autoindex_review_reports_2`：(review_run_id)；唯一
- `sqlite_autoindex_review_reports_1`：(id)；唯一

## review_runs

| 字段 | 类型 | 必填 | 默认 | 主键次序 |
|---|---|---|---|---|
| `id` | TEXT | 是 | `None` | 1 |
| `task_id` | TEXT | 是 | `None` | — |
| `interview_id` | TEXT | 是 | `None` | — |
| `context_version_id` | TEXT | 是 | `None` | — |
| `transcript_version_id` | TEXT | 是 | `None` | — |
| `model_config_json` | TEXT | 是 | `None` | — |
| `prompt_revision` | TEXT | 是 | `None` | — |
| `created_at` | TEXT | 是 | `None` | — |

外键（同一编号为复合外键）：

- 0.0 `interview_id` → `transcript_versions.interview_id`；ON DELETE RESTRICT
- 0.1 `transcript_version_id` → `transcript_versions.id`；ON DELETE RESTRICT
- 1.0 `interview_id` → `interview_context_versions.interview_id`；ON DELETE RESTRICT
- 1.1 `context_version_id` → `interview_context_versions.id`；ON DELETE RESTRICT
- 2.0 `interview_id` → `interviews.id`；ON DELETE RESTRICT
- 3.0 `task_id` → `background_tasks.id`；ON DELETE RESTRICT

索引：

- `sqlite_autoindex_review_runs_2`：(task_id)；唯一
- `sqlite_autoindex_review_runs_1`：(id)；唯一

## schema_migrations

| 字段 | 类型 | 必填 | 默认 | 主键次序 |
|---|---|---|---|---|
| `version` | INTEGER | 是 | `None` | 1 |
| `checksum` | TEXT | 是 | `None` | — |
| `applied_at` | TEXT | 是 | `None` | — |

外键（同一编号为复合外键）：

无。

索引：

主键 rowid 定位，无附加索引。

## search_matches

| 字段 | 类型 | 必填 | 默认 | 主键次序 |
|---|---|---|---|---|
| `task_id` | TEXT | 是 | `None` | 1 |
| `job_version_id` | TEXT | 是 | `None` | 2 |
| `assessment_json` | TEXT | 是 | `None` | — |

外键（同一编号为复合外键）：

- 0.0 `job_version_id` → `job_versions.id`；ON DELETE RESTRICT
- 1.0 `task_id` → `background_tasks.id`；ON DELETE RESTRICT

索引：

- `sqlite_autoindex_search_matches_1`：(task_id, job_version_id)；唯一

## settings

| 字段 | 类型 | 必填 | 默认 | 主键次序 |
|---|---|---|---|---|
| `key` | TEXT | 是 | `None` | 1 |
| `value_json` | TEXT | 是 | `None` | — |
| `revision` | INTEGER | 是 | `1` | — |
| `updated_at` | TEXT | 是 | `None` | — |

外键（同一编号为复合外键）：

无。

索引：

- `sqlite_autoindex_settings_1`：(key)；唯一

## source_accounts

| 字段 | 类型 | 必填 | 默认 | 主键次序 |
|---|---|---|---|---|
| `id` | TEXT | 是 | `None` | 1 |
| `source_key` | TEXT | 是 | `None` | — |
| `account_key` | TEXT | 是 | `None` | — |
| `display_name` | TEXT | 是 | `None` | — |
| `credential_ref` | TEXT | 否 | `None` | — |
| `connection_state` | TEXT | 是 | `'unconfigured'` | — |
| `updated_at` | TEXT | 是 | `None` | — |

外键（同一编号为复合外键）：

- 0.0 `source_key` → `sources.key`；ON DELETE RESTRICT

索引：

- `sqlite_autoindex_source_accounts_3`：(source_key, id)；唯一
- `sqlite_autoindex_source_accounts_2`：(source_key, account_key)；唯一
- `sqlite_autoindex_source_accounts_1`：(id)；唯一

## source_capabilities

| 字段 | 类型 | 必填 | 默认 | 主键次序 |
|---|---|---|---|---|
| `source_key` | TEXT | 是 | `None` | 1 |
| `capability` | TEXT | 是 | `None` | 2 |
| `enabled` | INTEGER | 是 | `0` | — |
| `evidence_status` | TEXT | 是 | `None` | — |
| `evidence_stage` | TEXT | 是 | `None` | — |
| `evidence_json` | TEXT | 是 | `None` | — |
| `verified_at` | TEXT | 否 | `None` | — |

外键（同一编号为复合外键）：

- 0.0 `source_key` → `sources.key`；ON DELETE RESTRICT

索引：

- `sqlite_autoindex_source_capabilities_1`：(source_key, capability)；唯一

## sources

| 字段 | 类型 | 必填 | 默认 | 主键次序 |
|---|---|---|---|---|
| `key` | TEXT | 是 | `None` | 1 |
| `display_name` | TEXT | 是 | `None` | — |
| `adapter_version` | TEXT | 是 | `None` | — |
| `enabled` | INTEGER | 是 | `0` | — |
| `config_json` | TEXT | 是 | `'{}'` | — |
| `credential_ref` | TEXT | 否 | `None` | — |
| `connection_state` | TEXT | 是 | `'unconfigured'` | — |
| `revision` | INTEGER | 是 | `1` | — |
| `updated_at` | TEXT | 是 | `None` | — |

外键（同一编号为复合外键）：

无。

索引：

- `sqlite_autoindex_sources_1`：(key)；唯一

## sync_cursors

| 字段 | 类型 | 必填 | 默认 | 主键次序 |
|---|---|---|---|---|
| `account_id` | TEXT | 是 | `None` | 1 |
| `stream_key` | TEXT | 是 | `None` | 2 |
| `cursor_json` | TEXT | 是 | `None` | — |
| `last_success_at` | TEXT | 否 | `None` | — |

外键（同一编号为复合外键）：

- 0.0 `account_id` → `source_accounts.id`；ON DELETE RESTRICT

索引：

- `sqlite_autoindex_sync_cursors_1`：(account_id, stream_key)；唯一

## transcript_segments

| 字段 | 类型 | 必填 | 默认 | 主键次序 |
|---|---|---|---|---|
| `version_id` | TEXT | 是 | `None` | 1 |
| `interview_id` | TEXT | 是 | `None` | — |
| `segment_key` | TEXT | 是 | `None` | 2 |
| `ordinal` | INTEGER | 是 | `None` | — |
| `speaker` | TEXT | 是 | `None` | — |
| `text_content` | TEXT | 是 | `None` | — |
| `audio_asset_id` | TEXT | 否 | `None` | — |
| `source_version_id` | TEXT | 否 | `None` | — |
| `source_segment_key` | TEXT | 否 | `None` | — |
| `start_ms` | INTEGER | 否 | `None` | — |
| `end_ms` | INTEGER | 否 | `None` | — |

外键（同一编号为复合外键）：

- 0.0 `source_version_id` → `transcript_segments.version_id`；ON DELETE RESTRICT
- 0.1 `source_segment_key` → `transcript_segments.segment_key`；ON DELETE RESTRICT
- 1.0 `interview_id` → `transcript_versions.interview_id`；ON DELETE RESTRICT
- 1.1 `source_version_id` → `transcript_versions.id`；ON DELETE RESTRICT
- 2.0 `interview_id` → `audio_assets.interview_id`；ON DELETE RESTRICT
- 2.1 `audio_asset_id` → `audio_assets.id`；ON DELETE RESTRICT
- 3.0 `interview_id` → `transcript_versions.interview_id`；ON DELETE RESTRICT
- 3.1 `version_id` → `transcript_versions.id`；ON DELETE RESTRICT
- 4.0 `version_id` → `transcript_versions.id`；ON DELETE RESTRICT

索引：

- `sqlite_autoindex_transcript_segments_2`：(version_id, ordinal)；唯一
- `sqlite_autoindex_transcript_segments_1`：(version_id, segment_key)；唯一

## transcript_versions

| 字段 | 类型 | 必填 | 默认 | 主键次序 |
|---|---|---|---|---|
| `id` | TEXT | 是 | `None` | 1 |
| `interview_id` | TEXT | 是 | `None` | — |
| `revision` | INTEGER | 是 | `None` | — |
| `audio_asset_id` | TEXT | 否 | `None` | — |
| `origin` | TEXT | 是 | `None` | — |
| `parent_version_id` | TEXT | 否 | `None` | — |
| `content_hash` | TEXT | 是 | `None` | — |
| `created_at` | TEXT | 是 | `None` | — |

外键（同一编号为复合外键）：

- 0.0 `interview_id` → `transcript_versions.interview_id`；ON DELETE RESTRICT
- 0.1 `parent_version_id` → `transcript_versions.id`；ON DELETE RESTRICT
- 1.0 `interview_id` → `audio_assets.interview_id`；ON DELETE RESTRICT
- 1.1 `audio_asset_id` → `audio_assets.id`；ON DELETE RESTRICT
- 2.0 `interview_id` → `interviews.id`；ON DELETE RESTRICT

索引：

- `sqlite_autoindex_transcript_versions_3`：(interview_id, id)；唯一
- `sqlite_autoindex_transcript_versions_2`：(interview_id, revision)；唯一
- `sqlite_autoindex_transcript_versions_1`：(id)；唯一

## transcription_jobs

| 字段 | 类型 | 必填 | 默认 | 主键次序 |
|---|---|---|---|---|
| `task_id` | TEXT | 是 | `None` | 1 |
| `audio_asset_id` | TEXT | 是 | `None` | — |
| `asset_revision` | INTEGER | 是 | `None` | — |
| `config_hash` | TEXT | 是 | `None` | — |
| `config_json` | TEXT | 是 | `None` | — |
| `request_generation` | INTEGER | 是 | `None` | — |
| `result_version_id` | TEXT | 否 | `None` | — |

外键（同一编号为复合外键）：

- 0.0 `audio_asset_id` → `audio_assets.id`；ON DELETE RESTRICT
- 0.1 `asset_revision` → `audio_assets.revision`；ON DELETE RESTRICT
- 1.0 `result_version_id` → `transcript_versions.id`；ON DELETE RESTRICT
- 2.0 `task_id` → `background_tasks.id`；ON DELETE RESTRICT

索引：

- `sqlite_autoindex_transcription_jobs_2`：(audio_asset_id, asset_revision, config_hash, request_generation)；唯一
- `sqlite_autoindex_transcription_jobs_1`：(task_id)；唯一
