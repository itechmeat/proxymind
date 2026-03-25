export type SourceType =
  | "markdown"
  | "txt"
  | "pdf"
  | "docx"
  | "html"
  | "image"
  | "audio"
  | "video";

export type SourceStatus =
  | "pending"
  | "processing"
  | "ready"
  | "failed"
  | "deleted";

export type SnapshotStatus = "draft" | "published" | "active" | "archived";

export type RetrievalMode = "hybrid" | "dense" | "sparse";

export interface SourceListItem {
  id: string;
  title: string;
  source_type: SourceType;
  status: SourceStatus;
  description: string | null;
  public_url: string | null;
  file_size_bytes: number | null;
  language: string | null;
  created_at: string;
}

export interface SourceUploadMetadata {
  title: string;
  description?: string | null;
  public_url?: string | null;
  catalog_item_id?: string | null;
  language?: string | null;
}

export interface SourceUploadResponse {
  source_id: string;
  task_id: string;
  status: string;
  file_path: string;
  message: string;
}

export interface SourceDeleteResponse {
  id: string;
  title: string;
  source_type: SourceType;
  status: SourceStatus;
  deleted_at: string | null;
  warnings: string[];
}

export interface AdminTaskStatus {
  id: string;
  task_type: string;
  status: string;
  source_id: string | null;
  progress: number | null;
  error_message: string | null;
  result_metadata: Record<string, unknown> | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
}

export interface SnapshotResponse {
  id: string;
  agent_id: string | null;
  knowledge_base_id: string | null;
  name: string;
  description: string | null;
  status: SnapshotStatus;
  published_at: string | null;
  activated_at: string | null;
  archived_at: string | null;
  chunk_count: number;
  created_at: string;
  updated_at: string;
}

export interface RollbackSnapshotResponse {
  id: string;
  name: string;
  status: SnapshotStatus;
  published_at: string | null;
  activated_at: string | null;
}

export interface RollbackResponse {
  rolled_back_from: RollbackSnapshotResponse;
  rolled_back_to: RollbackSnapshotResponse;
}

export interface DraftTestAnchor {
  page: number | null;
  chapter: string | null;
  section: string | null;
  timecode: string | null;
}

export interface DraftTestResult {
  chunk_id: string;
  source_id: string;
  source_title: string | null;
  text_content: string;
  score: number;
  anchor: DraftTestAnchor;
}

export interface DraftTestResponse {
  snapshot_id: string;
  snapshot_name: string;
  query: string;
  mode: RetrievalMode;
  results: DraftTestResult[];
  total_chunks_in_draft: number;
}
