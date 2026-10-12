const projectList = document.querySelector("#projectList");
const projectDetail = document.querySelector("#projectDetail");
const refreshButton = document.querySelector("#refreshButton");

let projects = [];
let selectedSlug = null;
let detailRequest = 0;

const stateNames = {
  complete: "FINAL พร้อม",
  review: "ควรตรวจเพิ่ม",
  production: "กำลังผลิต",
  planning: "เริ่มต้นเรื่อง",
  error: "อ่านข้อมูลไม่ได้",
};

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, character => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[character]);
}

function mediaUrl(slug, kind, sceneId) {
  return `/media/${encodeURIComponent(slug)}/${kind}${sceneId == null ? "" : `/${encodeURIComponent(sceneId)}`}`;
}

function timecode(seconds) {
  const total = Math.max(0, Math.floor(Number(seconds) || 0));
  return `${String(Math.floor(total / 60)).padStart(2, "0")}:${String(total % 60).padStart(2, "0")}`;
}

function requestedSlug() {
  try {
    return decodeURIComponent(location.hash.slice(1));
  } catch {
    return "";
  }
}

function stateChip(state) {
  return `<span class="state-chip ${escapeHtml(state)}">${escapeHtml(stateNames[state] || state)}</span>`;
}

async function getJson(path) {
  const response = await fetch(path, { cache: "no-store" });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
  return data;
}

function renderMetrics() {
  document.querySelector("#projectCount").textContent = projects.length;
  document.querySelector("#sceneCount").textContent = projects.reduce((sum, project) => sum + project.scene_count, 0);
  document.querySelector("#clipCount").textContent = projects.reduce((sum, project) => sum + project.clip_count, 0);
  document.querySelector("#finalCount").textContent = projects.filter(project => project.final).length;
  document.querySelector("#railCount").textContent = String(projects.length).padStart(2, "0");
}

function renderProjects() {
  if (!projects.length) {
    projectList.innerHTML = `<div class="loading-copy">ยังไม่มีโปรเจกต์<br>เริ่มด้วย <code>python tools/ani.py new my-film</code></div>`;
    return;
  }
  projectList.innerHTML = projects.map(project => `
    <button class="project-card" type="button" data-slug="${escapeHtml(project.slug)}" aria-current="${project.slug === selectedSlug}">
      ${project.cover
        ? `<img class="project-thumb" src="${mediaUrl(project.slug, "cover")}" alt="ภาพประกอบ ${escapeHtml(project.title)}" loading="lazy">`
        : `<span class="project-thumb thumb-placeholder" aria-hidden="true">✳</span>`}
      <span class="project-card-copy">
        <small>${escapeHtml(project.slug)}</small>
        <strong>${escapeHtml(project.title)}</strong>
        <span>${project.clip_count}/${project.scene_count} คลิป · ${escapeHtml(stateNames[project.state] || project.state)}</span>
      </span>
    </button>`).join("");
}

function assetBadge(label, exists, qc) {
  const state = qc === "redo" ? "redo" : exists ? "ready" : "";
  const detail = qc === "redo" ? "ทำใหม่" : exists ? qc === "pass" ? "ผ่าน QC" : "มีไฟล์" : "ยังไม่มี";
  return `<span class="asset-badge ${state}">${label}: ${detail}</span>`;
}

function fileCheck(label, ready, detail = "") {
  return `<div class="file-check"><span>${escapeHtml(label)}</span><strong class="${ready ? "ready" : "missing"}">${ready ? "● พร้อม" : "○ ยังไม่มี"}${detail ? ` · ${escapeHtml(detail)}` : ""}</strong></div>`;
}

