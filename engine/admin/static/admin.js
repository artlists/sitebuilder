"use strict";

let token = sessionStorage.getItem("slutadmin_token") || "";
let data = null;
let dirty = false;
let publishRunning = false;
let lastLine = 0;
let currentTab = null;

const KIND_FIELDS_DEFAULT = [
  { kind: "music", text: ["span"], inputs: ["url", "img", "alt"] },
  { kind: "watch", text: ["caption"], inputs: ["src", "poster"], variant: true,
    variants: ["classic", "center", "portrait", "tall"] },
  { kind: "press", text: ["text"], inputs: ["url", "img"] },
  { kind: "news", text: ["span", "body"], inputs: ["img", "link", "link_label"],
    list: ["images"], colors: ["credit_color", "span_color", "text_color"],
    rich: ["body"] },
];

function kindDefs() {
  const k = data && data.kinds;
  const entries = (k && typeof k === "object" && Object.keys(k).length)
    ? Object.entries(k)
    : KIND_FIELDS_DEFAULT.map((d) => [d.kind, d]);
  return entries.map(([kind, def]) => ({
    kind,
    text: Array.isArray(def.text) ? def.text : [],
    inputs: Array.isArray(def.inputs) ? def.inputs : [],
    variants: Array.isArray(def.variants) ? def.variants : [],
    variant: Array.isArray(def.variants) && def.variants.length > 0,
    list: Array.isArray(def.list) ? def.list : [],
    colors: Array.isArray(def.colors) ? def.colors : ["credit_color", "span_color"],
    rich: Array.isArray(def.rich) ? def.rich : ["body"],
  }));
}

const META_GROUPS = [
  {
    title: "Site",
    keys: ["name", "logo_text", "bio_h2", "title", "domain", "favicon",
           "og_image_width", "og_image_height", "locale"],
  },
  {
    title: "SEO",
    keys: ["meta_description", "keywords", "og_description",
           "twitter_description", "job_title", "ld_description", "knows_about",
           "analytics_snippet"],
    textarea: ["meta_description", "keywords", "og_description",
               "twitter_description", "ld_description", "knows_about", "analytics_snippet"],
  },
  { title: "Social", keys: ["instagram_url", "instagram_handle", "bandcamp_url", "behance_url",
                            "booking_label", "instagram_label", "bandcamp_label"] },
];

const $ = (sel) => document.querySelector(sel);
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
}[c]));
const humanize = (k) => k.replace(/[_-]/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

function setDirty(v) {
  dirty = v;
  $("#dirty").classList.toggle("hidden", !v);
}

async function api(path, opts = {}) {
  const headers = { ...(opts.headers || {}) };
  if (token) headers["Authorization"] = "Bearer " + token;
  const sep = path.includes("?") ? "&" : "?";
  const site = curSite();
  const url = "/admin/api" + path + (site ? `${sep}site=${encodeURIComponent(site)}` : "");
  const res = await fetch(url, { ...opts, headers });
  let body = null;
  try { body = await res.json(); } catch (_) { /* empty */ }
  if (res.status === 401) { logout(); throw new Error("session expired"); }
  if (!res.ok) throw new Error((body && body.error) || res.statusText);
  return body;
}

let siteList = [];
let defaultSite = "";
let mediaFiles = [];

function curSite() {
  return sessionStorage.getItem("slutadmin_site") || defaultSite || "";
}

async function loadSites() {
  try {
    const r = await api("/sites");
    siteList = r.sites || [];
    defaultSite = r.default || (siteList[0] && siteList[0].slug) || "";
    if (!sessionStorage.getItem("slutadmin_site")) {
      sessionStorage.setItem("slutadmin_site", curSite());
    }
  } catch (_) { /* unauthenticated yet */ }
  renderSiteSwitcher();
}

function renderSiteSwitcher() {
  const cur = curSite() || defaultSite;
  const slugs = siteList.length ? siteList.map((s) => s.slug) : [cur];
  const el = $("#brand");
  if (el) {
    el.innerHTML = "Site · " + ddHTML("site", cur, slugs);
    const dd = el.querySelector(".dd");
    if (dd) {
      dd.addEventListener("ddchange", (ev) => switchSite(ev.detail.value));
      const foot = document.createElement("div");
      foot.className = "dd-foot";
      foot.innerHTML = "<button type=\"button\" class=\"dd-new\">＋ New site…</button>";
      foot.querySelector("button").addEventListener("click", openSitePanel);
      dd.querySelector(".dd-menu").appendChild(foot);
    }
  }
  const siteTitle = (siteList.find((s) => s.slug === cur) || {}).title || cur;
  $("#btnPreview").setAttribute("title", `saves first, then opens preview of ${siteTitle}`);
}

function switchSite(slug) {
  if (dirty && !confirm("Discard unsaved changes and switch site?")) return;
  sessionStorage.setItem("slutadmin_site", slug);
  location.reload();
}

function openSitePanel() {
  $("#siteMsg").textContent = "";
  $("#sitePanel").classList.remove("hidden");
  $("#siteSlug").focus();
}

async function createSite() {
  const slug = $("#siteSlug").value.trim().toLowerCase();
  const title = $("#siteTitle").value.trim();
  $("#siteMsg").textContent = "";
  $("#btnCreateSite").disabled = true;
  try {
    await api("/sites", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ slug, title }),
    });
    sessionStorage.setItem("slutadmin_site", slug);
    location.reload();
  } catch (err) {
    $("#siteMsg").textContent = err.message;
    $("#btnCreateSite").disabled = false;
  }
}

function logout() {
  token = "";
  sessionStorage.removeItem("slutadmin_token");
  $("#login").classList.remove("hidden");
  $("#app").classList.add("hidden");
}

function buildTabList() {
  const tabs = (data.pages || []).map((p) =>
    p.type === "info"
      ? { key: "bio", label: p.label, kind: "bio", page: p }
      : { key: p.id, label: p.label, kind: "gal", page: p }
  );
  tabs.push({ key: "pages", label: "Pages", kind: "pages" });
  tabs.push({ key: "meta", label: "Site & SEO", kind: "meta" });
  tabs.push({ key: "deploy", label: "Deploy", kind: "deploy" });
  return tabs;
}

function renderTabs() {
  const nav = $("#topTabs");
  nav.innerHTML = "";
  buildTabList().forEach((t) => {
    const b = document.createElement("button");
    b.className = "tab" + (currentTab && currentTab.key === t.key ? " active" : "");
    b.textContent = t.label;
    b.addEventListener("click", () => switchTo(t.key));
    nav.appendChild(b);
  });
}

