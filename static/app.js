let currentNote = null; // { id, title }
let currentMode = "light";

const el = (id) => document.getElementById(id);

async function loadTree() {
  const res = await fetch("/api/tree");
  const tree = await res.json();
  el("tree").innerHTML = "";
  el("tree").appendChild(renderFolder(tree, true));
}

function renderFolder(folder, isRoot) {
  const wrap = document.createElement("div");
  if (!isRoot) {
    const header = document.createElement("div");
    header.className = "folder-name";
    header.textContent = `\u{1F4C1} ${folder.name}`;
    const children = document.createElement("div");
    children.className = "folder-children";
    header.onclick = () => children.classList.toggle("hidden");
    wrap.appendChild(header);
    wrap.appendChild(children);
    fillChildren(children, folder);
  } else {
    fillChildren(wrap, folder);
  }
  return wrap;
}

function fillChildren(container, folder) {
  for (const sub of folder.folders) container.appendChild(renderFolder(sub, false));
  for (const note of folder.notes) container.appendChild(renderNoteRow(note));
}

function renderNoteRow(note) {
  const row = document.createElement("div");
  row.className = "note-row";
  row.dataset.id = note.id;
  row.dataset.title = note.title.toLowerCase();
  let badges = "";
  if (note.locked) badges += `<span class="badge">locked</span>`;
  if (note.hasMergedDark) badges += `<span class="badge dark">dark saved</span>`;
  row.innerHTML = `<span>${escapeHtml(note.title)}</span>${badges}`;
  row.onclick = () => selectNote(note);
  return row;
}

function escapeHtml(s) {
  return s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

async function selectNote(note) {
  currentNote = note;
  document.querySelectorAll(".note-row").forEach((r) => r.classList.toggle("active", r.dataset.id === note.id));
  el("note-title").textContent = note.title;
  el("mode-toggle").classList.remove("hidden");
  el("export-actions").classList.remove("hidden");
  el("placeholder").classList.add("hidden");

  setStatus("Checking suggested color mode...");
  const suggestRes = await fetch(`/api/note/${encodeURIComponent(note.id)}/suggest`);
  const { suggested } = await suggestRes.json();
  el("suggested-hint").textContent = `(suggested: ${suggested})`;
  await showPreview(suggested);
}

async function showPreview(mode) {
  currentMode = mode;
  el("mode-light").classList.toggle("active", mode === "light");
  el("mode-dark").classList.toggle("active", mode === "dark");
  setStatus("Rendering preview...");
  const viewer = el("viewer");
  viewer.classList.remove("hidden");
  viewer.src = `/api/note/${encodeURIComponent(currentNote.id)}/preview?mode=${mode}&t=${Date.now()}`;
  viewer.onload = () => setStatus("");
}

function setStatus(msg) {
  el("status").textContent = msg;
}

el("mode-light").onclick = () => showPreview("light");
el("mode-dark").onclick = () => showPreview("dark");

el("export-current").onclick = async () => {
  if (!currentNote) return;
  setStatus(`Exporting ${currentMode} copy...`);
  const res = await fetch(`/api/note/${encodeURIComponent(currentNote.id)}/export?mode=${currentMode}`, { method: "POST" });
  const data = await res.json();
  setStatus(res.ok ? `Saved: ${data.written.map((w) => w.path).join(", ")}` : `Export failed: ${data.error}`);
};

el("export-both").onclick = async () => {
  if (!currentNote) return;
  setStatus("Exporting both light and dark copies...");
  const res = await fetch(`/api/note/${encodeURIComponent(currentNote.id)}/export?mode=both`, { method: "POST" });
  const data = await res.json();
  setStatus(res.ok ? `Saved: ${data.written.map((w) => w.path).join(", ")}` : `Export failed: ${data.error}`);
};

el("search").addEventListener("input", (e) => {
  const q = e.target.value.toLowerCase();
  document.querySelectorAll(".note-row").forEach((row) => {
    row.style.display = row.dataset.title.includes(q) ? "" : "none";
  });
});

loadTree();