function renderScene(scene, slug) {
  const image = scene.image
    ? `<img src="${mediaUrl(slug, "scene", scene.id)}" alt="ภาพฉาก ${escapeHtml(scene.id)}" loading="lazy">`
    : `<span class="no-image" aria-label="ยังไม่มีภาพ">${escapeHtml(scene.id)}</span>`;
  const voice = scene.vo.length
    ? scene.vo.map(line => `<p class="vo-line"><span class="speaker">${escapeHtml(line.speaker)} · +${escapeHtml(line.offset)}s</span><br>${escapeHtml(line.text)}</p>`).join("")
    : `<p class="scene-note">ฉากนี้ไม่มีบทพากย์</p>`;
  const clipLink = scene.clip
    ? `<a class="scene-link" href="${mediaUrl(slug, "clip", scene.id)}" target="_blank" rel="noopener">เปิดคลิปฉาก ${escapeHtml(scene.id)} ↗</a>`
    : "";
  return `<article class="scene-card">
    <div class="scene-visual">${image}<span class="frame-label">FRAME ${escapeHtml(scene.id)}</span></div>
    <div class="scene-body">
      <div class="scene-top"><span class="scene-index">SCENE ${escapeHtml(scene.id)} · ${escapeHtml(scene.mood || "—")}</span><span class="scene-time">${timecode(scene.start)} — ${timecode(scene.end)}</span></div>
      <h4>${escapeHtml(scene.title)}</h4>
      <div class="scene-badges">${assetBadge("ภาพ", scene.image, scene.qc.image)}${assetBadge("คลิป", scene.clip, scene.qc.clip)}</div>
      ${voice}
      ${scene.qc.note ? `<p class="scene-note">QC · ${escapeHtml(scene.qc.note)}</p>` : ""}
      ${clipLink}
      <details class="prompt-drawer"><summary>ดู image / motion prompt</summary>
        <h5>IMAGE PROMPT</h5><p>${escapeHtml(scene.image_prompt || "ยังไม่ได้เขียน")}</p>
        <h5>MOTION PROMPT</h5><p>${escapeHtml(scene.motion_prompt || "ยังไม่ได้เขียน")}</p>
      </details>
    </div>
  </article>`;
}

function renderDetail(project) {
  const video = project.final
    ? `<video controls preload="metadata" playsinline src="${mediaUrl(project.slug, "final")}">เบราว์เซอร์นี้เล่นวิดีโอไม่ได้</video>`
    : project.cover
      ? `<img src="${mediaUrl(project.slug, "cover")}" alt="ภาพรวมของ ${escapeHtml(project.title)}">`
      : `<div class="video-placeholder"><span>◧</span>ยังไม่มี final หรือภาพฉาก</div>`;
  const finalLinks = project.final
    ? `<a class="screening-link" href="${mediaUrl(project.slug, "final")}" target="_blank" rel="noopener">เปิด final ↗</a>${project.subs ? ` &nbsp;·&nbsp; <a class="screening-link" href="${mediaUrl(project.slug, "subs")}" target="_blank" rel="noopener">เปิด final พร้อมซับ ↗</a>` : ""}`
    : "";
  projectDetail.innerHTML = `
    <div class="detail-hero">
      <div class="detail-topline"><p class="eyebrow">PROJECT / ${escapeHtml(project.slug)}</p>${stateChip(project.state)}</div>
      <h2>${escapeHtml(project.title)}</h2>
      <div class="slug-line">${escapeHtml(project.slug)}</div>
      <div class="detail-facts">
        <span><strong>${project.scene_count}</strong> ฉาก</span><span class="divider">✳</span>
        <span><strong>${escapeHtml(project.duration)}</strong> วินาที</span><span class="divider">✳</span>
        <span><strong>${project.image_count}/${project.scene_count}</strong> ภาพ</span><span class="divider">✳</span>
        <span><strong>${project.clip_count}/${project.scene_count}</strong> คลิป</span>
      </div>
      <div class="next-step"><span>NEXT ACTION</span><strong>${escapeHtml(project.next_step)}</strong></div>
    </div>
    <div class="feature-grid">
      <section class="screening-room" aria-labelledby="screeningTitle">
        <div class="section-heading"><h3 id="screeningTitle">Screening room</h3><span class="section-kicker">01 / OUTPUT</span></div>
        <div class="video-frame">${video}</div>${finalLinks}
      </section>
      <section class="brief-panel" aria-labelledby="briefTitle">
        <div class="section-heading"><h3 id="briefTitle">Creative brief</h3><span class="section-kicker">02 / SOURCE</span></div>
        <div class="provider-strip">${["image", "video", "tts", "music"].map(kind => `<div class="provider-cell"><span>${kind.toUpperCase()} PROVIDER</span><strong>${escapeHtml(project.providers[kind])}</strong></div>`).join("")}</div>
        <div class="file-checks">
          ${fileCheck("Draft", project.draft)}
          ${fileCheck("เสียงพากย์", project.voice_count === project.voice_total, `${project.voice_count}/${project.voice_total} ไฟล์`)}
          ${fileCheck("เพลง", project.music)}
          ${fileCheck("ไฟล์ซับ", project.subtitle_file)}
          ${fileCheck("Final", project.final)}
        </div>
        <div class="brief-block"><h4>Visual style</h4><p>${escapeHtml(project.style || "ยังไม่ได้กำหนด")}</p></div>
        <div class="brief-block"><h4>Characters</h4><p>${escapeHtml(project.characters || "ยังไม่ได้กำหนด")}</p></div>
        <div class="brief-block"><h4>Output format</h4><p>${escapeHtml(project.video.width || "—")} × ${escapeHtml(project.video.height || "—")} · ${escapeHtml(project.video.fps || "—")} fps · ${escapeHtml(project.video.aspect || "—")}</p></div>
      </section>
    </div>
    <section class="scenes-section" aria-labelledby="sceneTitle">
      <div class="section-heading"><h3 id="sceneTitle">ลำดับฉาก</h3><span class="section-kicker">03 / STORYBOARD · ${project.scene_count} SCENES</span></div>
      <div class="scenes-list">${project.scenes.length ? project.scenes.map(scene => renderScene(scene, project.slug)).join("") : `<div class="detail-empty">ยังไม่มีฉากใน project.json</div>`}</div>
    </section>`;
}

