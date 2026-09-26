#!/usr/bin/env python3
"""Slut Online site engine.

Builds the static index.html from data.json + template.html.

Usage:
    python3 build.py                          # legacy paths (data.json -> ../slutonline/)
    python3 build.py --data ... --out ...     # per-instance paths
    python3 build.py --diff                   # also diff against reference/index.html
"""
import argparse
import json
import pathlib
import re
import sys
import urllib.parse


def media_src(v):
    """Normalise any media path to a plain site-relative filename.

    Accepts bare names AND full admin-file URLs (e.g. local thumbnail copies
    like /admin/api/file?name=photo.jpg&site=x) — both become 'photo.jpg',
    which resolves correctly in preview and on the published site.
    """
    v = (v or "").strip()
    m = re.match(r"(?:https?://[^/]+)?/admin/api/file\?name=([^&]+)", v)
    if m:
        return urllib.parse.unquote(m.group(1))
    return v


def nl_to_br(v):
    """Keep user line breaks inside a text block (browsers collapse them otherwise)."""
    if not isinstance(v, str) or "\n" not in v:
        return v
    return v.replace("\r\n", "\n").replace("\n", "<br>")


AUDIO_CSS = """<style data-audio>
        .gallery-item.audio .music-cover{position:relative}
        .gallery-item.audio .play-btn{position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);width:52px;height:52px;border-radius:50%;border:0;background:rgba(0,0,0,.22);-webkit-backdrop-filter:blur(4px);backdrop-filter:blur(4px);color:#fff;font-size:20px;line-height:1;cursor:pointer;z-index:3;display:flex;align-items:center;justify-content:center;padding:0 0 0 2px;transition:background .2s ease,transform .2s ease}
        .gallery-item.audio .play-btn:hover{background:rgba(0,0,0,.38)}
        .gallery-item.audio .play-btn:active{transform:translate(-50%,-50%) scale(.94)}
        .gallery-item.audio.playing .play-btn{opacity:.88}
        .gallery-item.audio .audio-bar{height:3px;background:rgba(128,128,128,.25);margin:10px 1px 0;overflow:hidden;border-radius:2px;cursor:pointer;position:relative}
        .gallery-item.audio .audio-bar:hover{background:rgba(128,128,128,.4)}
        .gallery-item.audio .audio-bar::after{content:"";position:absolute;left:-4px;right:-4px;top:-1.5px;bottom:-1.5px}
        .gallery-item.audio .audio-bar i{display:block;height:100%;width:0;background:var(--text);transition:width .2s linear;pointer-events:none}
        </style>"""


def any_audio(d):
    for p in d.get("pages", []):
        if p.get("type") != "gallery":
            continue
        for it in d.get(p.get("id"), []):
            if (it.get("audio") or "").strip():
                return True
    return False


GLASS_CSS = """<style data-glass>
        .info-content{background:rgba(255,255,255,.10);-webkit-backdrop-filter:blur(20px) saturate(1.6);backdrop-filter:blur(20px) saturate(1.6);border:1px solid rgba(255,255,255,.16);border-radius:14px;padding:26px 30px;box-shadow:0 8px 32px rgba(0,0,0,.18)}
        .info-section.page-fade,.info-section.page-fade.visible,.info-section.page-fade.hidden{opacity:1!important;transform:none!important;transition:none!important}
        .info-section.visible > .info-content{animation:infoGlassIn .6s cubic-bezier(.22,.61,.36,1) both}
        @keyframes infoGlassIn{0%{opacity:0;transform:translateY(18px) scale(.98)}100%{opacity:1;transform:none}}
        @media (prefers-reduced-motion: reduce){.info-section.visible > .info-content{animation:none}}
        </style>"""


def any_news(d):
    for p in d.get("pages", []):
        if p.get("type") != "gallery":
            continue
        for it in d.get(p.get("id"), []):
            if it.get("kind") == "news":
                return True
    return False


def any_block_glass(d):
    for p in d.get("pages", []):
        if p.get("type") != "gallery":
            continue
        for it in d.get(p.get("id"), []):
            if it.get("glass"):
                return True
    return False


BLOCK_GLASS_CSS = """<style data-block-glass>
.gallery-item.glass{background:rgba(255,255,255,.10);-webkit-backdrop-filter:blur(20px) saturate(1.6);backdrop-filter:blur(20px) saturate(1.6);border:1px solid rgba(255,255,255,.16);border-radius:14px;padding:14px;box-shadow:0 8px 32px rgba(0,0,0,.18);transition:none!important}
.gallery-item.glass.visible{animation:blockGlassIn .7s cubic-bezier(.22,.61,.36,1) both}
@keyframes blockGlassIn{0%{opacity:0;transform:translateY(30px) scale(.985)}100%{opacity:1;transform:none}}
@media (max-width:768px){.gallery-item.glass{padding:10px}}
@media (prefers-reduced-motion: reduce){.gallery-item.glass.visible{animation:none}}
</style>"""


