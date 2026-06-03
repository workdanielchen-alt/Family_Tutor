// ── Types ────────────────────────────────────────────────────

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

// ── Quiz Session ────────────────────────────────────────────

export interface QuizSessionQuestion {
  question_id: string;
  question: string;
  question_type: string;
  options?: Record<string, string>;
  difficulty?: string;
  knowledge_context?: string;
}

export interface QuizSessionData {
  session_id: string;
  learner_id?: string;
  status: string;
  title: string;
  total_questions: number;
  completed: number;
  questions: QuizSessionQuestion[];
  kp_covered: string[];
  created_at: number;
  expires_at: number;
  completed_at?: number | null;
}

export interface QuizAnswerResult {
  ok: boolean;
  is_correct: boolean;
  correct_answer: string;
  explanation: string;
  completed: number;
  total: number;
  session_completed: boolean;
}

export interface PendingQuizSession {
  session_id: string;
  title: string;
  total_questions: number;
  completed: number;
  created_at: number;
  expires_at: number;
  source_file: string;
}

export async function fetchQuizSession(
  sessionId: string,
): Promise<QuizSessionData> {
  return apiGet(`/quiz/session/${sessionId}`);
}

export async function submitQuizAnswer(
  sessionId: string,
  questionId: string,
  learnerId: string,
  answer: string,
): Promise<QuizAnswerResult> {
  return apiPost("/quiz/answer", {
    session_id: sessionId,
    question_id: questionId,
    learner_id: learnerId,
    answer,
  });
}

export async function completeQuizSession(
  sessionId: string,
  learnerId: string,
): Promise<{ ok: boolean; total: number; completed: number; accuracy: number; weak_kps: string[] }> {
  return apiPost("/quiz/complete", {
    session_id: sessionId,
    learner_id: learnerId,
  });
}

export async function fetchPendingQuizSessions(
  learnerId: string,
): Promise<{ sessions: PendingQuizSession[]; total_pending: number }> {
  return apiGet(`/quiz/pending/${learnerId}`);
}

export async function fetchAllPendingQuizSessions(): Promise<{
  sessions: PendingQuizSession[];
  total_pending: number;
}> {
  return apiGet("/quiz/pending");
}

// ── Teach Session ─────────────────────────────────────────────

export interface TeachStartResponse {
  ok: boolean;
  teach_session_id?: string;
  first_question?: string;
  total_questions?: number;
  source?: string;
  current?: number;
  error?: string;
}

export interface TeachContinueResponse {
  ok: boolean;
  reply?: string;
  current?: number;
  total_questions?: number;
  done?: boolean;
  error?: string;
}

export async function startTeach(params: {
  file_base64?: string;
  filename?: string;
  ocr_text?: string;
  learner_id?: string;
  source_file?: string;
  mode?: string;
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