function switchTo(key) {
  const tabs = buildTabList();
  const t = tabs.find((x) => x.key === key);
  if (!t) return;
  currentTab = t;
  renderTabs();

  document.querySelectorAll(".pane").forEach((p) => p.classList.remove("active"));

  if (t.kind === "gal") {
    $("#tab-items").classList.add("active");
    renderItems(t.page);
  } else if (t.kind === "bio") {
    $("#tab-bio").classList.add("active");
    const ig = $("#infoGlass");
    if (ig) ig.checked = !!data.site.info_glass;
    renderBio();
  } else if (t.kind === "pages") {
    $("#tab-pages").classList.add("active");
    const ha = $("#headerAnim");
    if (ha) ha.checked = !!data.site.header_animation;
    renderAnimCtl();
    renderPages();
  } else if (t.kind === "deploy") {
    $("#tab-deploy").classList.add("active");
    renderDeploy();
  } else {
    $("#tab-meta").classList.add("active");
    renderMeta();
  }
}

/* ---------- items ---------- */

function fieldEl(kind, key, value) {
  const tag = kind === "textarea" ? "textarea" : "input";
  return `<${tag} autocomplete="off" data-key="${key}" ${
    tag === "input" ? `value="${esc(value)}"` : ""
  }>${tag === "textarea" ? esc(value) : ""}</${tag}>`;
}

function ddHTML(key, value, options) {
  const cur = options.includes(value) ? value : options[0];
  const opts = options.map((o) =>
    `<button type="button" class="dd-option" data-val="${esc(o)}">${humanize(o)}</button>`).join("");
  return `<div class="dd" data-key="${key}" role="listbox">
      <button type="button" class="dd-trigger">
        <span class="dd-value">${humanize(cur)}</span>
        <span class="dd-caret" aria-hidden="true">▾</span>
      </button>
      <div class="dd-menu">${opts}</div>
    </div>`;
}

function pickHTML(attr) {
  if (!mediaFiles.length) return "";
  const opts = mediaFiles.map((f) =>
    `<button type="button" class="dd-option" data-val="${esc(f)}">${esc(f)}</button>`).join("");
  return `<span class="dd pick" ${attr} role="listbox" title="pick an uploaded file">
    <button type="button" class="dd-trigger pick-trigger">
      <span class="dd-value">▦ pick</span>
      <span class="dd-caret" aria-hidden="true">▾</span>
    </button>
    <div class="dd-menu">${opts}</div>
  </span>`;
}

function mediaPick(key) { return pickHTML(`data-key="${key}"`); }

function renderItems(page) {
  const tid = page.id;
  $("#itemsTitle").textContent = page.label;
  const items = data[tid] || (data[tid] = []);
  const defs = kindDefs();
  const wrap = $("#itemsCards");

  const COLOR_META = {
    credit_color: ["Credit color", "#999999"],
    span_color: ["Label color", "#ffffff"],
    text_color: ["Text color", "#111111"],
  };

  const colorField = (item, label, key, def) =>
    `<label>${label}<span class="color-row">` +
    `<input type="color" data-key="${key}" value="${esc(item[key] || def)}">` +
    `<span class="hexval">${item[key] ? esc(item[key]) : "default"}</span>` +
    `<button type="button" class="btn small" data-reset="${key}" title="reset to default">↺</button>` +
    `</span></label>`;

  const listField = (item, lk) => {
    const arr = Array.isArray(item[lk]) ? item[lk] : [];
    const rows = arr.map((val, li) =>
      `<span class="imgrow">
         <input class="li-inp" data-lkey="${lk}" data-li="${li}" value="${esc(val)}" autocomplete="off" placeholder="file name or URL">
         ${pickHTML(`data-lkey="${lk}" data-li="${li}"`)}
         <button type="button" class="btn small" data-lmove="${lk}" data-li="${li}" data-d="-1" title="up">↑</button>
         <button type="button" class="btn small" data-lmove="${lk}" data-li="${li}" data-d="1" title="down">↓</button>
         <button type="button" class="btn small" data-ldel="${lk}" data-li="${li}" title="delete">✕</button>
       </span>`).join("");
    return `<label>${humanize(lk)}<span class="imglist">${rows}<button type="button" class="btn small" data-ladd="${lk}">+ add image</button></span></label>`;
  };

  const fmtToolbar = () =>
    `<div class="fmt">
       <button class="btn small" data-fmt="strong" title="Bold">B</button>
       <button class="btn small" data-fmt="em" title="Italic"><i>I</i></button>
       <button class="btn small" data-fmt="a" title="Link">link</button>
     </div>`;

  wrap.innerHTML = items.map((item, i) => {
    const v = defs.find((f) => f.kind === item.kind) || defs[0];
    const inputsHtml = v.inputs.map((k) =>
      `<label>${humanize(k)}${fieldEl("input", k, item[k])}${(k === "img" || k === "poster" || k === "audio") ? mediaPick(k) : ""}</label>`).join("");
    const textsHtml = v.text.map((k) => {
      const ta = `<label>${humanize(k)}${fieldEl("textarea", k, item[k])}</label>`;
      return (v.rich || []).includes(k)
        ? `<div class="rich">${fmtToolbar()}${ta}</div>`
        : ta;
    }).join("");
    const variantHtml = v.variant
      ? `<label>Variant${ddHTML("variant", item.variant, v.variants)}</label>`
      : "";
    const glassHtml = (item.kind === "news" || item.kind === "music")
      ? `<label class="sw sw-page"><input type="checkbox" data-key="glass" ${item.glass ? "checked" : ""}><span class="sw-track"></span><span class="sw-label">Glass backdrop</span></label>`
      : "";
    const creditHtml = `<label>Credit${fieldEl("input", "credit", item.credit)}</label>`;
    const colorsHtml = (v.colors || []).map((ck) => {
      const [cl, cd] = COLOR_META[ck] || [humanize(ck), "#000000"];
      return colorField(item, cl, ck, cd);
    }).join("");
    const listsHtml = (v.list || []).map((lk) => listField(item, lk)).join("");

    return `<div class="card" data-cat="${tid}" data-idx="${i}">
      <div class="card-head">
        <span class="idx">${i + 1}</span>
        <span class="moves">
          <button class="btn small" data-move="${i}" data-d="-1" title="up">↑</button>
          <button class="btn small" data-move="${i}" data-d="1" title="down">↓</button>
          <button class="btn small" data-del="${i}" title="delete">✕</button>
        </span>
      </div>
      <div class="fields grid2">
        <label>Kind${ddHTML("kind", item.kind, defs.map((f) => f.kind))}</label>
        ${inputsHtml}
        ${textsHtml}
        ${variantHtml}
        ${glassHtml}
        ${creditHtml}
        ${colorsHtml}
        ${listsHtml}
      </div>
    </div>`;
  }).join("");

  wrap.querySelectorAll("input[type=checkbox][data-key]").forEach((el) => {
    const idx = +el.closest(".card").dataset.idx;
    const key = el.dataset.key;
    el.addEventListener("change", () => {
      data[tid][idx][key] = el.checked;
      setDirty(true);
    });
  });

  wrap.querySelectorAll("input[data-key]:not([type=checkbox]), textarea[data-key]").forEach((el) => {
    const idx = +el.closest(".card").dataset.idx;
    const key = el.dataset.key;
    const onChange = () => {
      data[tid][idx][key] = el.value;
      if (el.type === "color") {
        const hv = el.closest("label").querySelector(".hexval");
        if (hv) hv.textContent = el.value;
      }
      setDirty(true);
    };
    el.addEventListener("input", onChange);
    el.addEventListener("change", onChange);
  });

  wrap.querySelectorAll("input[data-lkey]").forEach((el) => {
    const card = el.closest(".card");
    const lk = el.dataset.lkey, li = +el.dataset.li;
    const upd = () => { data[tid][+card.dataset.idx][lk][li] = el.value; setDirty(true); };
    el.addEventListener("input", upd);
    el.addEventListener("change", upd);
  });

  wrap.querySelectorAll("[data-reset]").forEach((b) =>
    b.addEventListener("click", (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      delete data[tid][+b.closest(".card").dataset.idx][b.dataset.reset];
      setDirty(true);
      renderItems(page);
    }));

  wrap.querySelectorAll(".dd[data-lkey]").forEach((dd) => {
    const idx = +dd.closest(".card").dataset.idx;
    dd.addEventListener("ddchange", (ev) => {
      const lk = dd.dataset.lkey, li = +dd.dataset.li;
      data[tid][idx][lk][li] = ev.detail.value;
      const inp = dd.parentNode.querySelector(`input[data-lkey="${lk}"][data-li="${li}"]`);
      if (inp) inp.value = ev.detail.value;
      setDirty(true);
    });
  });

  wrap.querySelectorAll("[data-ladd]").forEach((b) =>
    b.addEventListener("click", () => {
      const card = b.closest(".card");
      const it = data[tid][+card.dataset.idx];
      const lk = b.dataset.ladd;
      (it[lk] = Array.isArray(it[lk]) ? it[lk] : []).push("");
      setDirty(true); renderItems(page);
    }));

  wrap.querySelectorAll("[data-ldel]").forEach((b) =>
    b.addEventListener("click", () => {
      const card = b.closest(".card");
      data[tid][+card.dataset.idx][b.dataset.ldel].splice(+b.dataset.li, 1);
      setDirty(true); renderItems(page);
    }));

  wrap.querySelectorAll("[data-lmove]").forEach((b) =>
    b.addEventListener("click", () => {
      const card = b.closest(".card");
      const arr = data[tid][+card.dataset.idx][b.dataset.lmove];
      const i = +b.dataset.li, j = i + (+b.dataset.d);
      if (j < 0 || j >= arr.length) return;
      const [x] = arr.splice(i, 1); arr.splice(j, 0, x);
      setDirty(true); renderItems(page);
    }));

  wrap.querySelectorAll(".dd[data-key]").forEach((dd) => {
    const idx = +dd.closest(".card").dataset.idx;
    dd.addEventListener("ddchange", (ev) => {
      data[tid][idx][dd.dataset.key] = ev.detail.value;
      setDirty(true);
      if (dd.dataset.key === "kind") renderItems(page);
      else {
        const inp = dd.parentNode.querySelector(`input[data-key="${dd.dataset.key}"]`);
        if (inp) inp.value = ev.detail.value;
      }
    });
  });

  wrap.querySelectorAll(".rich [data-fmt]").forEach((b) =>
    b.addEventListener("click", () => {
      const ta = b.closest(".rich").querySelector("textarea");
      applyFmt(ta, b.dataset.fmt);
      ta.dispatchEvent(new Event("input", { bubbles: true }));
    }));

  wrap.querySelectorAll("[data-move]").forEach((b) =>
    b.addEventListener("click", () => moveItem(tid, +b.dataset.move, +b.dataset.d, page)));
  wrap.querySelectorAll("[data-del]").forEach((b) =>
    b.addEventListener("click", () => deleteItem(tid, +b.dataset.del, page)));
}