NEWS_CSS = """<style data-news>
.gallery-item.news .news-card{position:relative;display:block;width:100%;overflow:hidden}
.gallery-item.news .news-card::before{content:"";display:block;padding-top:100%}
.gallery-item.news .news-cover{position:absolute;top:0;left:0;width:100%;height:100%;object-fit:cover;display:block;transition:transform .6s ease}
.gallery-item.news .news-card:hover .news-cover{transform:scale(1.03)}
.gallery-item.news .news-title{position:absolute;left:0;right:0;bottom:0;z-index:2;display:flex;align-items:flex-end;padding:20px 24px;font-size:18px;font-weight:400;line-height:1.3;letter-spacing:.5px;color:#fff;background:linear-gradient(to top,rgba(0,0,0,.55),rgba(0,0,0,0))}
.news-modal{position:fixed;inset:0;z-index:2000;display:flex;align-items:center;justify-content:center;padding:20px;background:rgba(10,10,12,.5);-webkit-backdrop-filter:blur(16px) saturate(1.5);backdrop-filter:blur(16px) saturate(1.5);opacity:0;animation:newsIn .3s ease forwards}
.news-panel{position:relative;width:min(720px,100%);max-height:90vh;overflow:auto;background:rgba(255,255,255,.12);-webkit-backdrop-filter:blur(24px) saturate(1.6);backdrop-filter:blur(24px) saturate(1.6);border:1px solid rgba(255,255,255,.18);border-radius:16px;box-shadow:0 16px 48px rgba(0,0,0,.45);-webkit-overflow-scrolling:touch;opacity:0;animation:newsPanelIn .5s cubic-bezier(.34,1.32,.64,1) forwards .06s}
@keyframes newsIn{from{opacity:0}to{opacity:1}}
@keyframes newsPanelIn{0%{opacity:0;transform:translateY(22px) scale(.96)}100%{opacity:1;transform:none}}
.news-modal.closing{animation:newsOut .28s ease forwards}
.news-modal.closing .news-panel{animation:newsPanelOut .28s ease forwards}
@keyframes newsOut{from{opacity:1}to{opacity:0}}
@keyframes newsPanelOut{from{opacity:1;transform:none}to{opacity:0;transform:translateY(10px) scale(.98)}}
@media (prefers-reduced-motion: reduce){.news-modal,.news-panel{animation:none;opacity:1;transform:none}.news-modal.closing{animation:none}}
.news-close{position:absolute;top:10px;right:10px;z-index:3;width:34px;height:34px;border:0;border-radius:50%;background:rgba(0,0,0,.35);color:#fff;font-size:20px;line-height:1;cursor:pointer;display:flex;align-items:center;justify-content:center;-webkit-backdrop-filter:blur(6px);backdrop-filter:blur(6px)}
.news-close:hover{background:rgba(0,0,0,.5)}
.news-strip{display:flex;overflow-x:auto;scroll-snap-type:x mandatory;-webkit-overflow-scrolling:touch}
.news-strip img{flex:0 0 100%;width:100%;scroll-snap-align:center;display:block}
.news-text{padding:22px 26px 26px}
.news-full-title{margin:0 0 12px;font-size:22px;font-weight:500;line-height:1.25;letter-spacing:.4px}
.news-body{line-height:1.65;font-size:15px;margin:0 0 16px}
.news-read{font-weight:700;text-decoration:none;color:inherit;border-bottom:1px solid currentColor}
.news-read:hover{opacity:.7}
@media (max-width:768px){.gallery-item.news .news-title{font-size:16px;padding:16px}.news-text{padding:18px 18px 22px}.news-full-title{font-size:19px}.news-modal{align-items:flex-start;padding:0;background:rgba(10,10,12,.65)}.news-panel{width:100%;max-height:100dvh;border-radius:0;border:0}}
</style>"""


NEWS_JS = """<script data-news>
(function () {
    function close(m) {
        m.classList.add("closing");
        m.addEventListener("animationend", function () { m.remove(); document.body.style.overflow = ""; }, { once: true });
    }
    document.addEventListener("click", function (e) {
        var card = e.target.closest(".gallery-item.news .news-card");
        if (!card) return;
        e.preventDefault();
        var full = card.parentNode.querySelector(".news-full");
        if (!full) return;
        var modal = document.createElement("div");
        modal.className = "news-modal";
        var panel = document.createElement("div");
        panel.className = "news-panel";
        panel.innerHTML = '<button class="news-close" type="button" aria-label="Close">\u00d7</button>' + full.innerHTML;
        modal.appendChild(panel);
        modal.addEventListener("click", function (ev) { if (ev.target === modal) close(modal); });
        panel.querySelector(".news-close").addEventListener("click", function () { close(modal); });
        document.body.appendChild(modal);
        document.body.style.overflow = "hidden";
    });
    document.addEventListener("keydown", function (e) {
        if (e.key !== "Escape") return;
        var m = document.querySelector(".news-modal:not(.closing)");
        if (m) close(m);
    });
})();
</script>"""


EDIT_CSS = """<style data-edit>
.ce-badge{position:fixed;left:50%;bottom:14px;transform:translateX(-50%);z-index:9000;background:rgba(10,10,12,.82);-webkit-backdrop-filter:blur(8px);backdrop-filter:blur(8px);color:#fff;padding:8px 14px;border-radius:999px;font:500 12px/1.4 system-ui,sans-serif;letter-spacing:.3px;pointer-events:none;box-shadow:0 6px 24px rgba(0,0,0,.4)}
[data-edit]{cursor:pointer;position:relative}
[data-edit]:hover{outline:2px dashed rgba(255,120,160,.85);outline-offset:2px}
[data-edit]:hover::after{content:attr(data-edit);position:absolute;right:4px;bottom:4px;z-index:5;background:rgba(255,95,140,.92);color:#fff;font:600 10px/1.4 system-ui,sans-serif;padding:2px 7px;border-radius:5px;letter-spacing:.3px;pointer-events:none;text-transform:none}
[data-edit].ce-hit{outline:2px solid #ff5078!important;outline-offset:2px}
[data-edit].ce-editing{outline:2px solid #ff5078!important;outline-offset:2px;border-radius:2px}
.ce-bar{position:fixed;z-index:9600;display:flex;gap:6px;align-items:center;background:#16161c;border:1px solid rgba(255,80,120,.45);border-radius:10px;padding:5px 8px;box-shadow:0 10px 30px rgba(0,0,0,.5);font:600 12px system-ui,sans-serif}
.ce-bar button{border:0;border-radius:7px;padding:5px 12px;font:600 12px system-ui,sans-serif;cursor:pointer}
.ce-bar .ce-save{background:#ff5078;color:#fff}
.ce-bar .ce-save:disabled{opacity:.55;cursor:default}
.ce-bar .ce-cancel{background:#26262e;color:#bbb}
.ce-bar .ce-hint{color:#888;font:11px system-ui;margin-left:6px;white-space:nowrap}
</style>"""


NAV_ANIM_CSS_OUT = """<style data-nav-anim>
.nav-anim-out{position:fixed;top:64px;left:0;right:0;z-index:999;text-align:center;font-family:'Inter','Helvetica Neue',Helvetica,Arial,sans-serif;font-size:clamp(26px,5vw,40px);font-weight:700;letter-spacing:1.5px;text-transform:uppercase;color:var(--text);opacity:0;transform:translateY(-12px);pointer-events:none;padding:0 20px;transition:opacity .45s ease,transform .45s ease}
.nav-anim-out.show{opacity:.92;transform:translateY(0)}
@media (prefers-reduced-motion: reduce){.nav-anim-out{transition:none}}
</style>"""


