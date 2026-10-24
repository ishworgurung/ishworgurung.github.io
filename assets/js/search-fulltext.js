// Full-text search for the ninja-keys search box.
// The built-in search only matches titles. This adds a "Found in posts"
// section listing posts whose body contains every word typed, with a snippet.
//
// The index (search-index.json, built by _plugins/search_index_generator.rb)
// is one entry per heading-delimited section of a post, carrying that
// section's real heading id. A result therefore links to post.url#heading-id,
// landing at the right section instead of the top of the post, and a
// Scroll To Text Fragment (`:~:text=`) directive is appended on top so that
// browsers which support it (Chrome, Edge) scroll to and highlight the exact
// matched sentence. Browsers without support just use the heading anchor.
(() => {
  const ninja = document.querySelector("ninja-keys");
  if (!ninja) return;

  const INDEX_URL = document.documentElement.dataset.searchIndex || "/assets/search-index.json";
  const MIN_QUERY = 3;
  const MAX_RESULTS = 8;
  // Result rows are a single line, so the snippet is sized to fit beside the
  // title and starts just before the match.
  const LINE_CHARS = 78;
  const LEAD_CHARS = 20;
  const PREFIX = "fulltext-";

  let index = null;
  let loading = null;
  let base = null;
  let lastQuery = "";

  const load = () =>
    (loading ||= fetch(INDEX_URL)
      .then((r) => (r.ok ? r.json() : []))
      .then((sections) => {
        index = sections.map((s) => ({ ...s, lower: s.body.toLowerCase() }));
      })
      .catch(() => {
        index = [];
      }));

  // Titles are rendered as HTML by ninja-keys and highlighted by character
  // position, so keep them plain text with no markup characters.
  const plain = (s) => s.replace(/</g, "‹").replace(/>/g, "›").replace(/&/g, "＆");

  // Word-boundary-trimmed text around a match, with no ellipses: used both
  // for the visible snippet (room-limited) and, shorter, as the exact phrase
  // handed to the browser's text fragment matcher.
  function textAround(body, lower, term, room) {
    const at = lower.indexOf(term);
    let start = Math.max(0, at - LEAD_CHARS);
    let end = Math.min(body.length, start + Math.max(room, term.length + LEAD_CHARS));
    if (start > 0) {
      const sp = body.indexOf(" ", start);
      if (sp !== -1 && sp < at) start = sp + 1;
    }
    if (end < body.length) {
      const sp = body.lastIndexOf(" ", end);
      if (sp > at + term.length) end = sp;
    }
    return { start, end, text: body.slice(start, end).trim() };
  }

  function snippet(body, lower, term, room) {
    const { start, end, text } = textAround(body, lower, term, room);
    return (start > 0 ? "…" : "") + text + (end < body.length ? "…" : "");
  }

  // A short, exact phrase around the match, safe to pass to a text fragment
  // (https://wicg.github.io/scroll-to-text-fragment/): a few words, no
  // ellipsis markers, since the browser matches it literally against the
  // page text.
  function exactPhrase(body, lower, term) {
    if (lower.indexOf(term) === -1) return null;
    return textAround(body, lower, term, 48).text;
  }

  function withTextFragment(url, phrase) {
    if (!phrase) return url;
    const encoded = encodeURIComponent(phrase).replace(/-/g, "%2D");
    return url.includes("#") ? `${url}:~:text=${encoded}` : `${url}#:~:text=${encoded}`;
  }

  function search(query) {
    const q = query.toLowerCase();
    const terms = q.split(/\s+/).filter((t) => t.length >= 2);
    if (!terms.length) return [];

    // One result per post: keep whichever of its sections matches best.
    const bestByTitle = new Map();
    for (const s of index) {
      if (!terms.every((t) => s.lower.includes(t))) continue;
      // The built-in search already lists posts whose title matches.
      if (s.title.toLowerCase().includes(q)) continue;
      let count = 0;
      for (const t of terms) count += s.lower.split(t).length - 1;
      const prev = bestByTitle.get(s.title);
      if (!prev || count > prev.count) bestByTitle.set(s.title, { s, count });
    }

    const hits = [...bestByTitle.values()].sort((a, b) => b.count - a.count).slice(0, MAX_RESULTS);

    return hits.map(({ s }, i) => {
      const anchor = s.lower.includes(q) ? q : terms[0];
      const room = Math.max(32, LINE_CHARS - s.title.length);
      const text = snippet(s.body, s.lower, anchor, room);
      const url = withTextFragment(s.url, exactPhrase(s.body, s.lower, anchor));
      return {
        id: PREFIX + i,
        title: plain(`${s.title} — ${text}`),
        // ninja-keys scores "title + description" against the query; the query
        // itself guarantees a body match is never filtered out.
        description: query,
        section: "Found in posts",
        handler: () => {
          window.location.href = url;
        },
      };
    });
  }

  async function update(query) {
    lastQuery = query;
    base ||= ninja.data.filter((a) => !String(a.id).startsWith(PREFIX));
    if (query.length < MIN_QUERY) {
      if (ninja.data.length !== base.length) ninja.data = base;
      return;
    }
    if (!index) await load();
    if (query !== lastQuery) return; // a newer keystroke has taken over
    ninja.data = base.concat(search(query));
  }

  ninja.addEventListener("change", (e) => update((e.detail.search || "").trim()));
})();
