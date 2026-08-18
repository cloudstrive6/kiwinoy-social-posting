// Newsletter signup handler. The on-site form POSTs {name, email} here and we add the
// subscriber to MailerLite via its API. Keeps the site's own styled form (no third-party embed).
//
// Runtime env vars (set in the Netlify site's Environment variables, NOT GitHub):
//   MAILERLITE_API_KEY   (required)  — MailerLite → Integrations → API → generate token
//   MAILERLITE_GROUP_ID  (optional)  — add subscribers to a specific group/list
//
// Endpoint: /.netlify/functions/subscribe

const json = (obj, status = 200) =>
  new Response(JSON.stringify(obj), {
    status,
    headers: { "Content-Type": "application/json" },
  });

export default async (req) => {
  if (req.method !== "POST") return json({ error: "method not allowed" }, 405);

  let body;
  try {
    body = await req.json();
  } catch {
    return json({ error: "invalid body" }, 400);
  }

  const email = String(body.email || "").trim().toLowerCase();
  const name = String(body.name || "").trim();
  if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) {
    return json({ error: "invalid email" }, 400);
  }

  const key = process.env.MAILERLITE_API_KEY;
  if (!key) return json({ error: "mailing list not configured yet" }, 503);

  const payload = { email, status: "active" };
  if (name) payload.fields = { name };
  if (process.env.MAILERLITE_GROUP_ID) payload.groups = [process.env.MAILERLITE_GROUP_ID];

  try {
    const r = await fetch("https://connect.mailerlite.com/api/subscribers", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
        Authorization: `Bearer ${key}`,
      },
      body: JSON.stringify(payload),
    });
    // 200 = existing subscriber updated, 201 = newly created — both are success.
    if (r.status === 200 || r.status === 201) return json({ ok: true });
    const detail = (await r.text()).slice(0, 300);
    return json({ error: "subscribe failed", status: r.status, detail }, 502);
  } catch (e) {
    return json({ error: "upstream error", detail: String(e).slice(0, 200) }, 502);
  }
};