NAV_ANIM_ALIGN_CSS = """<style data-nav-anim-align>
.info-section,
.gallery { padding-top: 110px !important; }
@media (max-width: 768px) {
    .info-section,
    .gallery { padding-top: 80px !important; }
}
</style>"""


NAV_ANIM_GLASS_CSS = """<style data-nav-anim-glass>
.nav-anim-out.glass{left:50%;right:auto;width:max-content;max-width:92vw;background:rgba(255,255,255,.10);-webkit-backdrop-filter:blur(20px) saturate(1.6);backdrop-filter:blur(20px) saturate(1.6);border:0.5px solid rgba(255,255,255,.16);border-radius:14px;padding:4px 12px;box-shadow:0 8px 32px rgba(0,0,0,.18);text-align:center;line-height:1.2;transform:translateX(-50%) translateY(-8px)}
.nav-anim-out.glass.show{transform:translateX(-50%) translateY(0)}
</style>"""


NAV_ANIM_JS_OUT = """<script data-nav-anim>
(function () {
    var glass = document.currentScript ? document.currentScript.getAttribute("data-glass") === "1" : false;
    function animateNavTitle(label) {
        var el = document.getElementById("navAnimOut");
        if (!el) {
            el = document.createElement("div");
            el.id = "navAnimOut";
            el.className = "nav-anim-out" + (glass ? " glass" : "");
            document.body.appendChild(el);
        }
        el.textContent = label;
        requestAnimationFrame(function () { el.classList.add("show"); });
        setTimeout(function () {
            el.classList.remove("show");
        }, 1800);
    }
    function bind() {
        var links = document.querySelectorAll(".menu-items a[data-filter], .menu-items a[href=\\"#info\\"]");
        Array.prototype.forEach.call(links, function (a) {
            a.addEventListener("click", function () {
                animateNavTitle(a.textContent.trim());
            });
        });
    }
    if (document.body) bind(); else document.addEventListener("DOMContentLoaded", bind);
})();
</script>"""


NAV_ANIM_JS = """<script data-nav-anim>
(function () {
    function animateNavTitle(label) {
        var el = document.getElementById("siteTitle");
        if (!el) return;
        el.classList.add("lift");
        var sub = el.querySelector(".logo-sub");
        if (!sub) {
            sub = document.createElement("div");
            sub.className = "logo-sub";
            el.appendChild(sub);
        }
        sub.textContent = label;
        requestAnimationFrame(function () { sub.classList.add("show"); });
        setTimeout(function () {
            el.classList.remove("lift");
            sub.classList.remove("show");
            setTimeout(function () { if (sub && sub.parentNode) sub.parentNode.removeChild(sub); }, 400);
        }, 1800);
    }
    function bind() {
        var links = document.querySelectorAll(".menu-items a[data-filter], .menu-items a[href=\\"#info\\"]");
        Array.prototype.forEach.call(links, function (a) {
            a.addEventListener("click", function () {
                animateNavTitle(a.textContent.trim());
            });
        });
    }
    if (document.body) bind(); else document.addEventListener("DOMContentLoaded", bind);
})();
</script>"""


