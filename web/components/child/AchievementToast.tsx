"use client";

import { useEffect, useState, useRef } from "react";
import { Trophy, X } from "lucide-react";
import { fetchMotivation, type MotivationInfo } from "@/lib/platform-api";

const LEARNER_ID = "default";
const POLL_INTERVAL = 30000; // Check every 30s

export default function AchievementToast() {
  const [motiv, setMotiv] = useState<MotivationInfo | null>(null);
  const [show, setShow] = useState(false);
  const [message, setMessage] = useState("");
  const prevCountRef = useRef<number | null>(null);
  const prevPointsRef = useRef<number | null>(null);
  const prevLevelRef = useRef<number | null>(null);

  useEffect(() => {
    let cancelled = false;

    const check = async () => {
      try {
        const m = await fetchMotivation(LEARNER_ID);
        if (cancelled) return;

        const prevCount = prevCountRef.current;
        const prevPoints = prevPointsRef.current;
        const prevLevel = prevLevelRef.current;

        // First load
        if (prevCount === null) {
          prevCountRef.current = m.achievement_count;
          prevPointsRef.current = m.points;
          prevLevelRef.current = m.level;
          setMotiv(m);
          return;
        }

        // New achievement unlocked
        if (m.achievement_count > prevCount) {
          setMessage(`🏆 新成就解锁！已获得 ${m.achievement_count} 个成就`);
          setShow(true);
        }
        // Level up
        else if (prevLevel !== null && m.level > prevLevel) {
          setMessage(`🎉 升级了！达到 Lv.${m.level}`);
          setShow(true);
        }
        // Significant points gain (50+)
        else if (prevPoints !== null && m.points - prevPoints >= 50) {
          setMessage(`⭐ +${m.points - prevPoints} XP！继续加油`);
          setShow(true);
        }

        prevCountRef.current = m.achievement_count;
        prevPointsRef.current = m.points;
        prevLevelRef.current = m.level;
        setMotiv(m);
      } catch { /* ignore */ }
    };

    check(); // Immediate first check
    const interval = setInterval(check, POLL_INTERVAL);
    return () => { cancelled = true; clearInterval(interval); };
  }, []);

  // Auto-dismiss
  useEffect(() => {
    if (!show) return;
    const timer = setTimeout(() => setShow(false), 5000);
    return () => clearTimeout(timer);
  }, [show]);

  if (!show) return null;

  return (
    <div className="fixed top-4 left-1/2 -translate-x-1/2 z-50 animate-in fade-in slide-in-from-top-4">
      <div className="flex items-center gap-3 rounded-2xl bg-gradient-to-r from-yellow-500 to-orange-500
        px-5 py-3 text-white shadow-xl">
        <Trophy className="h-5 w-5" />
        <span className="text-sm font-semibold">{message}</span>
        <button
          onClick={() => setShow(false)}
          className="ml-2 rounded-full p-0.5 hover:bg-white/20"
        >
          <X className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
}