function addItem() {
  const t = currentTab;
  if (!t || t.kind !== "gal") return;
  data[t.page.id].push({ kind: "music", credit: "" });
  setDirty(true);
  renderItems(t.page);
}

function moveItem(tid, idx, d, page) {
  const items = data[tid];
  const j = idx + d;
  if (j < 0 || j >= items.length) return;
  const [a] = items.splice(idx, 1);
  items.splice(j, 0, a);
  setDirty(true);
  renderItems(page);
}

function deleteItem(tid, idx, page) {
  data[tid].splice(idx, 1);
  setDirty(true);
  renderItems(page);
}

/* ---------- pages ---------- */

function slugify(label) {
  let s = label.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
  if (!s) s = "page";
  if (s === "info") s = "page";
  const used = new Set((data.pages || []).map((p) => p.id));
  let cand = s, n = 2;
  while (used.has(cand)) cand = `${s}-${n++}`;
  return cand;
}

function renderAnimCtl() {
  const ctl = $("#headerAnimCtl");
  if (!ctl) return;
  const style = data.site.header_animation_style || "inside";
  const col = (data.site.header_animation_color || "").trim();
  const ocol = (data.site.header_animation_outline_color || "").trim();
  const oon = !!data.site.header_animation_outline;
  const gglass = !!data.site.header_animation_glass;
  ctl.innerHTML =
    `<label class="sw-caption">Style${ddHTML("headerAnimStyle", style, ["inside", "outside"])}</label>` +
    `<label class="sw"><input type="checkbox" data-anim-glass ${gglass ? "checked" : ""}><span class="sw-track"></span><span class="sw-label">Glass label</span></label>` +
    `<label class="sw-caption">Color<span class="color-row">` +
    `<input type="color" data-anim-color value="${col || "#ffffff"}">` +
    `<span class="hexval">${col ? esc(col) : "default"}</span>` +
    `<button type="button" class="btn small" data-anim-color-reset title="reset to default">↺</button>` +
    `</span></label>` +
    `<label class="sw"><input type="checkbox" data-anim-outline ${oon ? "checked" : ""}><span class="sw-track"></span><span class="sw-label">Letters outline</span></label>` +
    `<label class="sw-caption">Outline color<span class="color-row">` +
    `<input type="color" data-anim-outline-color value="${ocol || "#000000"}" ${oon ? "" : "disabled"}>` +
    `<span class="hexval">${ocol ? esc(ocol) : "default"}</span>` +
    `<button type="button" class="btn small" data-anim-outline-reset ${oon ? "" : "disabled"} title="reset to default">↺</button>` +
    `</span></label>`;

  const bindOutline = () => {
    const ob = ctl.querySelector("[data-anim-outline]");
    const oc = ctl.querySelector("[data-anim-outline-color]");
    const or = ctl.querySelector("[data-anim-outline-reset]");
    const hex = ctl.querySelector(".color-row:last-of-type .hexval");
    const gg = ctl.querySelector("[data-anim-glass]");
    if (gg) gg.addEventListener("change", () => {
      data.site.header_animation_glass = gg.checked;
      setDirty(true);
    });
    if (ob) ob.addEventListener("change", () => {
      data.site.header_animation_outline = ob.checked;
      oc.disabled = !ob.checked;
      or.disabled = !ob.checked;
      setDirty(true);
    });
    if (oc) oc.addEventListener("input", () => {
      data.site.header_animation_outline_color = oc.value;
      hex.textContent = oc.value.toUpperCase();
      setDirty(true);
    });
    if (or) or.addEventListener("click", () => {
      delete data.site.header_animation_outline_color;
      oc.value = "#000000";
      hex.textContent = "default";
      setDirty(true);
    });
  };

  const dd = ctl.querySelector(".dd");
  dd.addEventListener("ddchange", (ev) => {
    data.site.header_animation_style = ev.detail.value;
    setDirty(true);
  });
  const ci = ctl.querySelector("[data-anim-color]");
  ci.addEventListener("input", () => {
    data.site.header_animation_color = ci.value;
    ctl.querySelector(".color-row:first-of-type .hexval").textContent = ci.value.toUpperCase();
    setDirty(true);
  });
  const cr = ctl.querySelector("[data-anim-color-reset]");
  if (cr) cr.addEventListener("click", () => {
    delete data.site.header_animation_color;
    ci.value = "#ffffff";
    ctl.querySelector(".color-row:first-of-type .hexval").textContent = "default";
    setDirty(true);
  });
  bindOutline();
}

