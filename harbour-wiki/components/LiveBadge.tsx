// Honest LIVE indicator: green only while events are actually arriving.
// A lecture marked live whose recorder went silent shows an amber warning —
// the "recorder died, nobody noticed" failure mode made visible.

interface LiveBadgeProps {
  live: boolean;
  receiving: boolean;
  silentFor: number | null;
}

export function LiveBadge({ live, receiving, silentFor }: LiveBadgeProps) {
  if (!live) return null;
  if (receiving) return <span className="live-badge">LIVE</span>;
  const label =
    silentFor === null
      ? "LIVE · no audio"
      : silentFor < 120
        ? `LIVE · no audio ${silentFor}s`
        : `LIVE · no audio ${Math.floor(silentFor / 60)}m`;
  return (
    <span className="live-badge stale" title="Recording is marked live but no events are arriving — check the recorder">
      ⚠ {label}
    </span>
  );
}
