import type { Profile, ProfileAnswer } from "../core/types";

export async function fetchProfile(): Promise<Profile | null> {
  const res = await fetch("/profile");
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`fetchProfile failed: ${res.status}`);
  return res.json();
}

export async function createProfile(
  name: string,
  answers: ProfileAnswer[],
): Promise<Profile> {
  const res = await fetch("/profile", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, answers }),
  });
  if (!res.ok) throw new Error(`createProfile failed: ${res.status}`);
  return res.json();
}
