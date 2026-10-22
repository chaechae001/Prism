/** Three overlapping planes: different sources, a shared context. */
export function PrismMark({ className = "" }: { className?: string }) {
  return (
    <svg
      className={`prism-mark ${className}`}
      viewBox="0 0 40 40"
      fill="none"
      aria-hidden="true"
    >
      <path d="M6 11 20 4v24L6 35V11Z" fill="currentColor" opacity=".35" />
      <path d="m13 11 14-7v24l-14 7V11Z" fill="currentColor" opacity=".65" />
      <path d="m20 11 14-7v24l-14 7V11Z" fill="currentColor" />
    </svg>
  );
}