function renderPages() {
  const wrap = $("#pagesCards");
  wrap.innerHTML = (data.pages || []).map((p, i) => {
    const isInfo = p.type === "info";
    return `<div class="card page-card" data-idx="${i}">
      <div class="card-head">
        <span class="idx">${i + 1}</span>
        <span class="kind-note">${isInfo ? "bio" : "page"}</span>
        <span class="id-note">${esc(p.id)}</span>
        <span class="moves">
          <button class="btn small" data-move="${i}" data-d="-1" title="up">↑</button>
          <button class="btn small" data-move="${i}" data-d="1" title="down">↓</button>
          <button class="btn small" data-del="${i}" ${isInfo ? "disabled" : ""} title="delete">✕</button>
        </span>
      </div>
      <div class="fields grid2">
        <label>Label<input data-key="label" value="${esc(p.label)}" autocomplete="off"></label>
        <label class="sw sw-page"><input type="checkbox" data-key="show_in_menu" ${p.show_in_menu === false ? "" : "checked"}><span class="sw-track"></span><span class="sw-label">Shown in menu</span></label>
      </div>
    </div>`;
  }).join("");

  wrap.querySelectorAll("input[data-key='label']").forEach((el) => {
    const i = +el.closest(".card").dataset.idx;
    el.addEventListener("input", () => { data.pages[i].label = el.value; renderTabs(); setDirty(true); });
  });
  wrap.querySelectorAll("input[data-key='show_in_menu']").forEach((el) => {
    const i = +el.closest(".card").dataset.idx;
    el.addEventListener("change", () => { data.pages[i].show_in_menu = el.checked; setDirty(true); });
  });
  wrap.querySelectorAll("[data-move]").forEach((b) =>
    b.addEventListener("click", () => {
      if (b.hasAttribute("disabled")) return;
      movePage(+b.dataset.move, +b.dataset.d);
    }));
  wrap.querySelectorAll("[data-del]").forEach((b) =>
    b.addEventListener("click", () => {
      if (b.hasAttribute("disabled")) return;
      deletePage(+b.dataset.del);
    }));
}

function addPage() {
  const label = prompt("New page name:", "");
  if (!label) return;
  const id = slugify(label);
  data.pages.push({ id, label: label.trim(), type: "gallery", show_in_menu: true });
  data[id] = [];
  setDirty(true);
  renderPages();
  renderTabs();
}

function movePage(idx, d) {
  const j = idx + d;
  if (j < 0 || j >= data.pages.length) return;
  const [a] = data.pages.splice(idx, 1);
  data.pages.splice(j, 0, a);
  setDirty(true);
  renderPages();
  renderTabs();
}

function deletePage(idx) {
  const p = data.pages[idx];
  if (p.type === "info") return;
  if (!confirm(`Delete page «${p.label}» with all its items?`)) return;
  data.pages.splice(idx, 1);
  delete data[p.id];
  setDirty(true);
  renderPages();
  renderTabs();
}

/* ---------- deploy ---------- */

let dpCurrent = null;
let dpInfo = null;

function applyDeployProvider(p) {
  dpCurrent = p;
  const showProject = p === "cloudflare_pages" || p === "netlify";
  const showRepo = p === "github_pages";
  const showDomain = p === "surge" || p === "cloudflare_pages";
  $("#dpProjectWrap").classList.toggle("hidden", !showProject);
  $("#dpRepoWrap").classList.toggle("hidden", !showRepo);
  $("#dpDomainWrap").classList.toggle("hidden", !showDomain);
  const slug = curSite() || "";
  if (p === "netlify") {
    $("#dpProject").placeholder = slug ? `${slug} (netlify site ID or slug; blank = create new)` : "netlify site ID or slug; blank = create new";
  } else if (p === "cloudflare_pages") {
    $("#dpProject").placeholder = slug ? `${slug} -- gives https://${slug}.pages.dev` : "your-pages-project-name";
  }
  if (p === "surge") {
    $("#dpDomain").placeholder = slug ? `${slug}.surge.sh` : "name.surge.sh";
  } else if (p === "cloudflare_pages") {
    $("#dpDomain").placeholder = slug ? `https://${slug}.pages.dev (optional, custom domain)` : "https://name.pages.dev (optional — custom domain)";
  }
  $("#dpRepo").placeholder = p === "github_pages" ? "you/your-repo" : "";
  $("#dpToken").placeholder = ({
    cloudflare_pages: "Cloudflare API token → Account.Read + Pages.Edit",
    github_pages: "GitHub token → public_repo scope",
    netlify: "Netlify personal access token",
    surge: "Surge token — run `surge token`",
    neocities: "Neocities API key",
  }[p] || "provider API token");
}

async function renderDeploy() {
  const info = await api("/deploy");
  dpInfo = info;
  const cfg = info.config || {};
  const prov = cfg.provider || info.providers[0];
  $("#dpProvider").innerHTML = ddHTML("provider", prov, info.providers);
  $("#dpProvider .dd").addEventListener("ddchange", (e) => applyDeployProvider(e.detail.value));
  const slug = curSite() || "";
  const projVal = cfg.project_name || "";
  $("#dpProject").value = projVal;
  $("#dpRepo").value = cfg.repo || "";
  $("#dpDomain").value = cfg.domain || "";
  $("#dpToken").value = "";
  applyDeployProvider(prov);
  $("#dpCredsStatus").innerHTML = info.providers.map((p) =>
    `<span class="cred ${info.creds[p] ? "cred-ok" : "cred-miss"}">${p.replace(/_/g, " ")} · ${info.creds[p] ? "token set" : "no token"}</span>`).join("");
  $("#btnSaveDeploy").onclick = saveDeploy;
  const lbl = $("#dpSiteLabel");
  if (lbl) lbl.textContent = `Site: ${info.site}${slug ? " · slug: " + slug : ""}`;
  renderDeployHistory();
}

