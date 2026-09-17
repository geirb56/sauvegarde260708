import { cn } from "@/lib/utils";

function getUserEmail(user) {
  return typeof user?.email === "string" ? user.email.trim() : "";
}

export function getUserIdentityInitial(user) {
  const email = getUserEmail(user);
  const localPart = email.split("@")[0] || "";
  const firstVisibleCharacter = Array.from(localPart).find((char) => /[\p{L}\p{N}]/u.test(char));

  return firstVisibleCharacter ? firstVisibleCharacter.toUpperCase() : "?";
}

export default function UserIdentityAvatar({ user, className, testId }) {
  return (
    <div
      className={cn(
        "flex h-8 w-8 items-center justify-center rounded-full bg-[var(--accent-green-dark)] text-xs font-semibold text-[#0a0e1a]",
        className,
      )}
      data-testid={testId}
      aria-hidden="true"
    >
      {getUserIdentityInitial(user)}
    </div>
  );
}
