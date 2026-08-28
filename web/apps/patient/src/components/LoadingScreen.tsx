export function LoadingScreen({ message = "Loading…" }: { message?: string }) {
  return (
    <main style={{ fontFamily: "system-ui", padding: "2rem" }}>
      <p role="status">{message}</p>
    </main>
  );
}