EDIT_JS = """<script data-edit>
(function () {
    if (!window.opener) return;
    function badge() {
        var b = document.createElement("div");
        b.className = "ce-badge";
        b.textContent = "Visual editor \\u2014 click a text to edit it in place; Cmd/Ctrl+S save, Esc cancel";
        (document.body || document.documentElement).appendChild(b);
    }
    if (document.body) badge(); else document.addEventListener("DOMContentLoaded", badge);
    window.addEventListener("message", function (e) {
        if (!e.data) return;
        if (e.data.type === "slut-site-edit-reload") {
            cleanup();
            location.reload();
        } else if (e.data.type === "slut-site-edit-error") {
            cleanup();
            alert("Save failed: " + (e.data.message || "unknown error"));
        }
    });
    var elf = null;
    var bar = null;
    var rawSnapshot = "";
    function htmlToRaw(html) {
        var s = html.replace(/<br\\s*\\/?>/gi, "\\n");
        s = s.replace(/<\\/(p|div)>/gi, "\\n");
        s = s.replace(/<(?!\\/?(?:strong|em|a|u|b|i|span)\\b)[^>]*>/gi, "");
        s = s.replace(/\\n{2,}/g, "\\n");
        s = s.replace(/&(#x[0-9a-f]+|#\\d+|amp|lt|gt|quot|apos|nbsp);/gi, function (m, ent) {
            var t = { amp: "&", lt: "<", gt: ">", quot: '"', apos: "'", nbsp: " " };
            if (t[ent.toLowerCase()]) return t[ent.toLowerCase()];
            var n = ent.toLowerCase()[0] === "x" ? parseInt(ent.slice(1), 16) : parseInt(ent.slice(1), 10);
            try { return String.fromCodePoint(n); } catch (_) { return m; }
        });
        return s.trim();
    }
    function save() {
        if (!elf) return;
        var value = htmlToRaw(elf.innerHTML);
        var path = elf.getAttribute("data-ce-path");
        cleanup();
        try { window.opener.postMessage({ type: "slut-site-edit-save", path: path, value: value }, "*"); } catch (_) {}
    }
    function cancel() {
        if (!elf) return;
        elf.innerHTML = rawSnapshot;
        cleanup();
    }
    function cleanup() {
        if (!elf) return;
        elf.contentEditable = "false";
        elf.classList.remove("ce-editing");
        elf.removeAttribute("data-ce-path");
        if (bar) { bar.remove(); bar = null; }
        elf = null;
    }
    function openEdit(field, path) {
        if (elf === field) return;
        cleanup();
        var rect = field.getBoundingClientRect();
        field.contentEditable = "true";
        field.classList.add("ce-editing");
        field.setAttribute("data-ce-path", path);
        rawSnapshot = field.innerHTML;
        bar = document.createElement("div");
        bar.className = "ce-bar";
        var saveBtn = document.createElement("button");
        saveBtn.className = "ce-save";
        saveBtn.textContent = "Save";
        saveBtn.type = "button";
        saveBtn.addEventListener("mousedown", function (e) { e.preventDefault(); });
        saveBtn.addEventListener("click", save);
        var cancelBtn = document.createElement("button");
        cancelBtn.className = "ce-cancel";
        cancelBtn.textContent = "Cancel";
        cancelBtn.type = "button";
        cancelBtn.addEventListener("mousedown", function (e) { e.preventDefault(); });
        cancelBtn.addEventListener("click", cancel);
        var hint = document.createElement("span");
        hint.className = "ce-hint";
        hint.textContent = "Cmd/Ctrl+S \\u00b7 Esc";
        bar.appendChild(saveBtn);
        bar.appendChild(cancelBtn);
        bar.appendChild(hint);
        document.body.appendChild(bar);
        var ph = 6, barW = bar.offsetWidth || 150;
        var left = Math.max(ph, Math.min(rect.left, window.innerWidth - barW - ph));
        var top = rect.top - bar.offsetHeight - 6;
        if (top < ph) top = rect.bottom + 6;
        bar.style.left = left + "px";
        bar.style.top = top + "px";
        elf = field;
        var range = document.createRange();
        range.selectNodeContents(field);
        range.collapse(false);
        var sel = window.getSelection();
        sel.removeAllRanges();
        sel.addRange(range);
        field.focus({ preventScroll: true });
    }
    function hit(el) {
        el.classList.remove("ce-hit");
        void el.offsetWidth;
        el.classList.add("ce-hit");
        setTimeout(function () { el.classList.remove("ce-hit"); }, 800);
    }
    function isEditable(fieldName) {
        return ["span", "caption", "text", "body", "credit"].indexOf(fieldName) !== -1;
    }
    document.addEventListener("keydown", function (e) {
        if (!elf) return;
        if ((e.metaKey || e.ctrlKey) && (e.key === "s" || e.key === "S")) {
            e.preventDefault();
            e.stopPropagation();
            save();
        } else if (e.key === "Escape") {
            e.preventDefault();
            e.stopPropagation();
            cancel();
        }
    }, true);
    document.addEventListener("click", function (e) {
        var t = e.target;
        if (bar && bar.contains(t)) return;
        var field = t && t.closest ? t.closest("[data-edit-field]") : null;
        var host = t && t.closest ? t.closest("[data-edit]") : null;
        if (elf) {
            var inside = elf && (elf === t || elf.contains(t));
            if (inside) { e.stopPropagation(); return; }
            save();
            return;
        }
        if (!host) return;
        e.preventDefault();
        e.stopPropagation();
        var path = host.getAttribute("data-edit") +
            (field && !field.contains(host) ? "/" + field.getAttribute("data-edit-field") : "");
        var bio = /^bio\\/(\\d+)$/.exec(host.getAttribute("data-edit"));
        var fieldName = field && field.getAttribute("data-edit-field") || "";
        var editable = isEditable(fieldName) || !!bio;
        if (editable) {
            hit(field || host);
            openEdit(field || host, path);
        } else {
            hit(host);
            try { window.opener.postMessage({ type: "slut-site-edit", path: path }, "*"); } catch (_) {}
        }
    }, true);
})();
</script>"""


