export default function AuthBrand({ className = "", testId = "auth-brand-logo" }) {
  return (
    <img
      src="/runindex-logo.png"
      alt="RunIndex"
      className={`mx-auto h-12 w-auto max-w-[220px] ${className}`.trim()}
      data-testid={testId}
    />
  );
}
