import { q } from "@/lib/db";

export type CaptureMoment = {
  courseId: string;
  courseName: string;
  lecture: number;
  slot: number;
  startsAt: string;
  endsAt: string;
};

export type CaptureHeartbeat = {
  agentId: string;
  hostname: string;
  schedulerStatus: string;
  sessionId?: string | null;
  current?: CaptureMoment | null;
  next?: CaptureMoment | null;
  audioStatus: string;
  cameraStatus: string;
  zoomStatus: string;
  outboxPending: number;
  errors: string[];
};

export type CommandResult = {
  id: number;
  ok: boolean;
  message?: string;
};

type CommandRow = {
  id: string;
  agent_id: string;
  kind: "stop" | "extend" | "skip";
  payload: Record<string, unknown>;
  status: "pending" | "acknowledged" | "failed";
  created_at: Date;
  delivered_at: Date | null;
  completed_at: Date | null;
  result: string | null;
  error: string | null;
};

export function captureOperatorAuthorized(key: string | null | undefined): boolean {
  const token = process.env.CAPTURE_DASHBOARD_TOKEN ?? process.env.MCP_BEARER_TOKEN;
  return Boolean(token && key && key === token);
}

export async function recordHeartbeat(value: CaptureHeartbeat): Promise<void> {
  const current = value.current;
  const next = value.next;
  await q(
    `INSERT INTO harbour_wiki.capture_agent (
       agent_id, hostname, scheduler_status, session_id,
       current_course_id, current_course_name, current_lecture, current_slot,
       current_started_at, current_ends_at,
       next_course_id, next_course_name, next_lecture, next_slot,
       next_starts_at, next_ends_at,
       audio_status, camera_status, zoom_status, outbox_pending, errors, updated_at
     ) VALUES (
       $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11,
       $12, $13, $14, $15, $16, $17, $18, $19, $20, $21::jsonb, now()
     )
     ON CONFLICT (agent_id) DO UPDATE SET
       hostname = EXCLUDED.hostname,
       scheduler_status = EXCLUDED.scheduler_status,
       session_id = EXCLUDED.session_id,
       current_course_id = EXCLUDED.current_course_id,
       current_course_name = EXCLUDED.current_course_name,
       current_lecture = EXCLUDED.current_lecture,
       current_slot = EXCLUDED.current_slot,
       current_started_at = EXCLUDED.current_started_at,
       current_ends_at = EXCLUDED.current_ends_at,
       next_course_id = EXCLUDED.next_course_id,
       next_course_name = EXCLUDED.next_course_name,
       next_lecture = EXCLUDED.next_lecture,
       next_slot = EXCLUDED.next_slot,
       next_starts_at = EXCLUDED.next_starts_at,
       next_ends_at = EXCLUDED.next_ends_at,
       audio_status = EXCLUDED.audio_status,
       camera_status = EXCLUDED.camera_status,
       zoom_status = EXCLUDED.zoom_status,
       outbox_pending = EXCLUDED.outbox_pending,
       errors = EXCLUDED.errors,
       updated_at = now()`,
    [
      value.agentId,
      value.hostname,
      value.schedulerStatus,
      value.sessionId ?? null,
      current?.courseId ?? null,
      current?.courseName ?? null,
      current?.lecture ?? null,
      current?.slot ?? null,
      current?.startsAt ?? null,
      current?.endsAt ?? null,
      next?.courseId ?? null,
      next?.courseName ?? null,
      next?.lecture ?? null,
      next?.slot ?? null,
      next?.startsAt ?? null,
      next?.endsAt ?? null,
      value.audioStatus,
      value.cameraStatus,
      value.zoomStatus,
      value.outboxPending,
      JSON.stringify(value.errors.slice(-20)),
    ],
  );
}

export async function acknowledgeCommands(results: CommandResult[]): Promise<void> {
  for (const item of results) {
    await q(
      `UPDATE harbour_wiki.capture_command
       SET status = $2, completed_at = now(), result = $3, error = $4
       WHERE id = $1 AND status = 'pending'`,
      [
        item.id,
        item.ok ? "acknowledged" : "failed",
        item.ok ? item.message ?? "done" : null,
        item.ok ? null : item.message ?? "command failed",
      ],
    );
  }
}

export async function pendingCommands(agentId: string) {
  const rows = await q<CommandRow>(
    `UPDATE harbour_wiki.capture_command
     SET delivered_at = COALESCE(delivered_at, now())
     WHERE id IN (
       SELECT id FROM harbour_wiki.capture_command
       WHERE agent_id = $1 AND status = 'pending'
       ORDER BY created_at ASC LIMIT 20
     )
     RETURNING *`,
    [agentId],
  );
  return rows
    .sort((a, b) => Number(a.id) - Number(b.id))
    .map((row) => ({ id: Number(row.id), kind: row.kind, payload: row.payload }));
}

export async function enqueueCommand(
  agentId: string,
  kind: "stop" | "extend" | "skip",
  payload: Record<string, unknown> = {},
) {
  const [row] = await q<CommandRow>(
    `INSERT INTO harbour_wiki.capture_command (agent_id, kind, payload)
     VALUES ($1, $2, $3::jsonb) RETURNING *`,
    [agentId, kind, JSON.stringify(payload)],
  );
  return serializeCommand(row);
}

function serializeCommand(row: CommandRow) {
  return {
    id: Number(row.id),
    agentId: row.agent_id,
    kind: row.kind,
    payload: row.payload,
    status: row.status,
    createdAt: row.created_at,
    deliveredAt: row.delivered_at,
    completedAt: row.completed_at,
    result: row.result,
    error: row.error,
  };
}

export async function captureDashboardData() {
  const agents = await q<Record<string, unknown>>(
    `SELECT ca.*,
       COALESCE(events.last_event_at, ca.updated_at) AS last_event_at
     FROM harbour_wiki.capture_agent ca
     LEFT JOIN LATERAL (
       SELECT max(last_seen_at) AS last_event_at
       FROM harbour_wiki.course_session
       WHERE session_id = ca.session_id
     ) events ON true
     ORDER BY ca.updated_at DESC`,
  );
  const commands = await q<CommandRow>(
    `SELECT * FROM harbour_wiki.capture_command
     ORDER BY created_at DESC LIMIT 50`,
  );
  return { agents, commands: commands.map(serializeCommand), serverTime: new Date() };
}