def convert_favicon(src, out_dir):
    """Downscale any raster to a 32x32 favicon set (png + ico)."""
    try:
        from PIL import Image
        im = Image.open(src).convert("RGBA")
    except Exception:
        return False
    if max(im.size) > 32:
        im.thumbnail((32, 32), Image.LANCZOS)
    canvas = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
    canvas.paste(im, ((32 - im.width) // 2, (32 - im.height) // 2), im)
    try:
        canvas.save(out_dir / "favicon.png", "PNG")
        canvas.save(out_dir / "favicon.ico", format="ICO", sizes=[(16, 16), (32, 32)])
    except Exception:
        return False
    return True


def favicon_links(favicon, out_dir):
    """Choose how to reference a favicon. Converts when format/size is awkward.

    Rules:
      - svg is kept as-is (browsers render it, no rasterisation needed)
      - png/ico up to 256px is linked as-is (legacy behaviour untouched)
      - anything else (wrong format or too big) is auto-converted to a 32x32
        favicon.png + favicon.ico saved next to the site index
      - unreadable/missing/remote values fall back to linking as-is
    """
    low = favicon.lower()
    ftype = ' type="image/svg+xml"' if low.endswith(".svg") else ""
    remote = ("://" in favicon) or favicon.startswith(("data:", "//"))
    slashed = "/" in favicon
    if remote or slashed or out_dir is None:
        return [f'    <link rel="icon" href="{favicon}"{ftype}>']
    src = out_dir / favicon
    if not src.is_file():
        return [f'    <link rel="icon" href="{favicon}"{ftype}>']
    if low.endswith(".svg"):
        return [f'    <link rel="icon" href="{favicon}"{ftype}>']
    size = None
    try:
        from PIL import Image
        with Image.open(src) as im:
            size = im.size
    except Exception:
        size = None
    if size and low.endswith((".png", ".ico")) and max(size) <= 256:
        return [f'    <link rel="icon" href="{favicon}"{ftype}>']
    if size and convert_favicon(src, out_dir):
        return ['    <link rel="icon" href="favicon.ico" sizes="any">',
                '    <link rel="icon" href="favicon.png" type="image/png">']
    return [f'    <link rel="icon" href="{favicon}"{ftype}>']

ROOT = pathlib.Path(__file__).parent
SITE = ROOT.parent / "slutonline"
DATA = ROOT / "data.json"
TEMPLATE = ROOT / "template.html"
OUT = SITE / "index.html"
REFERENCE = ROOT / "reference" / "index.html"

IND = "    "  # 4 spaces


def render_head_meta(d):
    s = d["site"]
    seo = d["seo"]
    social = d["social"]
    domain = s["domain"].rstrip("/")
    hero = media_src(s["hero"])
    title = s["title"]

    ld = {
        "@context": "https://schema.org",
        "@type": "Person",
        "name": s["name"],
        "url": domain,
        "image": f"{domain}/{hero}",
        "sameAs": [
            social["instagram_url"],
            social["bandcamp_url"],
            social["behance_url"],
        ],
        "jobTitle": seo["job_title"],
        "description": seo["ld_description"],
        "knowsAbout": seo["knows_about"],
    }
    ld_json = json.dumps(ld, ensure_ascii=False, indent=4)
    ld_lines = "\n".join("    " + line for line in ld_json.splitlines())

    lines = [
        f'    <meta charset="UTF-8">',
        f'    <meta name="viewport" content="width=device-width, initial-scale=1.0">',
        f"    <title>{title}</title>",
        f'    <link rel="canonical" href="{domain}">',
        f'    <meta name="description" content="{seo["meta_description"]}">',
        f'    <meta name="keywords" content="{seo["keywords"]}">',
        f'    <meta name="robots" content="index, follow, max-image-preview:large, max-snippet:-1, max-video-preview:-1">',
        f'    <meta name="author" content="{s["name"]}">',
        f'    <meta property="og:site_name" content="{s["name"]}">',
        f'    <meta property="og:locale" content="{s["locale"]}">',
        f'    <meta property="og:title" content="{title}">',
        f'    <meta property="og:description" content="{seo["og_description"]}">',
        f'    <meta property="og:type" content="website">',
        f'    <meta property="og:url" content="{domain}">',
        f'    <meta property="og:image" content="{domain}/{hero}">',
        f'    <meta property="og:image:width" content="{s["og_image_width"]}">',
        f'    <meta property="og:image:height" content="{s["og_image_height"]}">',
        f'    <meta name="twitter:card" content="summary_large_image">',
        f'    <meta name="twitter:title" content="{title}">',
        f'    <meta name="twitter:description" content="{seo["twitter_description"]}">',
        f'    <meta name="twitter:image" content="{domain}/{hero}">',
        f'    <script type="application/ld+json">',
        ld_lines,
        f"    </script>",
    ]
    return "\n".join(lines)


def render_head_extra(d, out_dir=None, edit=False):
    lines = []
    favicon = media_src(d["site"].get("favicon"))
    if favicon:
        lines.extend(favicon_links(favicon, out_dir))
    else:
        lines.append('    <link rel="icon" href="favicon.ico" sizes="any">')
        lines.append('    <link rel="icon" href="icon.svg" type="image/svg+xml">')
    snippet = (d["seo"].get("analytics_snippet") or "").strip()
    if snippet:
        for raw in snippet.splitlines():
            line = raw.rstrip()
            if line:
                lines.append(f"    {line}")
    theme = render_theme(d["site"].get("theme"))
    if theme:
        lines.append(theme)
    if any_audio(d):
        lines.append("    " + AUDIO_CSS)
    if d["site"].get("info_glass"):
        lines.append("    " + GLASS_CSS)
    if any_block_glass(d):
        lines.append("    " + BLOCK_GLASS_CSS)
    anim_style = d["site"].get("header_animation_style", "inside")
    if d["site"].get("header_animation"):
        lines.append("    " + NAV_ANIM_ALIGN_CSS)
        acolor = (d["site"].get("header_animation_color") or "").strip()
        if anim_style == "outside":
            lines.append("    " + NAV_ANIM_CSS_OUT)
            lines.append("    " + NAV_ANIM_JS_OUT.replace(
                '<script data-nav-anim>',
                '<script data-nav-anim data-glass="1">' if d["site"].get("header_animation_glass") else '<script data-nav-anim>'))
            if d["site"].get("header_animation_glass"):
                lines.append("    " + NAV_ANIM_GLASS_CSS)
            if acolor:
                lines.append(f'    <style data-nav-anim-color>.nav-anim-out{{color:{acolor}!important}}</style>')
            if d["site"].get("header_animation_outline"):
                ocor = (d["site"].get("header_animation_outline_color") or "").strip()
                if ocor:
                    lines.append(f'    <style data-nav-anim-outline>.nav-anim-out{{-webkit-text-stroke:4px {ocor};paint-order:stroke fill}}</style>')
        else:
            lines.append("    " + NAV_ANIM_JS)
            if acolor:
                lines.append(f'    <style data-nav-anim-color>.logo-sub{{color:{acolor}!important}}</style>')
    if any_news(d):
        lines.append("    " + NEWS_CSS)
        lines.append("    " + NEWS_JS)
    if edit:
        lines.append("    " + EDIT_CSS)
        lines.append("    " + EDIT_JS)
    return "\n".join(lines).rstrip("\n") or ""


def render_theme(theme):
    """Per-site look: page/text color + optional full-page background image."""
    if not isinstance(theme, dict):
        return ""
    bg = (theme.get("background_color") or "").strip()
    txt = (theme.get("text_color") or "").strip()
    htx = (theme.get("header_text_color") or "").strip()
    img = media_src(theme.get("background_image"))
    if not bg and not txt and not htx and not img:
        return ""
    rules = []
    vs = []
    if bg:
        vs.append(f"--bg:{bg}")
        rules.append(f"body{{background-color:{bg}!important}}")
    if txt:
        vs.append(f"--text:{txt}")
        rules.append(f"body{{color:{txt}!important}}")
        rules.append(f".info-content p{{color:{txt}!important}}")
    if htx:
        rules.append(
            f"header .logo,header .logo-sub{{color:{htx}!important}}"
            f".menu-toggle span{{background:{htx}!important}}")
    if img:
        rules.append(f"body{{background-image:url('{img}')!important;"
                     f"background-size:cover!important;background-position:center!important;"
                     f"background-attachment:fixed!important}}")
    style = "<style data-theme>"
    if vs:
        style += ":root{" + ";".join(vs) + "}"
    style += "".join(rules) + "</style>"
    return "    " + style


def _luminance(color):
    h = color.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) != 6:
        raise ValueError(color)
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def span_style(color):
    """Inline style for an image overlay label. Empty -> current default."""
    if not color:
        return ""
    try:
        shadow = ("rgba(0,0,0,0.65)" if _luminance(color) > 0.45
                  else "rgba(255,255,255,0.55)")
    except ValueError:
        return ""
    return f' style="color:{color};text-shadow:0 2px 10px {shadow}"'


def color_style(color):
    if not color:
        return ""
    return f' style="color:{color}"'


def render_credit(credit, color="", edit_field=""):
    if not credit:
        return ""
    edit_attr = f' data-edit-field="{edit_field}"' if edit_field else ""
    return (f'        <div class="gallery-credit"{color_style(color)}'
            f'{edit_attr}>{nl_to_br(credit)}</div>')


def render_music(item, category="music", edit=""):
    ep = f' data-edit="{edit}"' if edit else ""
    ef = lambda key: f' data-edit-field="{key}"' if edit else ""
    gcls = " glass" if item.get("glass") else ""
    credit = render_credit(item["credit"], item.get("credit_color", ""),
                           edit_field="credit" if edit else "")
    credit_block = ("\n" + credit) if credit else ""
    url = (item.get("url") or "").strip()
    audio = (item.get("audio") or "").strip()
    span = nl_to_br(item["span"])
    ss = span_style(item.get("span_color", ""))
    img = media_src(item["img"])
    alt = item.get("alt", "")
    if audio:
        if url:
            leader = f'        <a href="{url}" target="_blank" rel="noopener" class="music-link"{ef("url")}>'
            closer = "        </a>"
        else:
            leader = '        <div class="music-link">'
            closer = "        </div>"
        cover = (
            leader + "\n"
            f'            <img src="{img}" alt="{alt}"{ef("img")}>\n'
            f'            <span{ss}{ef("span")}>{span}</span>\n'
            + closer
        )
        overlay = (
            '\n        <button type="button" class="play-btn" aria-label="play/pause" '
            "onclick=\"event.preventDefault();event.stopPropagation();"
            "var a=this.closest('.gallery-item').querySelector('audio');"
            "if(a.paused){a.play().catch(function(){});}else{a.pause();}\">"
            '<span class="play-ic">▶</span></button>'
        )
        tail = (
            '\n        <div class="audio-bar" role="slider" aria-label="seek" '
            "onclick=\"var p=this.closest('.gallery-item'),a=p.querySelector('audio');"
            "if(a&&a.duration){var r=this.getBoundingClientRect();"
            "a.currentTime=(event.clientX-r.left)/r.width*a.duration;}\"><i></i></div>\n"
            '        <audio preload="metadata" src="' + media_src(audio) + '" style="display:none" '
            "onplay=\"var p=this.closest('.gallery-item');p.querySelector('.play-ic').textContent='❚❚';p.classList.add('playing')\" "
            "onpause=\"var p=this.closest('.gallery-item');p.querySelector('.play-ic').textContent='▶';p.classList.remove('playing')\" "
            "onended=\"var p=this.closest('.gallery-item');p.querySelector('.play-ic').textContent='▶';p.classList.remove('playing');p.querySelector('.audio-bar i').style.width='0'\" "
            "ontimeupdate=\"var p=this.closest('.gallery-item'),b=p.querySelector('.audio-bar i');b.style.width=(this.duration?this.currentTime/this.duration*100:0)+'%'\"></audio>"
        )
        return (
            f'    <div class="gallery-item audio{gcls}" data-category="{category}"{ep}>\n'
            '        <div class="music-cover">\n'
            + cover + overlay + "\n"
            + "        </div>" + tail + credit_block + "\n"
            + "    </div>"
        )
    head = []
    if url:
        head.append(f'        <a href="{url}" target="_blank" class="music-link"{ef("url")}>')
    else:
        head.append('        <div class="music-link" data-no-link>')
    head.append(f'            <img src="{img}" alt="{alt}"{ef("img")}>')
    head.append(f'            <span{ss}{ef("span")}>{span}</span>')
    head.append("        </a>" if url else "        </div>")
    return (
        f'    <div class="gallery-item{gcls}" data-category="{category}"{ep}>\n'
        + "\n".join(head) + credit_block + "\n"
        + "    </div>"
    )


def render_watch(item, category="watch", edit=""):
    ep = f' data-edit="{edit}"' if edit else ""
    ef = lambda key: f' data-edit-field="{key}"' if edit else ""
    variant = item.get("variant", "classic")
    poster = media_src(item.get("poster", ""))
    caption = item.get("caption", "")
    src = media_src(item["src"])
    credit = render_credit(item.get("credit", ""), item.get("credit_color", ""),
                           edit_field="credit" if edit else "")
    credit_block = ("\n" + credit) if credit else ""

    if variant == "center":
        video = (
            f'            <video controls preload="metadata" playsinline poster="{poster}" '
            f'style="position:absolute;top:0;left:0;width:100%;height:100%;object-fit:contain;background:#000;">\n'
            f'                <source src="{src}" type="video/mp4">\n'
            f"            </video>"
        )
        container = f'        <div class="video-frame"{ef("src")}>\n{video}\n        </div>'
    else:
        container_cls = "video-container"
        if variant == "portrait":
            container_cls = "video-container--portrait"
        video = (
            f"            <video\n"
            f'                class="local-video"\n'
            f'                src="{src}"\n'
            f'                poster="{poster}"\n'
            f"                controls\n"
            f"                preload=\"metadata\"\n"
            f"                playsinline>\n"
            f"            </video>"
        )
        container = f'        <div class="{container_cls}"{ef("src")}>\n{video}\n        </div>'

    if variant == "tall":
        container = (
            f'        <div style="position:relative;overflow:hidden;margin-bottom:16px;width:100%;padding-top:177.78%;"{ef("src")}>\n'
            f"{video}\n"
            f"        </div>"
        )

    caption_block = (
        f'        <div class="gallery-caption"{span_style(item.get("span_color", ""))}{ef("caption")}>\n'
        f'            {nl_to_br(caption)}\n'
        f"        </div>"
    )

    return (
        f'    <div class="gallery-item" data-category="{category}"{ep}>\n'
        f"{container}\n"
        f"{caption_block}{credit_block}\n"
        f"    </div>"
    )


def render_press(item, category="press", edit=""):
    ep = f' data-edit="{edit}"' if edit else ""
    ef = lambda key: f' data-edit-field="{key}"' if edit else ""
    credit = render_credit(item["credit"], item.get("credit_color", ""),
                           edit_field="credit" if edit else "")
    credit_block = ("\n" + credit) if credit else ""
    return (
        f'    <div class="gallery-item" data-category="{category}"{ep}>\n'
        f'        <a href="{item["url"]}" target="_blank" class="music-link press-link-square"{ef("url")}>\n'
        f'            <img src="{media_src(item["img"])}" alt=""{ef("img")}>\n'
        f'            <span{span_style(item.get("span_color", ""))}{ef("text")}>{nl_to_br(item["text"])}</span>\n'
        f"        </a>{credit_block}\n"
        f"    </div>"
    )


def render_news(item, category="news", site_name="", edit=""):
    ep = f' data-edit="{edit}"' if edit else ""
    ef = lambda key: f' data-edit-field="{key}"' if edit else ""
    gcls = " glass" if item.get("glass") else ""
    img = media_src(item.get("img", ""))
    span = nl_to_br(item.get("span", ""))
    body = item.get("body", "")
    extras = [media_src(x) for x in (item.get("images") or []) if str(x).strip()]
    slides = extras or [img]
    link = (item.get("link") or "").strip()
    label = (item.get("link_label") or "").strip() or (
        f"Read full: {site_name}" if site_name else "Read full")
    ss = span_style(item.get("span_color", ""))
    ts = color_style(item.get("text_color", ""))
    slides_html = "\n".join(
        f'                <img src="{s}" alt="" loading="lazy">' for s in slides if s)
    read = (f'\n                <a class="news-read" href="{link}" target="_blank" '
            f'rel="noopener"{ef("link")}>{label}</a>') if link else ""
    credit = render_credit(item.get("credit", ""), item.get("credit_color", ""),
                           edit_field="credit" if edit else "")
    credit_block = ("\n" + credit) if credit else ""
    full = (
        f'            <div class="news-strip">\n{slides_html}\n            </div>\n'
        f'            <div class="news-text"{ts}>\n'
        f'                <h2 class="news-full-title"{ss}>{span}</h2>\n'
        f'                <div class="news-body"{ef("body")}>{nl_to_br(body)}</div>{read}\n'
        f'            </div>'
    )
    return (
        f'    <div class="gallery-item news{gcls}" data-category="{category}"{ep}>\n'
        f'        <a class="news-card" href="#" role="button" aria-haspopup="dialog">\n'
        f'            <img class="news-cover" src="{img}" alt=""{ef("img")}>\n'
        f'            <span class="news-title"{ss}{ef("span")}>{span}</span>\n'
        f'        </a>\n'
        f'        <div class="news-full" hidden>\n{full}\n        </div>{credit_block}\n'
        f'    </div>'
    )


def initial_page_id(d):
    """Id of the gallery page shown on load: first non-empty, else first."""
    galleries = [p for p in d.get("pages", [])
                 if p.get("type") == "gallery" and p.get("show_in_menu", True)]
    active = next((p["id"] for p in galleries if d.get(p["id"])), None)
    if active is None and galleries:
        active = galleries[0]["id"]
    return active


def render_menu(d):
    pages = d["pages"]
    active_id = initial_page_id(d)
    links = []
    for p in pages:
        if not p.get("show_in_menu", True):
            continue
        if p.get("type") == "gallery":
            cls = " class=\"active\"" if p["id"] == active_id else ""
            links.append(
                f'                <a href="#" data-filter="{p["id"]}"{cls}>{p["label"].lower()}</a>'
            )
        elif p.get("type") == "info":
            links.append(f'                <a href="#info">{p["label"].lower()}</a>')
    return "\n".join(links)


def render_categories_js(d):
    ids = [p["id"] for p in d["pages"] if p.get("show_in_menu", True)]
    return json.dumps(ids)


def render_gallery(d, edit=""):
    pages = d["pages"]
    site_name = d["site"].get("name", "")
    renderers = {"music": render_music, "watch": render_watch,
                 "press": render_press, "news": render_news}
    blocks = []
    for p in pages:
        if p.get("type") != "gallery":
            continue
        blocks.append(f"    <!-- {p['label'].upper()} -->")
        cat = p["id"]
        for i, item in enumerate(d.get(cat, [])):
            ep = f"{cat}/{i}" if edit else ""
            kind = item.get("kind", "music")
            fn = renderers.get(kind)
            if fn:
                if kind == "news":
                    block = fn(item, cat, site_name, edit=ep)
                else:
                    block = fn(item, cat, edit=ep)
            else:
                block = render_generic(item, cat, edit=ep)
            blocks.append(block)
    return "\n\n".join(blocks)


def render_generic(item, category="", edit=""):
    """Fallback for kinds without a dedicated renderer."""
    ep = f' data-edit="{edit}"' if edit else ""
    out = []
    img = media_src(item.get("img"))
    url = item.get("url")
    if img and url:
        out.append(f'<a class="keyvisual" href="{url}">'
                   f'<img src="{img}" alt="" loading="lazy"></a>')
    elif img:
        out.append(f'<div class="keyvisual"><img src="{img}" alt="" '
                   f'loading="lazy"></div>')
    if item.get("credit"):
        out.append(render_credit(item["credit"], item.get("credit_color", ""),
                                 edit_field="credit" if edit else ""))
    for k in ("span", "caption", "text"):
        v = item.get(k)
        if v:
            efk = f' data-edit-field="{k}"' if edit else ""
            out.append(f'<p class="tem"{span_style(item.get("span_color", ""))}{efk}>'
                       f'{nl_to_br(v)}</p>')
    if not out:
        return ""
    attr = f' data-category="{category}"' if category else ""
    return f'<div class="gallery-item"{attr}{ep}>' + "".join(out) + "</div>"


def render_bio(d, edit=""):
    social = d["social"]
    iu = (social.get("instagram_url") or "").strip()
    ih = (social.get("instagram_handle") or "").strip()
    bu = (social.get("bandcamp_url") or "").strip()
    booking = (social.get("booking_label") or "").strip() or "Booking / shows:"
    insta_lbl = (social.get("instagram_label") or "").strip() or "on Instagram"
    bc_lbl = (social.get("bandcamp_label") or "").strip() or "music"
    parts = []
    if iu or ih:
        handle_txt = f"@{ih}" if ih else "Instagram"
        insta = f'<a href="{iu}" target="_blank">{handle_txt}</a>' if iu else handle_txt
        parts.append(f"<strong>{booking}</strong> DM\n{insta}\n{insta_lbl}")
    if bu:
        link = f'<a href="{bu}" target="_blank">Bandcamp</a>'
        if parts:
            parts[-1] += f" &nbsp;/&nbsp; {bc_lbl}:\n{link}"
        else:
            head = bc_lbl[:1].upper() + bc_lbl[1:]
            parts.append(f"<strong>{head}:</strong>\n{link}")
    cta = "\n".join(parts)
    paragraphs = [nl_to_br(p) for p in d["bio"]]
    blocks = []
    for i, p in enumerate(paragraphs):
        ata = f' data-edit="bio/{i}"' if edit else ""
        blocks.append(f"                <p{ata}>\n                    {p}\n                </p>")
    if cta:
        blocks.append(f"                <p>\n                    {cta}\n                </p>")
    return "\n\n".join(blocks)


def render_initial_filter(d):
    """JS literal for the page shown on load. Legacy resolves to 'music'."""
    active = initial_page_id(d) or "music"
    return "'" + active.replace("\\", "\\\\").replace("'", "\\'") + "'"


def render_menu_socials(d):
    s = d["social"]
    A = " " * 16  # anchor
    S = " " * 20  # svg
    N = " " * 24  # inner svg nodes
    socials = [
        {
            "url": s["instagram_url"],
            "aria": ' aria-label="Instagram"',
            "svg": f'{S}<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">\n'
                    f'{N}<rect x="2.5" y="2.5" width="19" height="19" rx="5"></rect>\n'
                    f'{N}<circle cx="12" cy="12" r="4.2"></circle>\n'
                    f'{N}<circle cx="17.3" cy="6.7" r="0.55" fill="currentColor" stroke="none"></circle>\n'
                    f"{S}</svg>",
        },
        {
            "url": s["bandcamp_url"],
            "aria": "",
            "svg": f'{S}<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">\n'
                    f'{N}<path d="M3 18c1.5 0 2.5-1 2.5-2.5C5.5 14 4.5 13 3 13s-2 .5-1.5 1.5C2 15.5 3 16 3.5 17M8 18c1.5 0 2.5-1 2.5-2.5C10.5 14 9.5 13 8 13s-2 .5-1.5 1.5C7 15.5 8 16 8.5 17M13 18h2.5c4 0 4-6 0-6S11.9 12 13 18z"></path>\n'
                    f"{S}</svg>",
        },
        {
            "url": s["behance_url"],
            "aria": ' aria-label="Behance"',
            "svg": f'{S}<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">\n'
                    f'{N}<path d="M5.5 17V7h4.5a2.8 2.8 0 0 1 0 5H5.5"></path>\n'
                    f'{N}<path d="M5.5 12h5.5a2.6 2.6 0 0 1 0 5H5.5z"></path>\n'
                    f'{N}<circle cx="16.4" cy="12.5" r="3.1"></circle>\n'
                    f'{N}<path d="M13.5 12.5h5.8"></path>\n'
                    f'{N}<circle cx="21.2" cy="7.8" r="0.7" fill="currentColor" stroke="none"></circle>\n'
                    f"{S}</svg>",
        },
    ]
    out = []
    for x in socials:
        if not (x["url"] or "").strip():
            continue
        out.append(
            f'{A}<a href="{x["url"]}" target="_blank" class="social-link"{x["aria"]}>\n'
            f'{x["svg"]}\n'
            f"{A}</a>"
        )
    return "\n\n".join(out)


def build(d, template, out_dir=None, edit=False):
    for key, val in {
        "{{HEAD_META}}": render_head_meta(d),
        "{{HEAD_EXTRA}}": render_head_extra(d, out_dir, edit=edit),
        "{{GALLERY_ITEMS}}": render_gallery(d, edit=edit),
        "{{BIO_CONTENT}}": render_bio(d, edit="bio" if edit else ""),
        "{{MENU_ITEMS}}": render_menu(d),
        "{{MENU_SOCIALS}}": render_menu_socials(d),
"{{CATEGORIES_JS}}": render_categories_js(d),
       "{{INITIAL_FILTER}}": render_initial_filter(d),
       "{{SITE_TITLE}}": d["site"]["logo_text"],
       "{{BIO_H2}}": d["site"]["bio_h2"],
       "{{HEADER_IMAGE}}": media_src(d["site"].get("hero")),
    }.items():
        if key not in template:
            raise ValueError(f"placeholder missing in template: {key}")
        template = template.replace(key, val)
    leftover = [tok for tok in template.split() if tok.startswith("{{") and tok.endswith("}}")]
    if leftover:
        raise ValueError(f"unresolved placeholders: {leftover}")
    return template


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", type=pathlib.Path, default=DATA)
    ap.add_argument("--template", type=pathlib.Path, default=TEMPLATE)
    ap.add_argument("--out", type=pathlib.Path, default=OUT)
    ap.add_argument("--diff", action="store_true", help="diff output vs reference")
    args = ap.parse_args()

    d = json.loads(args.data.read_text(encoding="utf-8"))
    template = args.template.read_text(encoding="utf-8")
    out_dir = args.out.parent if args.out != OUT or args.data != DATA else None
    html = build(d, template, out_dir=out_dir)
    html += "\n"

    args.out.write_text(html, encoding="utf-8")
    print(f"wrote {args.out} ({len(html)} chars)")

    if args.diff and REFERENCE.exists():
        ref = REFERENCE.read_text(encoding="utf-8")
        ref_lines = [l.rstrip() for l in ref.splitlines()]
        new_lines = [l.rstrip() for l in html.splitlines()]
        import difflib
        diff = list(difflib.unified_diff(ref_lines, new_lines, "reference", "new", lineterm=""))
        if diff:
            print("--- DIFF vs reference ---")
            for line in diff:
                print(line)
        else:
            print("identical to reference")


if __name__ == "__main__":
    sys.exit(main())