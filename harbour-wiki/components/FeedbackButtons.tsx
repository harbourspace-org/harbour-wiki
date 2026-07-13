"use client";

import { useState } from "react";

// One-tap feedback — the signal the whole student test is run for.

interface FeedbackButtonsProps {
  courseId: string;
}

export function FeedbackButtons({ courseId }: FeedbackButtonsProps) {
  const [sent, setSent] = useState(false);
  const [comment, setComment] = useState("");
  const [voted, setVoted] = useState<"up" | "down" | null>(null);

  async function send(vote: "up" | "down", withComment?: string) {
    setVoted(vote);
    try {
      await fetch("/api/feedback", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ course: courseId, vote, comment: withComment || undefined }),
      });
    } finally {
      if (withComment !== undefined || vote === "up") setSent(true);
    }
  }

  if (sent) return <div className="feedback-row">Thanks — feedback recorded 🙌</div>;

  if (voted === "down") {
    return (
      <div className="feedback-row">
        <input
          className="field"
          style={{ flex: "1 1 12rem" }}
          value={comment}
          onChange={(e) => setComment(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && send("down", comment)}
          placeholder="What was wrong or missing? (optional)"
          aria-label="Feedback comment"
        />
        <button className="btn" onClick={() => send("down", comment)}>
          Send
        </button>
      </div>
    );
  }

  return (
    <div className="feedback-row">
      <span>Were these notes useful?</span>
      <button className="btn" onClick={() => send("up")} aria-label="Useful">
        👍
      </button>
      <button className="btn" onClick={() => setVoted("down")} aria-label="Not useful">
        👎
      </button>
    </div>
  );
}