async function selectProject(slug, changeHash = true) {
  selectedSlug = slug;
  renderProjects();
  if (changeHash) history.replaceState(null, "", `#${encodeURIComponent(slug)}`);
  const request = ++detailRequest;
  projectDetail.innerHTML = `<div class="detail-empty"><span class="empty-symbol">✳</span><p>กำลังอ่านรายละเอียด…</p></div>`;
  try {
    const detail = await getJson(`/api/projects/${encodeURIComponent(slug)}`);
    if (request === detailRequest) renderDetail(detail);
  } catch (error) {
    if (request === detailRequest) projectDetail.innerHTML = `<div class="detail-empty"><h2>เปิดโปรเจกต์ไม่ได้</h2><p>${escapeHtml(error.message)}</p></div>`;
  }
}

async function refresh() {
  refreshButton.disabled = true;
  try {
    projects = await getJson("/api/projects");
    const picker = document.querySelector('#flowProject');
    const previous = picker.value;
    picker.innerHTML = projects.length ? projects.map(project => `<option value="${escapeHtml(project.slug)}">${escapeHtml(project.title)}</option>`).join('') : '<option value="">ยังไม่มีโปรเจกต์</option>';
    if (projects.some(project => project.slug === previous)) picker.value = previous;
    const requested = requestedSlug();
    const slug = projects.some(project => project.slug === requested) ? requested : projects[0]?.slug;
    selectedSlug = slug || null;
    renderMetrics();
    renderProjects();
    if (slug) await selectProject(slug, false);
    else projectDetail.innerHTML = `<div class="detail-empty"><span class="empty-symbol">✳</span><h2>ยังไม่มีเรื่องในคลัง</h2><p>เริ่มด้วย <code>python tools/ani.py new my-film</code> แล้วรีเฟรชหน้านี้</p></div>`;
  } catch (error) {
    projectList.innerHTML = `<p class="loading-copy">อ่านข้อมูลไม่ได้: ${escapeHtml(error.message)}</p>`;
    projectDetail.innerHTML = `<div class="detail-empty"><h2>เชื่อมต่อ UI ไม่ได้</h2><p>${escapeHtml(error.message)}</p></div>`;
  } finally {
    refreshButton.disabled = false;
  }
}

projectList.addEventListener("click", event => {
  const card = event.target.closest("[data-slug]");
  if (card) selectProject(card.dataset.slug);
});
refreshButton.addEventListener("click", refresh);
window.addEventListener("hashchange", () => {
  const slug = requestedSlug();
  if (projects.some(project => project.slug === slug)) selectProject(slug, false);
});

refresh();

let flowPlan = null;
let flowBusy = false;
let flowRunning = false;
let flowLastJobState = null;
const flowMessage = document.querySelector('#flowMessage');
const flowUrl = document.querySelector('#flowUrl');
const flowButtons = [...document.querySelectorAll('.flow-actions button')];

