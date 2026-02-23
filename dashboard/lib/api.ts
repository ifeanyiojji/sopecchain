const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "";

export async function calculateScope3(formData: FormData) {
  const res = await fetch(`${API_BASE}/api/calculate`, {
    method: "POST",
    body: formData,
  });

  if (!res.ok) {
    const errorText = await res.text();
    throw new Error(errorText || `Server error: ${res.status}`);
  }

  return res.json();
}