async function saveDeploy() {
  if (!dpCurrent) return;
  const body = {
    deploy: {
      provider: dpCurrent,
      project_name: $("#dpProject").value.trim(),
      domain: $("#dpDomain").value.trim(),
      repo: $("#dpRepo").value.trim(),
    },
    credentials: { [dpCurrent]: $("#dpToken").value.trim() },
  };
  $("#btnSaveDeploy").disabled = true;
  try {
    await api("/deploy", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    flash($("#btnSaveDeploy"), "saved");
    renderDeploy();
  } catch (err) {
    alert("Deploy config failed:\n" + err.message);
  } finally {
    $("#btnSaveDeploy").disabled = false;
  }
}

async function renderDeployHistory() {
  const box = $("#dpHistory");
  try {
    const { runs } = await api("/history");
    box.innerHTML = runs.length
      ? runs.slice().reverse().map((r) =>
        `<div class="deploy-run ${r.ok ? "run-ok" : "run-fail"}">
          <span class="run-ts">${esc(r.ts)}</span>
          <span class="run-kind">${esc(r.provider)}${r.project ? " · " + esc(r.project) : ""}</span>
          <span class="run-code run-${r.ok ? "ok" : "fail"}">${r.ok ? "ok" : "failed"}</span>
        </div>`).join("")
      : '<span class="hint">no deploys yet</span>';
  } catch (err) {
    box.innerHTML = '<span class="hint">' + esc(err.message) + "</span>";
  }
}

function exportData() {
  fetch("/admin/api/export", { headers: { Authorization: "Bearer " + token } })
    .then((res) => {
      if (!res.ok) throw new Error("export failed: " + res.status);
      return res.blob();
    })
    .then((blob) => {
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = "data.json";
      a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 5000);
      flash($("#btnExport"), "exported");
    })
    .catch((err) => alert(err.message));
}

async function importData(file) {
  if (!file) return;
  $("#backupMsg").textContent = "importing…";
  try {
    const text = await file.text();
    const res = await fetch("/admin/api/import", {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: "Bearer " + token },
      body: text,
    });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).error || res.statusText);
    $("#backupMsg").textContent = "imported — reloading…";
    await api("/data");            // refresh in-memory data
    enter();                       // re-render everything
    renderDeploy();
    renderDeployHistory();
    refreshMedia();
  } catch (err) {
    $("#backupMsg").textContent = "import failed: " + err.message;
  }
}

/* ---------- bio ---------- */

function renderBio() {
  const wrap = $(".bio-list");
  wrap.innerHTML = data.bio.map((p, i) => `
    <div class="card" data-idx="${i}">
      <div class="card-head">
        <span class="idx">${i + 1}</span>
        <span class="moves">
          <button class="btn small" data-move="${i}" data-d="-1" title="up">↑</button>
          <button class="btn small" data-move="${i}" data-d="1" title="down">↓</button>
          <button class="btn small" data-del="${i}" title="delete">✕</button>
        </span>
      </div>
      <div class="fmt">
        <button class="btn small" data-fmt="strong" title="Bold">B</button>
        <button class="btn small" data-fmt="em" title="Italic"><i>I</i></button>
        <button class="btn small" data-fmt="a" title="Link">link</button>
      </div>
      <textarea autocomplete="off">${esc(p)}</textarea>
    </div>`).join("");

  wrap.querySelectorAll("textarea").forEach((ta) => {
    const idx = +ta.closest(".card").dataset.idx;
    ta.addEventListener("input", () => { data.bio[idx] = ta.value; setDirty(true); });
  });
  wrap.querySelectorAll("[data-fmt]").forEach((b) =>
    b.addEventListener("click", () => {
      const card = b.closest(".card");
      const ta = card.querySelector("textarea");
      applyFmt(ta, b.dataset.fmt);
      data.bio[+card.dataset.idx] = ta.value;
      setDirty(true);
    }));
  wrap.querySelectorAll("[data-move]").forEach((b) =>
    b.addEventListener("click", () => moveBio(+b.dataset.move, +b.dataset.d)));
  wrap.querySelectorAll("[data-del]").forEach((b) =>
    b.addEventListener("click", () => {
      data.bio.splice(+b.dataset.del, 1);
      setDirty(true); renderBio();
    }));
}

function applyFmt(ta, kind) {
  const s = ta.selectionStart;
  const e = ta.selectionEnd;
  const sel = ta.value.slice(s, e);
  const tags = { strong: ["<strong>", "</strong>"], em: ["<em>", "</em>"],
                 a: ['<a href="">', "</a>"] };
  const [open, close] = tags[kind];
  const body = sel || (kind === "a" ? "link" : "");
  ta.value = ta.value.slice(0, s) + open + body + close + ta.value.slice(e);
  ta.focus();
  if (kind === "a") {
    const p = s + 9;
    ta.setSelectionRange(p, p + body.length);
  } else {
    ta.setSelectionRange(s + open.length, s + open.length + body.length);
  }
}

function moveBio(idx, d) {
  const j = idx + d;
  if (j < 0 || j >= data.bio.length) return;
  const [a] = data.bio.splice(idx, 1);
  data.bio.splice(j, 0, a);
  setDirty(true);
  renderBio();
}

/* ---------- meta ---------- */

function metaValue(k) {
  if (k === "knows_about") return (data.seo.knows_about || []).join(", ");
  return data.site[k] ?? data.seo[k] ?? data.social[k];
}

function metaApply(k, raw) {
  if (k === "knows_about") {
    data.seo[k] = raw.split(",").map((s) => s.trim()).filter(Boolean);
    return;
  }
  const num = k === "og_image_width" || k === "og_image_height";
  for (const sec of ["site", "seo", "social"]) data[sec][k] = num ? parseFloat(raw) || 0 : raw;
}