function clearFlowPlan() {
  flowPlan = null;
  document.querySelector('#flowPlan').hidden = true;
  document.querySelector('#flowApprove').checked = false;
  document.querySelector('#flowRun').disabled = true;
}

function flowControls() {
  flowButtons.forEach(button => { button.disabled = flowBusy || flowRunning; });
  document.querySelector('#flowCookies').disabled = flowBusy || flowRunning;
  document.querySelector('#flowRun').disabled = flowBusy || flowRunning || !flowPlan || !document.querySelector('#flowApprove').checked;
}

async function flowPost(action, data) {
  const response = await fetch(`/api/flow/${action}`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data),
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || `HTTP ${response.status}`);
  return result;
}

async function flowAction(action, extra = {}) {
  if (flowBusy || flowRunning) return;
  flowBusy = true;
  flowMessage.textContent = 'กำลังเชื่อมต่อ Flow…';
  flowControls();
  try {
    const result = await flowPost(action, { project_url: flowUrl.value, ...extra });
    flowMessage.textContent = result.message || 'ดำเนินการแล้ว';
    await flowRefresh();
    return result;
  } catch (error) {
    flowMessage.textContent = error.message;
  } finally {
    flowBusy = false;
    flowControls();
  }
}

async function flowRefresh() {
  const status = await getJson('/api/flow/status');
  const agentReady = status.agent?.ready || status.ready || status.session_ready;
  document.querySelector('#flowBadge').textContent = agentReady ? 'พร้อมให้เอเจนท์ทำงาน' : 'รอเอเจนท์ตรวจล็อกอิน';
  document.querySelector('#flowBadge').className = `state-chip ${agentReady ? 'complete' : 'planning'}`;
  document.querySelector('#flowTitle').textContent = agentReady ? 'ล็อกอิน Flow แล้ว' : 'เอเจนท์ดูแลการสร้างให้คุณ';
  document.querySelector('#agentMessage').textContent = agentReady ? 'พร้อมรับคำสั่ง สร้างงาน และดาวน์โหลดผลกลับเข้าแดชบอร์ด' : status.agent?.message || 'เอเจนท์จะตรวจล็อกอิน Flow เมื่อเริ่มคำสั่งของคุณ';
  if (!document.querySelector('#agentBudget').dataset.edited) {
    document.querySelector('#agentBudget').value = status.agent?.policy?.credits_per_request ?? 10;
    document.querySelector('#agentAuto').checked = status.agent?.policy?.enabled || false;
  }
  document.querySelector('#flowMode').textContent = status.browser_mode === 'existing' ? 'โหมดปัจจุบัน: ใช้ Chrome ที่เปิดอยู่ — ไม่เปิดหน้าต่าง Chrome แยก' : 'โหมดปัจจุบัน: Chrome ของ ANI สำหรับล็อกอินหรือนำเข้า cookies';
  if (document.activeElement !== flowUrl && !flowUrl.dataset.edited) flowUrl.value = status.project_url || '';
  const job = status.job;
  flowRunning = job?.state === 'running';
  if (job) {
    document.querySelector('#flowJob').hidden = false;
    document.querySelector('#flowJobTitle').textContent = `${job.slug} · ${job.kind} · ${flowRunning ? 'กำลังสร้าง' : job.state === 'complete' ? 'จบการทำงาน — ตรวจไฟล์และข้อความด้านล่าง' : 'หยุดจากข้อผิดพลาด'}`;
    document.querySelector('#flowJobOutput').textContent = job.output || 'กำลังเริ่มงาน…';
    if (flowLastJobState === 'running' && !flowRunning) await refresh();
    flowLastJobState = job.state;
  }
  flowControls();
  return status;
}

