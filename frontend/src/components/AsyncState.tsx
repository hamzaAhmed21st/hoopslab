type AsyncStateProps = {
  title: string;
  message?: string;
  onRetry?: () => void;
  role?: "status" | "alert";
};

export function AsyncState({
  title,
  message,
  onRetry,
  role = "status",
}: AsyncStateProps) {
  return (
    <div className={`async-state ${role === "alert" ? "async-error" : ""}`} role={role}>
      <strong>{title}</strong>
      {message ? <p>{message}</p> : null}
      {onRetry ? (
        <button type="button" onClick={onRetry}>
          Retry
        </button>
      ) : null}
    </div>
  );
}