function renderMeta() {
  const grid = $(".meta-grid");
  grid.innerHTML = META_GROUPS.map((g) => {
    const fields = g.keys.map((k) => {
      const isTextarea = g.textarea && g.textarea.includes(k);
      const isNum = k === "og_image_width" || k === "og_image_height";
      if (isTextarea) {
        return `<label>${humanize(k)}<textarea data-sec="meta" k="${k}" autocomplete="off">${esc(metaValue(k))}</textarea></label>`;
      }
      return `<label>${humanize(k)}<input data-sec="meta" k="${k}" type="${isNum ? "number" : "text"}" autocomplete="off" value="${esc(metaValue(k))}"></label>`;
    }).join("");
    return `<fieldset><legend>${g.title}</legend><div class="fields">${fields}</div></fieldset>`;
  }).join("");

  data.site.theme = data.site.theme || {};
  const th = data.site.theme;
  const heroVal = (data.site.hero || "").trim();
  const thc = (k) => th[k] && th[k].trim() ? th[k] : "";
  const col = (k, def) => thc(k) || def;
  const himg = heroVal
    ? `<div class="himg-prev" data-himg><img src="/admin/api/file?name=${encodeURIComponent(heroVal)}&site=${encodeURIComponent(curSite())}" onerror="this.style.display='none'"></div>`
    : `<div class="himg-prev" data-himg></div>`;
  grid.insertAdjacentHTML("beforeend", `<fieldset><legend>Theme</legend><div class="fields">
    <label>Page color<input type="color" data-th="background_color" value="${col("background_color", "#ffffff")}"><span class="hexval">${col("background_color", "#ffffff")}</span></label>
    <label>Text color<input type="color" data-th="text_color" value="${col("text_color", "#000000")}"><span class="hexval">${col("text_color", "#000000")}</span></label>
    <label>Header text color<input type="color" data-th="header_text_color" value="${col("header_text_color", "#ffffff")}"><span class="hexval">${col("header_text_color", "#ffffff")}</span></label>
    <label>Header image<input data-th="header_image" type="text" autocomplete="off" value="${esc(heroVal)}" placeholder="file name or URL">${mediaPick("header_image")}</label>
    ${himg}
    <label>Page background image<input data-th="background_image" type="text" autocomplete="off" value="${esc(thc("background_image"))}" placeholder="file name or URL">${mediaPick("background_image")}</label>
  </div></fieldset>`);

  grid.querySelectorAll("[data-sec='meta']").forEach((el) => {
    const k = el.getAttribute("k");
    el.addEventListener("input", () => metaApply(k, el.value));
    if (k === "favicon") el.insertAdjacentHTML("afterend", mediaPick(k));
  });

  grid.querySelectorAll(".dd.pick").forEach((dd) => {
    const k = dd.dataset.key;
    dd.addEventListener("ddchange", (ev) => {
      if (k === "header_image") {
        data.site.hero = ev.detail.value;
      } else if (k === "background_image") {
        data.site.theme.background_image = ev.detail.value;
      } else {
        metaApply(k, ev.detail.value);
      }
      const inp = dd.parentNode.querySelector(`input[data-th="${k}"], input[k="${k}"]`);
      if (inp) inp.value = ev.detail.value;
      setDirty(true);
    });
  });

  grid.querySelectorAll("[data-th]").forEach((el) => {
    el.addEventListener("input", () => {
      const k = el.dataset.th;
      if (el.type === "checkbox") {
        data.site[k] = el.checked;
        return;
      }
      if (k === "header_image") {
        data.site.hero = el.value.trim();
        el.closest("label").parentNode.querySelector("[data-himg]").innerHTML =
          el.value.trim()
            ? `<img src="/admin/api/file?name=${encodeURIComponent(el.value.trim())}&site=${encodeURIComponent(curSite())}" onerror="this.style.display='none'">`
            : "";
      } else if (el.value) {
        data.site.theme[k] = el.value;
      } else {
        delete data.site.theme[k];
      }
      if (el.type === "color") {
        const hv = el.closest("label").querySelector(".hexval");
        if (hv) hv.textContent = el.value;
      }
      setDirty(true);
    });
  });
}

/* ---------- global actions ---------- */

async function saveData() {
  $("#btnSave").disabled = true;
  try {
    const r = await api("/data", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) });
    if (r.ok) { setDirty(false); flash($("#btnSave"), "saved"); }
  } catch (err) {
    alert("Save failed:\n" + err.message);
  } finally {
    $("#btnSave").disabled = false;
  }
}

async function openPreview() {
  const win = window.open("", "_blank");
  if (!win) {
    alert("Pop-up blocked by the browser — allow pop-ups for 127.0.0.1");
    return;
  }
  win.document.write(
    "<!DOCTYPE html><html><body style='font-family:Inter,sans-serif;color:#888;padding:2em'>" +
    "loading preview…</body></html>"
  );
  win.document.close();
  try {
    if (dirty) {
      const r = await api("/data", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      });
      if (!r.ok) { win.close(); alert("Save failed — preview not opened"); return; }
      setDirty(false);
    }
    win.location.href = "/preview/" + encodeURIComponent(curSite()) + "/";
  } catch (err) {
    win.close();
    alert("Save failed: " + err.message);
  }
}

function openVisualEditor() {
  const win = window.open("", "_blank");
  if (!win) {
    alert("Pop-up blocked by the browser — allow pop-ups for 127.0.0.1");
    return;
  }
  const url = "/preview/" + encodeURIComponent(curSite()) + "/?edit=1";
  win.location.href = url;
}

function focusEditPath(path, site) {
  if (site && site !== curSite()) return;
  const parts = (path || "").split("/").filter(Boolean);
  const cat = parts[0];
  const idx = parts[1] != null ? parseInt(parts[1], 10) : null;
  const field = parts[2] || "";
  if (!cat) return;
  if (cat === "bio") {
    switchTo("bio");
    const card = $("#tab-bio");
    if (card) {
      card.scrollIntoView({ behavior: "smooth", block: "start" });
      flashPane(card);
    }
    const ta = $("#bioText") || document.querySelector("#tab-bio textarea, #tab-bio [data-key]");
    if (ta) { ta.scrollIntoView({ behavior: "smooth", block: "center" }); highlightField(ta); }
    return;
  }
  switchTo(cat);
  const card = document.querySelector(`#itemsCards .card[data-cat="${cat}"][data-idx="${idx}"]`);
  if (!card) {
    const first = document.querySelector(`#itemsCards .card[data-cat="${cat}"]`);
    if (first) first.scrollIntoView({ behavior: "smooth", block: "start" });
    return;
  }
  card.scrollIntoView({ behavior: "smooth", block: "center" });
  flashPane(card);
  if (field) {
    const ta = card.querySelector(`[data-key="${field}"], textarea[data-key="${field}"]`);
    if (ta) highlightField(ta);
  }
}

function flashPane(el) {
  el.classList.remove("edit-flash");
  void el.offsetWidth;
  el.classList.add("edit-flash");
  setTimeout(() => el.classList.remove("edit-flash"), 2000);
}

function highlightField(el) {
  el.focus({ preventScroll: true });
  el.classList.add("edit-field-flash");
  setTimeout(() => el.classList.remove("edit-field-flash"), 2000);
}

function applyEditSave(path, value) {
  const parts = (path || "").split("/").filter(Boolean);
  try {
    if (parts[0] === "bio") {
      const i = +parts[1];
      if (!Number.isInteger(i) || i < 0 || i >= data.bio.length) return false;
      data.bio[i] = value;
      return true;
    }
    const i = +parts[1];
    if (!data[parts[0]] || !Number.isInteger(i) || i < 0 || i >= data[parts[0]].length) return false;
    data[parts[0]][i][parts[2]] = value;
    return true;
  } catch (_) {
    return false;
  }
}

