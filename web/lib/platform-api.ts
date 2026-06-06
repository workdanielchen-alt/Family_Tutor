// ── Types ────────────────────────────────────────────────────

import type { TeachQuestion, TeachEvaluation, KnowledgePointSummary } from "./quiz-types";

export interface MasterySummary {
  total_questions: number;
  accuracy: number;
  mastered: number;
  total_kp: number;
}

export interface WeakPoint {
  kp_id: string;
  level: number;
  total: number;
  correct: number;
}

export interface WrongAnswer {
  question: string;
  user_answer: string;
  correct_answer: string;
  kp_id: string;
}

export interface PeriodStats {
  total: number;
  accuracy: number;
  per_day: { date: string; total: number }[];
}

export interface PracticeQuestion {
  question: string;
  question_type?: string;
  options?: Record<string, string>;
  correct_answer: string;
  explanation?: string;
  difficulty?: string;
  kp_id?: string;
}

// ── HTTP helpers ─────────────────────────────────────────────

const BASE = "/api/platform";

async function apiGet<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`);
  if (!res.ok) throw new Error(`请求失败 (${res.status})`);
  return res.json();
}

async function apiPost<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`请求失败 (${res.status})`);
  return res.json();
}

async function apiPostText(path: string, body: unknown): Promise<string> {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`请求失败 (${res.status})`);
  return res.text();
}

// ── Mastery / Learner ───────────────────────────────────────

export async function listLearners(): Promise<string[]> {
  return apiGet<string[]>("/mastery/");
}

export async function fetchMasterySummary(
  learnerId: string,
): Promise<MasterySummary> {
  return apiGet<MasterySummary>(`/mastery/${learnerId}/summary`);
}

export async function fetchWrongAnswers(
  learnerId: string,
  kpId?: string,
  limit = 10,
): Promise<WrongAnswer[]> {
  const params = new URLSearchParams();
  if (kpId) params.set("kp_id", kpId);
  params.set("limit", String(limit));
  return apiGet<WrongAnswer[]>(
    `/mastery/${learnerId}/wrong?${params.toString()}`,
  );
}

export async function fetchWeakPoints(
  learnerId: string,
): Promise<WeakPoint[]> {
  const data = await apiGet<{ weak_points: WeakPoint[] }>(
    `/mastery/${learnerId}/weak`,
  );
  return data.weak_points;
}

function toPerDay(daily: Record<string, { total?: number }>): { date: string; total: number }[] {
  return Object.entries(daily || {}).map(([date, ds]) => ({
    date,
    total: ds.total || 0,
  }));
}

export async function fetchWeeklyStats(
  learnerId: string,
): Promise<PeriodStats> {
  const raw = await apiGet<any>(`/mastery/${learnerId}/stats/weekly`);
  return { total: raw.total, accuracy: raw.accuracy, per_day: toPerDay(raw.daily) };
}

export async function fetchMonthlyStats(
  learnerId: string,
): Promise<PeriodStats> {
  const raw = await apiGet<any>(`/mastery/${learnerId}/stats/monthly`);
  return { total: raw.total, accuracy: raw.accuracy, per_day: toPerDay(raw.daily) };
}


export interface MotivationInfo {
  streak_current: number;
  streak_longest: number;
  points: number;
  level: number;
  xp_to_next: number;
  achievement_count: number;
  weekly_accuracy: number;
  last_week_accuracy: number;
}

export async function fetchMotivation(learnerId: string): Promise<MotivationInfo> {
  const raw = await apiGet<any>(`/mastery/${learnerId}/motivation`);
  return {
    streak_current: raw.streak_current ?? 0,
    streak_longest: raw.streak_longest ?? 0,
    points: raw.points ?? 0,
    level: raw.level ?? 1,
    xp_to_next: raw.xp_to_next ?? 100,
    achievement_count: raw.achievement_count ?? 0,
    weekly_accuracy: raw.weekly_accuracy ?? 0,
    last_week_accuracy: raw.last_week_accuracy ?? 0,
  };
}


// ── Due Reviews (Ebbinghaus) ────────────────────────────────

export interface DueReview {
  kp_id: string;
  name?: string;
  level: number;
  due_date: string;
  chapter_title?: string;
  grade_name?: string;
}

export async function fetchDueReviews(
  learnerId: string,
): Promise<{ ok: boolean; reviews: DueReview[]; total: number }> {
  return apiGet(`/mastery/${learnerId}/reviews`);
}

// ── Knowledge Graph ─────────────────────────────────────────

export interface GraphNode {
  id: string;
  name: string;
  chapter: string;
  chapter_id: string;
  grade_name: string;
  importance: string;
  level: number;
  total: number;
  correct: number;
}

export interface GraphEdge {
  source: string;
  target: string;
}

export async function fetchKnowledgeGraph(
  subject = "math",
  learnerId = "default",
): Promise<{
  ok: boolean;
  nodes: GraphNode[];
  edges: GraphEdge[];
  total_nodes: number;
  total_edges: number;
}> {
  return apiGet(`/knowledge/graph?subject=${subject}&learner_id=${learnerId}`);
}

export interface PastQuestionEntry {
  question: TeachQuestion;
  evaluation: TeachEvaluation;
  user_answer: string;
}

export interface TeachStartResponse {
  ok: boolean;
  teach_session_id?: string;
  dt_session_id?: string;
  /** v2: structured TeachQuestion object; v1: string (legacy fallback) */
  first_question?: TeachQuestion | string;
  total_questions?: number;
  source?: string;
  current?: number;
  title?: string;
  task_type?: string;
  error?: string;
  /** Resume: past Q&A entries */
  past_questions?: PastQuestionEntry[];
  /** Resume: current question to display */
  current_question?: TeachQuestion;
  /** Resume: flag */
  resumed?: boolean;
  correct_count?: number;
  wrong_count?: number;
}

export interface TeachContinueResponse {
  ok: boolean;
  /** v1: legacy text reply (always present for backward compat) */
  reply?: string;
  /** v2: structured evaluation result */
  evaluation?: TeachEvaluation;
  /** v2: next question object (null = all done) */
  next_question?: TeachQuestion | null;
  current?: number;
  total_questions?: number;
  correct_count?: number;
  wrong_count?: number;
  done?: boolean;
  /** v2: knowledge-point summary (only when done=true) */
  summary?: KnowledgePointSummary;
  error?: string;
}

export async function startTeach(params: {
  file_base64?: string;
  filename?: string;
  ocr_text?: string;
  learner_id?: string;
  source_file?: string;
  mode?: string;
  title?: string;
  task_type?: string;
  consume_session_id?: string;
}): Promise<TeachStartResponse> {
  return apiPost("/teach/start", params);
}

export async function continueTeach(params: {
  teach_session_id: string;
  message: string;
  learner_id?: string;
}): Promise<TeachContinueResponse> {
  return apiPost("/teach/continue", params);
}

// ── Unified Tasks (v7.0) ─────────────────────────────────────

export interface PendingTask {
  teach_session_id: string;
  dt_session_id: string;
  title: string;
  task_type: string;           // "exam_paper" | "practice" | "auto_reinforce"
  task_source: string;         // "wechat" | "web_upload" | "auto_generated"
  total_questions: number;
  current_question: number;
  correct_count: number;
  wrong_count: number;
  status: string;
  knowledge_points: string;
  subject: string;
  created_at: number;
  expires_at: number;
}

export interface TaskCreateResponse {
  ok: boolean;
  teach_session_id?: string;
  title?: string;
  task_type?: string;
  task_source?: string;
  total_questions?: number;
  current_question?: number;
  status?: string;
  error?: string;
}

export async function fetchPendingTasks(
  learnerId = "",
): Promise<{ tasks: PendingTask[]; total_pending: number }> {
  const params = learnerId
    ? `?learner_id=${encodeURIComponent(learnerId)}`
    : "";
  return apiGet(`/tasks/pending${params}`);
}

export async function fetchTasksForSessions(
  sessionIds: string[],
): Promise<Record<string, PendingTask>> {
  const ids = sessionIds.filter(Boolean).join(",");
  if (!ids) return {};
  const data = await apiGet<{ tasks: Record<string, PendingTask> }>(
    `/tasks/for-sessions?session_ids=${encodeURIComponent(ids)}`,
  );
  return data.tasks || {};
}

export async function createTask(params: {
  learner_id: string;
  source: string;
  title?: string;
  task_type?: string;
  file_base64?: string;
  filename?: string;
  ocr_text?: string;
  total_questions?: number;
  knowledge_points?: string;
  subject?: string;
}): Promise<TaskCreateResponse> {
  return apiPost("/tasks/create", params);
}

export async function updateTaskProgress(
  teachSessionId: string,
  params: {
    current_question?: number;
    correct_count?: number;
    wrong_count?: number;
    done?: boolean;
  },
): Promise<{
  ok: boolean;
  current: number;
  total: number;
  correct: number;
  wrong: number;
  done: boolean;
}> {
  return apiPost(`/tasks/${encodeURIComponent(teachSessionId)}/progress`, params);
}

// ── Practice / Exam / Report ────────────────────────────────

export async function generatePractice(
  learnerId: string,
  kpId: string,
  count = 3,
  timeLimit = 0,
): Promise<{ questions: PracticeQuestion[]; time_limit: number }> {
  return apiPost("/practice/generate", {
    learner_id: learnerId,
    kp_id: kpId,
    count,
    time_limit: timeLimit,
  });
}

export interface ExamQuestion {
  num: number;
  section_type: string;
  question: string;
  options?: Record<string, string>;
  kpi: string;
  difficulty: string;
  correct_answer: string;
  explanation: string;
}

export async function generateExam(
  learnerId: string,
  timeLimit = 0,
): Promise<{
  ok: boolean;
  exam_text: string;
  title: string;
  kp_covered: string[];
  total: number;
  questions: ExamQuestion[];
  time_limit: number;
}> {
  return apiPost("/practice/exam", {
    learner_id: learnerId,
    time_limit: timeLimit,
  });
}

export async function generateReport(
  learnerId: string,
  type: "daily" | "weekly" | "monthly",
): Promise<string> {
  return apiPostText("/report/generate", {
    learner_id: learnerId,
    type,
  });
}

// ── Exam Topics (中考专题) ──────────────────────────────────

export interface ExamTopic {
  id: string;
  title: string;
  description: string;
  kp_list: string[];
}

export async function fetchExamTopics(
  subject = "math",
): Promise<{ ok: boolean; topics: ExamTopic[]; subject: string }> {
  return apiGet(`/practice/exam-topics?subject=${subject}`);
}

export async function generateExamTopic(
  learnerId: string,
  examTopicId: string,
  subject = "math",
  count = 8,
): Promise<{
  ok: boolean;
  questions: PracticeQuestion[];
  title: string;
  total: number;
}> {
  return apiPost("/practice/exam-topic", {
    learner_id: learnerId,
    exam_topic_id: examTopicId,
    subject,
    count,
  });
}

// ── Quiz Sync ───────────────────────────────────────────────

export async function syncQuizResults(
  learnerId: string,
  answers: Array<{
    kp_id: string;
    is_correct: boolean;
    question: string;
    user_answer: string;
    correct_answer?: string;
  }>,
): Promise<{ ok: boolean; synced: number; errors: number }> {
  return apiPost("/quiz/sync", {
    learner_id: learnerId,
    answers,
  });
}

// ── Practice Review & Summary ──────────────────────────────

export interface PracticeAnswer {
  question: string;
  student_answer: string;
  correct_answer: string;
  is_correct: boolean;
  kp_id: string;
}

// ── Practice Teach (DT native teaching via TeachSession) ──

export async function fetchPracticeTeach(
  learnerId: string,
  contextText: string,
  topicName: string,
): Promise<{
  ok: boolean;
  teach_session_id?: string;
  first_question?: string;
  total_questions?: number;
  error?: string;
}> {
  return apiPost("/practice/teach", {
    learner_id: learnerId,
    context_text: contextText,
    topic_name: topicName,
  });
}

// ── Practice Review & Summary (batch: used on exercise completion) ──

export async function fetchPracticeReview(
  learnerId: string,
  wrongAnswers: Array<{
    question: string;
    options?: Record<string, string>;
    student_answer: string;
    correct_answer: string;
    kp_id: string;
  }>,
): Promise<{ ok: boolean; review_text: string }> {
  return apiPost("/practice/review", {
    learner_id: learnerId,
    wrong_answers: wrongAnswers,
  });
}

export interface PracticeSummary {
  ok: boolean;
  total: number;
  correct: number;
  score_pct: number;
  weak_kps: Array<{ kp_id: string; name: string; accuracy: number }>;
  assessment: string;
  mastery_updated: number;
}

export async function fetchPracticeSummary(
  learnerId: string,
  answers: PracticeAnswer[],
): Promise<PracticeSummary> {
  return apiPost("/practice/summary", {
    learner_id: learnerId,
    answers,
  });
}

// ── Record answer to mastery ───────────────────────────────
export async function recordQuizAnswer(
  learnerId: string,
  kpId: string,
  correct: boolean,
  question: string,
  userAnswer: string,
  correctAnswer: string,
): Promise<void> {
  await apiPost(`/mastery/${learnerId}`, {
    kp_id: kpId,
    correct,
    question,
    user_answer: userAnswer,
    correct_answer: correctAnswer,
  });
}
