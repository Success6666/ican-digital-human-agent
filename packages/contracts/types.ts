/** Provider identifiers are open-ended so a new external adapter does not require a contract release. */
export type ProviderName = "mock" | "aliyun" | "mofa" | "iflytek" | "fay" | (string & {});

/** Wire status returned by Agent ProviderResponse. */
export type ProviderStatus = string;

export interface ProviderDescriptor {
  /** Agent API field. Optional here so legacy producers using `name` remain source-compatible. */
  provider?: ProviderName;
  configured: boolean;
  status: ProviderStatus;
  detail?: string;
  capabilities: Record<string, boolean>;
  available?: boolean;
  name?: ProviderName;
  displayName?: string;
  label?: string;
  description?: string;
}

export interface AvatarSession {
  sessionId: string;
  provider: ProviderName;
  capabilities: Record<string, boolean>;
  expiresAt: string;
  /** Agent API fields; optional to preserve the v0.1 legacy session shape. */
  userId?: string;
  createdAt?: string;
  status?: "active" | "interrupted" | "closed" | "expired" | string;
  clientParams?: Record<string, unknown>;
  /** Deprecated compatibility alias; Agent API uses `clientParams`. */
  sdkConfig?: Record<string, unknown>;
}

export interface AgentEvent {
  schema_version: "1.0";
  event_id: string;
  run_id: string;
  thread_id?: string | null;
  seq: number;
  ts: string;
  type: string;
  data: Record<string, unknown>;
}