function setupVisualEditor() {
  const btn = $("#btnVisualEditor");
  if (btn) btn.addEventListener("click", openVisualEditor);
  window.addEventListener("message", async (ev) => {
    if (!ev.data) return;
    if (ev.data.type === "slut-site-edit") {
      focusEditPath(ev.data.path, ev.data.site);
    } else if (ev.data.type === "slut-site-edit-save") {
      if (!applyEditSave(ev.data.path, ev.data.value)) return;
      setDirty(true);
      try {
        const r = await api("/data", {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(data),
        });
        if (r.ok) {
          setDirty(false);
          if (ev.source) ev.source.postMessage({ type: "slut-site-edit-reload" }, "*");
          const parts = (ev.data.path || "").split("/").filter(Boolean);
          if (parts[0] === "bio") {
            renderBio();
          } else if (parts[0] && currentTab && currentTab.kind === "gal") {
            renderItems(currentTab.page);
          }
        } else {
          if (ev.source) ev.source.postMessage({ type: "slut-site-edit-error", message: "Save rejected by server" }, "*");
        }
      } catch (err) {
        if (ev.source) ev.source.postMessage({ type: "slut-site-edit-error", message: (err && err.message) || "Save failed" }, "*");
      }
    }
  });
}

async function buildOnly() {
  const log = openPublish("Build", "building review copy…");
  try {
    const r = await api("/build", { method: "POST" });
    log((r.output || "") + (r.ok ? "\n✓ build ok" : "\n✗ build failed"));
  } catch (err) {
    log("✗ " + err.message);
  }
}

function openPublish(title, note) {
  const panel = $("#publishPanel");
  panel.classList.remove("hidden");
  const logEl = $("#publishLog");
  logEl.textContent = note + "\n";
  $("#publishTitle").textContent = title;
  return (text) => {
    logEl.textContent += text + "\n";
    logEl.scrollTop = logEl.scrollHeight;
  };
}

async function startPublish() {
  if (publishRunning) return;
  if (dirty) {
    if (!confirm("Unsaved changes will be lost. Publish anyway?")) return;
  }

  // Pre-deploy validation (fail fast before triggering the worker)
  if (dpInfo && dpCurrent) {
    const cfg = dpInfo.config || {};
    const creds = dpInfo.creds || {};
    const p = cfg.provider || dpCurrent;
    const missing = [];
    if (!creds[p]) missing.push("API token not set (add it on the Deploy tab and press Save)");
    if (p === "cloudflare_pages" || p === "netlify") {
      if (!($("#dpProject").value.trim() || cfg.project_name))
        missing.push(`project name empty → Deploy tab > Project (e.g. "${curSite() || "your-project"}")`);
    }
    if (p === "github_pages") {
      if (!($("#dpRepo").value.trim() || cfg.repo))
        missing.push("repo empty → Deploy tab > Repo (user/repo)");
    }
    if (p === "surge") {
      if (!($("#dpDomain").value.trim() || cfg.domain))
        missing.push("domain empty → Deploy tab > Domain (name.surge.sh)");
    }
    if (missing.length) {
      alert("Publish can't start yet:\n\n • " + missing.join("\n • ") +
            "\n\nSave the Deploy tab first, then press Publish.");
      if (!currentTab || currentTab.kind !== "deploy") switchTo("deploy");
      return;
    }
  }

  publishRunning = true;
  $("#btnPublish").disabled = true;
  const log = openPublish("Publish", "…");
  try {
    await api("/publish", { method: "POST" });
  } catch (err) {
    log("✗ " + err.message);
    publishRunning = false;
    $("#btnPublish").disabled = false;
    return;
  }
  const poll = async () => {
    try {
      const st = await api("/status");
      if (st.log) log("\n" + st.log.trim());
      if (!st.running) {
        publishRunning = false;
        $("#btnPublish").disabled = false;
        const ok = st.exit_code === 0;
        log(ok ? "\n✓ published" : `\n✗ publish failed (exit ${st.exit_code})`);
        return;
      }
      setTimeout(poll, 1500);
    } catch (err) {
      publishRunning = false;
      $("#btnPublish").disabled = false;
      log("✗ " + err.message);
    }
  };
  setTimeout(poll, 500);
}

function flash(el, text) {
  const old = el.textContent;
  el.textContent = text;
  setTimeout(() => { el.textContent = old; }, 1500);
}

async function refreshMedia() {
  const list = $("#mediaList");
  try {
    const { files } = await api("/media");
    mediaFiles = files;
    const fs = curSite();
    const qs = fs ? `&site=${encodeURIComponent(fs)}` : "";
    list.innerHTML = files.length
      ? files.map((f) => {
          const isImg = /\.(jpe?g|png|webp|gif|avif)$/i.test(f);
          const isVid = /\.(mp4|mov|webm)$/i.test(f);
          const preview = isImg
            ? `<img src="/admin/api/file?name=${encodeURIComponent(f)}${qs}" alt="">`
            : isVid
              ? `<video src="/admin/api/file?name=${encodeURIComponent(f)}${qs}" muted preload="metadata"></video>`
              : "";
          return `<div class="media-item" data-name="${esc(f)}">
            <button class="media-del" data-del="${esc(f)}" title="delete file">✕</button>
            ${preview}<span class="media-name">${esc(f)}</span></div>`;
        }).join("")
      : '<span class="hint">empty — upload the first file</span>';

    list.querySelectorAll(".media-item").forEach((m) => {
      const name = m.dataset.name;
      m.addEventListener("click", async () => {
        try {
          await navigator.clipboard.writeText(name);
          flash(m.querySelector(".media-name"), "copied");
        } catch (_) {
          prompt("Copy path:", name);
        }
      });
      m.querySelector(".media-del").addEventListener("click", async (e) => {
        e.stopPropagation();
        if (!confirm(`Delete "${name}" from the site folder?`)) return;
        try {
          await api("/media?name=" + encodeURIComponent(name), { method: "DELETE" });
          refreshMedia();
        } catch (err) {
          alert("Delete failed:\n" + err.message);
        }
      });
    });
  } catch (err) {
    list.innerHTML = '<span class="hint">' + esc(err.message) + "</span>";
  }
  if (currentTab) {
    if (currentTab.kind === "gal") renderItems(currentTab.page);
    else if (currentTab.kind === "meta") renderMeta();
  }
}

async function uploadFiles(fileList) {
  const files = Array.from(fileList);
  if (!files.length) return;
  $("#uploadMsg").textContent = `uploading ${files.length} file(s)…`;
  try {
    for (const f of files) {
      await api("/upload?filename=" + encodeURIComponent(f.name), { method: "POST", body: f });
    }
    $("#uploadMsg").textContent = "done ✓";
    $("#fileInput").value = "";
    await refreshMedia();
    if (currentTab && currentTab.kind === "gal") renderItems(currentTab.page);
  } catch (err) {
    $("#uploadMsg").textContent = "✗ " + err.message;
  }
}

/* ---------- boot ---------- */