flowUrl.addEventListener('input', () => { flowUrl.dataset.edited = 'true'; clearFlowPlan(); });
document.querySelector('#agentBudget').addEventListener('input', () => { document.querySelector('#agentBudget').dataset.edited = 'true'; });
document.querySelector('#agentAuto').addEventListener('change', () => { document.querySelector('#agentBudget').dataset.edited = 'true'; });
document.querySelector('#agentSavePolicy').addEventListener('click', async () => {
  try {
    await flowPost('policy', {enabled: document.querySelector('#agentAuto').checked, credits_per_request: Number(document.querySelector('#agentBudget').value)});
    delete document.querySelector('#agentBudget').dataset.edited;
    await flowRefresh();
    flowMessage.textContent = 'บันทึกการทำงานอัตโนมัติแล้ว';
  } catch (error) { flowMessage.textContent = error.message; }
});
document.querySelector('#flowProject').addEventListener('change', clearFlowPlan);
document.querySelector('#flowLogin').addEventListener('click', () => { clearFlowPlan(); flowAction('login'); });
document.querySelector('#flowExisting').addEventListener('click', () => { clearFlowPlan(); flowAction('existing', {existing_cdp: document.querySelector('#flowEndpoint').value.trim() || 'auto'}); });
document.querySelector('#flowCheck').addEventListener('click', () => { clearFlowPlan(); flowAction('check'); });
document.querySelector('#flowCookies').addEventListener('change', async event => {
  const file = event.target.files[0];
  if (!file) return;
  clearFlowPlan();
  try {
    if (file.size > 2 * 1024 * 1024) throw new Error('ไฟล์ cookies ต้องไม่เกิน 2 MB');
    const cookies = await file.text();
    await flowAction('import', { cookies });
  } catch (error) {
    flowMessage.textContent = error.message;
  } finally {
    event.target.value = '';
  }
});
document.querySelector('#flowApply').addEventListener('click', async () => {
  clearFlowPlan();
  const slug = document.querySelector('#flowProject').value;
  if (!slug) { flowMessage.textContent = 'สร้างเรื่องด้วย ANI.cmd new <slug> ก่อน'; return; }
  if (await flowAction('configure', { slug })) { flowMessage.textContent = 'บันทึกให้เรื่องนี้ใช้ Flow แล้ว'; await refresh(); }
});

async function previewFlow(kind) {
  clearFlowPlan();
  const slug = document.querySelector('#flowProject').value;
  if (!slug) { flowMessage.textContent = 'สร้างเรื่องและกรอกฉากก่อน'; return; }
  if (flowBusy || flowRunning) return;
  flowBusy = true;
  flowControls();
  flowMessage.textContent = 'กำลังอ่านเครดิตปัจจุบันจาก Flow…';
  try {
    flowPlan = await flowPost('plan', { slug, kind });
    document.querySelector('#flowPlanSummary').textContent = `Provider: Google Flow · ${flowPlan.kind === 'images' ? 'ภาพ' : 'คลิป'} · ฉาก: ${flowPlan.jobs.map(job => job.scene_id).join(', ')} · ${flowPlan.credits_per_job} เครดิต/งาน · ประมาณ ${flowPlan.estimated_credits} เครดิตรวม (แผนมีอายุ 5 นาที)`;
    document.querySelector('#flowPlan').hidden = false;
    flowMessage.textContent = 'ตรวจฉากและเครดิต แล้วกดยืนยันเพื่อเริ่มสร้าง';
  } catch (error) { flowMessage.textContent = error.message; }
  finally { flowBusy = false; flowControls(); }
}

document.querySelector('#flowPlanImages').addEventListener('click', () => previewFlow('images'));
document.querySelector('#flowPlanClips').addEventListener('click', () => previewFlow('clips'));
document.querySelector('#flowApprove').addEventListener('change', flowControls);
document.querySelector('#flowRun').addEventListener('click', async () => {
  if (!flowPlan || !document.querySelector('#flowApprove').checked || flowBusy || flowRunning) return;
  flowBusy = true;
  flowControls();
  try {
    await flowPost('run', { token: flowPlan.token, approved: true });
    clearFlowPlan();
    flowMessage.textContent = 'เริ่มแล้ว ระบบสร้างและดาวน์โหลดสื่อทีละฉาก สามารถดูสถานะด้านล่าง';
    document.querySelector('#flowJob').open = true;
    await flowRefresh();
  } catch (error) { flowMessage.textContent = error.message; clearFlowPlan(); }
  finally { flowBusy = false; flowControls(); }
});

flowRefresh().then(status => { flowMessage.textContent = status.message || 'เลือกวิธีเชื่อมต่อ หรือกดตรวจสอบเพื่อใช้เซสชันที่เก็บไว้'; }).catch(error => { flowMessage.textContent = error.message; });
setInterval(() => { if (!flowBusy) flowRefresh().catch(() => {}); }, 5000);
