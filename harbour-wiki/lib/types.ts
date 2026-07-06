// Mirrors Knottra's v1 public contract (the fields the app consumes).

export type SubPoint = { text: string; source_event_seqs: number[] };

export type ConceptNode = {
  id: string;
  title: string;
  detail: string | null;
  modalities: string[];
  time_start: string;
  time_end: string;
  source_event_seqs: number[];
  sub_points: SubPoint[];
  confidence: number;
  created_at_seq: number;
  updated_at_seq: number;
};

export type ConceptLink = {
  id: string;
  from_concept: string;
  to_concept: string;
  kind: string;
  confidence: number;
  updated_at_seq: number;
};

export type RecordOut = {
  session_id: string;
  contract_version: string;
  fused_through_seq: number;
  fused_through_timestamp: string | null;
  concepts: ConceptNode[];
  links: ConceptLink[];
};

export type SearchHit = { concept: ConceptNode; score: number };
export type SearchOut = { session_id: string; query: string; hits: SearchHit[] };

export type EventIn = {
  timestamp: string;
  modality: string;
  content: string;
  confidence: number;
};