let dirtyListenerBound = false;
function bindDirtyListener() {
  if (dirtyListenerBound) return;
  ["input", "change"].forEach((evt) => {
    document.addEventListener(evt, (e) => {
      if (["INPUT", "TEXTAREA", "SELECT"].includes(e.target.tagName)) setDirty(true);
    });
  });
  dirtyListenerBound = true;
}

async function enter() {
  $("#login").classList.add("hidden");
  $("#app").classList.remove("hidden");
  data = await api("/data");
  setDirty(false);
  lastLine = 0;
  bindDirtyListener();
  await loadSites();
  const tabs = buildTabList();
  switchTo(tabs[0].key);
  refreshMedia();
}

async function savePassword() {
  const cur = $("#pwdCurrent").value;
  const n1 = $("#pwdNew").value;
  const n2 = $("#pwdNew2").value;
  const msg = $("#pwdMsg");
  msg.textContent = "";
  if (!cur || !n1) { msg.textContent = "fill in all fields"; return; }
  if (n1 !== n2) { msg.textContent = "new passwords don't match"; return; }
  if (n1.length < 8) { msg.textContent = "new password must be at least 8 characters"; return; }
  $("#btnSavePwd").disabled = true;
  try {
    await api("/password", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ current_password: cur, new_password: n1 }),
    });
    msg.textContent = "password updated";
    $("#pwdCurrent").value = $("#pwdNew").value = $("#pwdNew2").value = "";
    flash($("#btnSavePwd"), "updated");
  } catch (err) {
    msg.textContent = err.message;
  } finally {
    $("#btnSavePwd").disabled = false;
  }
}

function openPwd() {
  $("#pwdMsg").textContent = "";
  $("#pwdPanel").classList.remove("hidden");
  $("#pwdCurrent").focus();
}

function init() {
  api("/siteinfo")
    .then((info) => { if (info && info.name) $("#loginTitle").textContent = `${info.name} · admin`; })
    .catch(() => {});

  loadSites().then(() => {
    if (token) {
      api("/data").then(() => enter()).catch(() => logout());
    } else {
      $("#login").classList.remove("hidden");
    }
  });

  $("#loginForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    $("#loginError").textContent = "";
    try {
      const r = await api("/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: $("#loginUser").value, password: $("#loginPass").value }),
      });
      token = r.token;
      sessionStorage.setItem("slutadmin_token", token);
      await enter();
    } catch (err) {
      $("#loginError").textContent = err.message;
    }
  });

  $("#fileInput").addEventListener("change", () => uploadFiles($("#fileInput").files));
  const dz = $("#dropzone");
  dz.addEventListener("click", () => $("#fileInput").click());
  for (const ev of ["dragover", "dragleave", "drop"]) dz.addEventListener(ev, (e) => e.preventDefault());
  dz.addEventListener("dragover", () => dz.classList.add("drag"));
  dz.addEventListener("dragleave", () => dz.classList.remove("drag"));
  dz.addEventListener("drop", (e) => { dz.classList.remove("drag"); uploadFiles(e.dataTransfer.files); });

  $("#btnAddItem").addEventListener("click", addItem);
  $("#btnAddPage").addEventListener("click", addPage);
  $("#btnAddPara").addEventListener("click", () => { data.bio.push(""); setDirty(true); renderBio(); });
  const ig = $("#infoGlass");
  if (ig) ig.addEventListener("change", () => { data.site.info_glass = ig.checked; setDirty(true); });
  const ha = $("#headerAnim");
  if (ha) ha.addEventListener("change", () => { data.site.header_animation = ha.checked; setDirty(true); });

  $("#btnSave").addEventListener("click", saveData);
  $("#btnBuild").addEventListener("click", buildOnly);
  $("#btnPublish").addEventListener("click", startPublish);
  $("#btnPreview").addEventListener("click", openPreview);
  $("#btnLogout").addEventListener("click", logout);
  setupVisualEditor();
  $("#btnClosePublish").addEventListener("click", () => $("#publishPanel").classList.add("hidden"));
  $("#btnPwd").addEventListener("click", openPwd);
  $("#btnClosePwd").addEventListener("click", () => $("#pwdPanel").classList.add("hidden"));
  $("#btnSavePwd").addEventListener("click", savePassword);
  $("#btnCloseSite").addEventListener("click", () => $("#sitePanel").classList.add("hidden"));
  $("#btnCreateSite").addEventListener("click", createSite);
  $("#siteSlug").addEventListener("keydown", (e) => { if (e.key === "Enter") createSite(); });
  $("#btnExport").addEventListener("click", exportData);
  $("#btnImport").addEventListener("click", () => $("#importFile").click());
  $("#importFile").addEventListener("change", (e) => { importData(e.target.files[0]); e.target.value = ""; });
  $("#pwdCurrent").addEventListener("keydown", (e) => { if (e.key === "Enter") savePassword(); });
  $("#pwdNew").addEventListener("keydown", (e) => { if (e.key === "Enter") savePassword(); });
  $("#pwdNew2").addEventListener("keydown", (e) => { if (e.key === "Enter") savePassword(); });
}

document.addEventListener("DOMContentLoaded", init);

/* --- custom dropdown (replaces native <select>) --- */

function ddCloseAll() {
  document.querySelectorAll(".dd.open").forEach((dd) => dd.classList.remove("open"));
}

document.addEventListener("click", (e) => {
  const opt = e.target.closest(".dd-option");
  if (opt) {
    const dd = opt.closest(".dd");
    dd.querySelector(".dd-value").textContent = opt.textContent.trim();
    dd.dispatchEvent(new CustomEvent("ddchange", { detail: { value: opt.dataset.val } }));
    ddCloseAll();
    return;
  }
  const dd = e.target.closest(".dd");
  if (!dd) { ddCloseAll(); return; }
  const wasOpen = dd.classList.contains("open");
  ddCloseAll();
  if (!wasOpen && e.target.closest(".dd-trigger")) dd.classList.add("open");
});

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") { ddCloseAll(); return; }
  const open = document.querySelector(".dd.open");
  if (!open) return;
  const opts = [...open.querySelectorAll(".dd-option")];
  const cur = document.activeElement;
  const ci = opts.indexOf(cur);
  if (e.key === "ArrowDown") {
    e.preventDefault();
    if (ci > -1) opts[(ci + 1) % opts.length].focus();
    else opts[0].focus();
    opts.forEach((o) => o.classList.remove("hi"));
    (ci > -1 ? opts[(ci + 1) % opts.length] : opts[0]).classList.add("hi");
  } else if (e.key === "ArrowUp") {
    e.preventDefault();
    (ci > -1 ? opts[(ci - 1 + opts.length) % opts.length] : opts[opts.length - 1]).focus();
    opts.forEach((o) => o.classList.remove("hi"));
    (ci > -1 ? opts[(ci - 1 + opts.length) % opts.length] : opts[opts.length - 1]).classList.add("hi");
  } else if (e.key === "Enter" && ci > -1) {
    e.preventDefault();
    cur.click();
  }
});