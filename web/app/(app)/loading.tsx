/**
 * Loading skeleton shown during route transitions within (app).
 * Prevents any page from flashing into view during rapid sidebar tab switching.
 */
export default function AppLoading() {
  return (
    <div className="flex h-full items-center justify-center bg-[var(--background)]">
      <div className="flex flex-col items-center gap-2">
        <div className="h-4 w-4 animate-spin rounded-full border-2 border-[var(--muted-foreground)]/30 border-t-[var(--muted-foreground)]" />
        <span className="text-xs text-[var(--muted-foreground)]/60">
          Loading…
        </span>
      </div>
    </div>
  );
}
