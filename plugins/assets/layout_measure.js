'use strict';

// Measure the layout of generated pages in headless Chrome (puppeteer).
//
// Usage:
//   node layout_measure.js --input=pages.json [--root=body]
//        [--exclude="nav, footer"] [--width=1920] [--height=1080] [--images=1|render|0]
//
// pages.json: [{"html": "/abs/path/index.html", "out": "/abs/output/dir"}, ...]
// For each page, writes <out>/layout.json and, if images=1, <out>/render.png
// (real render), <out>/overlay.png (real render + outlined ink of each block)
// and <out>/blocks.png (ink of each block as solid rectangles).

const fs = require('fs');
const path = require('path');
const puppeteer = require('puppeteer');
const {localFrames} = require('./frames');
// interactive states: agent extension, loaded only for the pages that enable them
let interactiveModule = null;
function interactive() {
    return interactiveModule ||= require(path.join(__dirname, '..', '..', 'agent', 'assets', 'interactive_states'));
}
const args = require('minimist')(process.argv.slice(2));

const pages = JSON.parse(fs.readFileSync(args.input, 'utf-8'));
const rootSelector = args.root || 'body';
const excludeSelector = args.exclude || 'nav, footer';
const width = parseInt(args.width || 1920);
const height = parseInt(args.height || 1080);
// images: 1 = render, overlay and blocks; render = render only; 0 = none
const images = String(args.images === undefined ? '1' : args.images);
const withImages = images !== '0';

const PALETTE = ['#e6194b', '#3cb44b', '#4363d8', '#f58231', '#911eb4', '#42d4f4',
                 '#f032e6', '#bfef45', '#469990', '#9a6324', '#800000', '#808000',
                 '#000075', '#fabed4', '#ffd8b1', '#aaffc3'];


// Runs in the page: extracts the top-level blocks under the content root.
//
// Each block has a list of typed ink rectangles {x, y, w, h, t} in page
// coordinates (CSS px), describing what is actually drawn:
//   t = 'text'   a line (or line fragment) of text
//   t = 'media'  an image cell with drawn pixels, a video, a canvas...
//   t = 'paint'  an element painting a background or a border
// and, if some of its text is hidden by another block drawn on top of it,
// a list 'hidden_text' of {by, x, y, w, h, samples, total}.
function extractBlocks(rootSelector, excludeSelector) {
    const MEDIA = new Set(['IMG', 'VIDEO', 'SVG', 'CANVAS', 'IFRAME', 'svg']);
    const IMAGE_CELL = 16;      // CSS px, resolution of the shape of images
    const root = document.querySelector(rootSelector) || document.body;

    const round = (v) => Math.round(v);
    const clean = (s) => (s || '').replace(/\s+/g, ' ').trim();
    // cut by code points (not UTF-16 units) so that surrogate pairs (math symbols) stay whole
    const excerpt = (s, n = 60) => { const c = Array.from(clean(s)); return c.length > n ? c.slice(0, n).join('') + '…' : c.join(''); };
    const basename = (src) => (src || '').split('/').pop().split('?')[0];

    function toRect(r, t) {
        return {x: round(r.left + scrollX), y: round(r.top + scrollY), w: round(r.width), h: round(r.height), t};
    }

    function unionRects(rects) {
        let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
        for (const r of rects) {
            if (r.w <= 0 || r.h <= 0) continue;
            x0 = Math.min(x0, r.x); y0 = Math.min(y0, r.y);
            x1 = Math.max(x1, r.x + r.w); y1 = Math.max(y1, r.y + r.h);
        }
        return x0 === Infinity ? null : {x: x0, y: y0, w: x1 - x0, h: y1 - y0};
    }

    const contains = (a, b) => a.x <= b.x && a.y <= b.y && a.x + a.w >= b.x + b.w && a.y + a.h >= b.y + b.h;

    // Merge rectangles of the same type: fragments of a same line of text
    // (vertical overlap of at least half their height, horizontal gap below
    // gapFor(t)), adjacent image cells, and rectangles contained in another.
    function mergeRects(rects, gapFor) {
        const list = rects.filter(r => r.w > 1 && r.h > 1).map(r => ({...r}));
        let merged = true;
        while (merged) {
            merged = false;
            outer:
            for (let i = 0; i < list.length; i++) {
                for (let j = i + 1; j < list.length; j++) {
                    const a = list[i], b = list[j];
                    if (a.t !== b.t) continue;
                    const overlapY = Math.min(a.y + a.h, b.y + b.h) - Math.max(a.y, b.y);
                    const gapX = Math.max(a.x, b.x) - Math.min(a.x + a.w, b.x + b.w);
                    const sameColumn = a.x === b.x && a.w === b.w
                        && Math.max(a.y, b.y) <= Math.min(a.y + a.h, b.y + b.h);
                    if (contains(a, b) || contains(b, a) || sameColumn
                        || (overlapY >= 0.5 * Math.min(a.h, b.h) && gapX <= gapFor(a.t))) {
                        list[i] = {...unionRects([a, b]), t: a.t};
                        list.splice(j, 1);
                        merged = true;
                        break outer;
                    }
                }
            }
        }
        return list;
    }

    function paints(cs) {
        // background or border actually drawn
        const bg = cs.backgroundColor;
        if (bg && bg !== 'transparent' && !/rgba\([^)]*,\s*0\)$/.test(bg)) return true;
        if (cs.backgroundImage && cs.backgroundImage !== 'none') return true;
        return ['Top', 'Right', 'Bottom', 'Left'].some(s =>
            parseFloat(cs['border' + s + 'Width']) > 0 && cs['border' + s + 'Style'] !== 'none');
    }

    function isHiddenText(el) {
        // hidden or clipped helpers, e.g. KaTeX MathML kept for accessibility
        for (let e = el; e; e = e.parentElement) {
            if (e.classList && e.classList.contains('katex-mathml')) return true;
            const cs = getComputedStyle(e);
            if (cs.visibility === 'hidden' || cs.display === 'none' || (cs.clip && cs.clip !== 'auto')) return true;
            if (e === root) break;
        }
        return false;
    }

    // Pixels of an image (cached): alpha and "drawn" flag (neither
    // transparent nor of the uniform background color taken from the corners).
    const imageCache = new Map();
    function imagePixels(img) {
        if (imageCache.has(img)) return imageCache.get(img);
        let result = null;
        if (img.tagName === 'IMG' && img.complete && img.naturalWidth) {
            const scale = Math.min(1, 400 / Math.max(img.naturalWidth, img.naturalHeight));
            const cw = Math.max(1, Math.round(img.naturalWidth * scale));
            const ch = Math.max(1, Math.round(img.naturalHeight * scale));
            try {
                const canvas = document.createElement('canvas');
                canvas.width = cw; canvas.height = ch;
                const ctx = canvas.getContext('2d');
                ctx.drawImage(img, 0, 0, cw, ch);
                const data = ctx.getImageData(0, 0, cw, ch).data;
                const px = (x, y) => data.subarray(4 * (y * cw + x), 4 * (y * cw + x) + 4);
                const corners = [px(0, 0), px(cw - 1, 0), px(0, ch - 1), px(cw - 1, ch - 1)];
                const transparent = corners.some(c => c[3] < 16);
                const bg = corners[0];
                const close = (c) => Math.max(Math.abs(c[0] - bg[0]), Math.abs(c[1] - bg[1]),
                                              Math.abs(c[2] - bg[2])) <= 24;
                const uniform = transparent || corners.every(close);
                const drawn = !uniform ? () => true
                    : transparent ? (x, y) => px(x, y)[3] >= 16
                    : (x, y) => px(x, y)[3] >= 16 && !close(px(x, y));
                result = {cw, ch, uniform, drawn, opaque: (x, y) => px(x, y)[3] >= 16};
            } catch (e) {
                result = null;
            }
        }
        imageCache.set(img, result);
        return result;
    }

    // Shape of an image: cells of IMAGE_CELL px containing drawn pixels,
    // merged into rectangles. Also returns the bounding rectangle of the
    // drawn content. The whole image if it cannot be analysed.
    function imageShape(img) {
        const box = toRect(img.getBoundingClientRect(), 'media');
        const p = imagePixels(img);
        if (!p || !p.uniform || box.w <= 0 || box.h <= 0) return {cells: [box], content: box};
        const nx = Math.max(1, Math.ceil(box.w / IMAGE_CELL)), ny = Math.max(1, Math.ceil(box.h / IMAGE_CELL));
        const cells = [];
        for (let j = 0; j < ny; j++) {
            for (let i = 0; i < nx; i++) {
                const x0 = Math.floor(i * p.cw / nx), x1 = Math.max(x0 + 1, Math.floor((i + 1) * p.cw / nx));
                const y0 = Math.floor(j * p.ch / ny), y1 = Math.max(y0 + 1, Math.floor((j + 1) * p.ch / ny));
                let found = false;
                for (let y = y0; y < y1 && y < p.ch && !found; y++) {
                    for (let x = x0; x < x1 && x < p.cw; x++) {
                        if (p.drawn(x, y)) { found = true; break; }
                    }
                }
                if (found) {
                    const cx = box.x + round(i * box.w / nx), cy = box.y + round(j * box.h / ny);
                    cells.push({x: cx, y: cy, w: box.x + round((i + 1) * box.w / nx) - cx,
                                h: box.y + round((j + 1) * box.h / ny) - cy, t: 'media'});
                }
            }
        }
        if (!cells.length) return {cells: [box], content: box};
        return {cells: mergeRects(cells, () => 0), content: {...unionRects(cells), t: 'media'}};
    }

    // Ink of an element: text lines, media (image shapes) and descendants
    // painting a background or a border, as typed rectangles. Invisible
    // layout boxes (full-width blocks, struts) are ignored.
    // Elements placed out of the flow (position fixed or absolute) inside a
    // block are measured as blocks of their own, so that their overlaps with
    // the rest of the block are found; `skip`: those of the block.
    const inside = (node, skip) => skip.some(s => s.contains(node));
    function positionedDescendants(el) {
        const found = [];
        for (const d of el.querySelectorAll('*')) {
            if (found.some(f => f.contains(d)) || d.closest('.katex')) continue;     // KaTeX: internal layout
            const cs = getComputedStyle(d);
            if ((cs.position === 'fixed' || cs.position === 'absolute') && isVisible(d)) found.push(d);
        }
        return found;
    }

    function inkRects(el, fontSize, stats, skip = [], preciseMath = false) {
        const metrics = preciseMath ? document.createElement("canvas").getContext("2d") : null;
        const rects = [];
        const own = (e) => {
            if (e.tagName === 'IMG') rects.push(...imageShape(e).cells);
            else if (MEDIA.has(e.tagName)) rects.push(toRect(e.getBoundingClientRect(), 'media'));
            else if (paints(getComputedStyle(e))) rects.push(toRect(e.getBoundingClientRect(), 'paint'));
        };
        own(el);
        const range = document.createRange();
        const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
        let node, count = 0;
        while ((node = walker.nextNode()) && count < 5000) {
            if (!node.textContent.trim() || isHiddenText(node.parentElement) || inside(node, skip)) continue;
            if (stats) countText(node, stats);
            range.selectNodeContents(node);
            for (const r of range.getClientRects()) {
                let drawn = toRect(r, 'text');
                if (metrics && node.parentElement.closest('.katex')) {
                    // KaTeX size fonts reserve very tall line boxes for delimiters.
                    // Canvas font metrics locate the actual glyphs around the baseline.
                    metrics.font = getComputedStyle(node.parentElement).font;
                    const m = metrics.measureText(node.textContent);
                    if (Number.isFinite(m.fontBoundingBoxDescent) && m.actualBoundingBoxAscent + m.actualBoundingBoxDescent > 0) {
                        const baseline = drawn.y + drawn.h - m.fontBoundingBoxDescent;
                        drawn.y = round(baseline - m.actualBoundingBoxAscent);
                        drawn.h = round(m.actualBoundingBoxAscent + m.actualBoundingBoxDescent);
                    }
                }
                rects.push(drawn);
            }
            count++;
        }
        const descendants = el.getElementsByTagName('*');
        for (let i = 0; i < descendants.length && i < 3000; i++) {
            if (inside(descendants[i], skip)) continue;
            const cs = getComputedStyle(descendants[i]);
            if (cs.display === 'none' || cs.visibility === 'hidden') continue;
            own(descendants[i]);
        }
        return mergeRects(rects, (t) => t === 'text' && !skip.length ? Math.max(8, fontSize) : 0);
    }

    // Text statistics of a block: prose words (math and code excluded),
    // formulas, lines of code, list items, smallest font size of prose/code.
    function newStats() { return {words: 0, formulas: 0, code_lines: 0, items: 0, min_font: null}; }
    function countText(node, stats) {
        const parent = node.parentElement;
        if (parent.closest('.katex')) return;
        const size = round(parseFloat(getComputedStyle(parent).fontSize) || 16);
        stats.min_font = stats.min_font === null ? size : Math.min(stats.min_font, size);
        if (!parent.closest('pre')) stats.words += (node.textContent.match(/[\p{L}\p{N}][\p{L}\p{N}'’-]*/gu) || []).length;
    }
    function elementStats(el, stats) {
        const all = (sel) => [...(el.matches(sel) ? [el] : []), ...el.querySelectorAll(sel)];
        stats.formulas = all('.katex').filter(k => !k.parentElement.closest('.katex')).length;
        stats.code_lines = all('pre').filter(p => !p.parentElement.closest('pre'))
            .reduce((n, p) => n + p.innerText.split('\n').filter(l => l.trim()).length, 0);
        stats.items = all('li').length;
        return stats;
    }

    function isVisible(el) {
        const cs = getComputedStyle(el);
        if (cs.display === 'none' || cs.visibility === 'hidden' || el.classList.contains('hidden')) return false;
        const r = el.getBoundingClientRect();
        return r.width > 0 && r.height > 0;
    }

    function isInline(el) {
        if (MEDIA.has(el.tagName) || el.tagName === 'BR') return el.tagName === 'BR';
        const cs = getComputedStyle(el);
        if (cs.position === 'fixed' || cs.position === 'absolute') return false;
        if (cs.display !== 'inline') return false;
        // an inline element that only wraps media (e.g. <a><img></a>) is a media block
        const hasMedia = el.querySelector('img, video, svg, canvas, iframe');
        return !(hasMedia && !clean(el.textContent));
    }

    function kindOf(el) {
        const t = el.tagName.toUpperCase();
        if (/^H[1-6]$/.test(t)) return 'title';
        if (t === 'UL' || t === 'OL' || t === 'DL') return 'list';
        if (t === 'PRE' || el.classList.contains('code') || el.querySelector(':scope > pre')) return 'code';
        if (t === 'IMG' || t === 'SVG' || t === 'CANVAS') return 'image';
        if (t === 'VIDEO' || t === 'IFRAME') return 'video';
        if (el.classList.contains('katex-display') || t === 'MATH') return 'math';
        if (t === 'TABLE') return 'table';
        if (t === 'P') return 'text';
        if (!clean(el.textContent) && el.querySelector('img, video, svg, canvas, iframe')) return 'image';
        return 'div';
    }

    // Rectangle where an image or a video is drawn in its box (object-fit):
    // smaller than the box with contain (empty bands), larger with cover (cropped).
    function drawnRect(el, box) {
        const nw = el.naturalWidth || el.videoWidth, nh = el.naturalHeight || el.videoHeight;
        const fit = getComputedStyle(el).objectFit;
        if (!nw || !nh || !box.w || !box.h || !['contain', 'cover', 'scale-down'].includes(fit)) return null;
        let scale = fit === 'cover' ? Math.max(box.w / nw, box.h / nh) : Math.min(box.w / nw, box.h / nh);
        if (fit === 'scale-down') scale = Math.min(1, scale);
        const w = nw * scale, h = nh * scale;
        return {x: round(box.x + (box.w - w) / 2), y: round(box.y + (box.h - h) / 2), w: round(w), h: round(h), fit};
    }

    const sourceOf = (el) => el.dataset.layoutSrc || el.getAttribute('src')
        || (el.querySelector && el.querySelector('source') ? el.querySelector('source').getAttribute('src') : '') || '';

    function mediaInfo(el, skip = []) {
        // the figures shown: not those hidden on purpose ((.hidden), a closed <details>)
        const shown = (m) => !m.checkVisibility || m.checkVisibility({checkVisibilityCSS: true});
        const items = (['IMG', 'VIDEO'].includes(el.tagName) ? [el] : [...el.querySelectorAll('img, video')])
            .filter(m => !inside(m, skip) && shown(m));
        return items.slice(0, 6).map(img => {
            const box = toRect(img.getBoundingClientRect());
            const src = sourceOf(img);
            delete box.t;
            const content = img.tagName === 'IMG' ? {...imageShape(img).content} : {...box};
            delete content.t;
            return {src: basename(src), url: src, w: box.w, h: box.h, tag: img.tagName.toLowerCase(),
                    natural_w: img.naturalWidth || img.videoWidth, natural_h: img.naturalHeight || img.videoHeight,
                    vector: /\.svgz?(\?|#|$)/i.test(src), box, content, drawn: drawnRect(img, box)};
        });
    }

    // Lines of the own text of an element (not of its nested lists): the
    // distinct line boxes of its text nodes.
    function ownLines(el) {
        const range = document.createRange();
        const tops = [];
        let firstW = 0, lastW = 0;
        const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
        let node;
        const rects = [];
        const formulas = new Set();
        while ((node = walker.nextNode())) {
            if (!node.textContent.trim() || isHiddenText(node.parentElement)) continue;
            const owner = node.parentElement.closest('li, h1, h2, h3, h4, h5, h6, .credit');
            if (owner !== el) continue;
            // a formula is one box (its sums, indices and fractions are not lines)
            const formula = node.parentElement.closest('.katex');
            if (formula) {
                if (!formulas.has(formula)) {
                    formulas.add(formula);
                    rects.push(...[...formula.getClientRects()].filter(r => r.width > 0));
                }
                continue;
            }
            range.selectNodeContents(node);
            rects.push(...[...range.getClientRects()].filter(r => r.width > 0));
        }
        const lines = [];
        for (const r of rects.sort((a, b) => a.top - b.top || a.left - b.left)) {
            const mid = r.top + r.height / 2;
            const line = lines.find(l => Math.abs(l.mid - mid) < Math.max(r.height, l.h) / 2);
            if (line) { line.x0 = Math.min(line.x0, r.left); line.x1 = Math.max(line.x1, r.right); }
            else lines.push({mid, h: r.height, x0: r.left, x1: r.right});
        }
        return lines.map(l => round(l.x1 - l.x0));
    }

    // Titles, list items and credits written on several lines.
    function wrappedItems(el) {
        const items = el.matches('li, h1, h2, h3, h4, h5, h6, .credit') ? [el] : [];
        items.push(...el.querySelectorAll('li, h1, h2, h3, h4, h5, h6, .credit'));
        const found = [];
        for (const item of items.slice(0, 200)) {
            const widths = ownLines(item);
            if (widths.length > 1) {
                found.push({tag: item.tagName.toLowerCase() + (item.classList.contains('credit') ? '.credit' : ''),
                            text: excerpt(item.innerText, 50), lines: widths.length,
                            first_w: widths[0], last_w: widths[widths.length - 1]});
            }
        }
        return found;
    }

    // Figures side by side in a container (a row): the top and bottom of what
    // they draw, to check that they are aligned.
    const figureIds = new Map();
    function figureRows(el) {
        const rows = [], seen = new Set();
        for (const container of [el, ...el.querySelectorAll('*')].slice(0, 2000)) {
            const figures = [...container.children].map(c =>
                MEDIA.has(c.tagName) ? c : c.querySelector('img, video, svg, canvas, iframe')).filter(Boolean);
            if (figures.length < 2) continue;
            const key = figures.map(f => { if (!figureIds.has(f)) figureIds.set(f, figureIds.size); return figureIds.get(f); }).join(',');
            if (seen.has(key)) continue;
            seen.add(key);
            const rects = figures.map(f => {
                const box = toRect(f.getBoundingClientRect());
                return drawnRect(f, box) || box;
            }).filter(r => r.w > 0 && r.h > 0);
            if (rects.length < 2) continue;
            const order = rects.map((r, i) => i).sort((a, b) => rects[a].x - rects[b].x);
            const sideBySide = order.every((i, k) => k === 0 || (rects[order[k - 1]].x + rects[order[k - 1]].w <= rects[i].x + 2
                && Math.min(rects[order[k - 1]].y + rects[order[k - 1]].h, rects[i].y + rects[i].h) > Math.max(rects[order[k - 1]].y, rects[i].y)));
            if (!sideBySide) continue;
            rows.push({figures: order.map(i => basename(sourceOf(figures[i])) || figures[i].tagName.toLowerCase()),
                       tops: order.map(i => rects[i].y), bottoms: order.map(i => rects[i].y + rects[i].h)});
        }
        return rows;
    }

    // SVG figures: what they draw beyond their viewBox (cut when shown), and
    // their labels drawn across a line of the figure. An SVG image is analysed
    // in a copy of its file (window.__layoutSvg, read before), drawn out of
    // the page at 1 px per unit of its viewBox.
    const DRAWN = 'path, line, polyline, polygon, rect, circle, ellipse, text, image, use';
    const NOT_DRAWN = 'defs, marker, clipPath, mask, pattern, symbol, title, desc, metadata';
    // the viewBox of an svg: its viewBox attribute, else its width and height
    // when they are in px (10cm or 100% are not units of its content)
    function viewBoxOf(svg) {
        const vb = svg.viewBox && svg.viewBox.baseVal;
        if (vb && vb.width > 0 && vb.height > 0) return {x: vb.x, y: vb.y, w: vb.width, h: vb.height};
        const plain = (v) => /^\s*[\d.]+(px)?\s*$/.test(v || '') ? parseFloat(v) : NaN;
        const w = plain(svg.getAttribute('width')), h = plain(svg.getAttribute('height'));
        return w > 0 && h > 0 ? {x: 0, y: 0, w, h} : null;
    }
    function hasHalo(text) {
        for (let e = text; e && e.tagName && e.tagName.toLowerCase() !== 'svg'; e = e.parentNode) {
            const cs = getComputedStyle(e);
            if (cs.paintOrder && cs.paintOrder.startsWith('stroke') && cs.stroke !== 'none'
                && parseFloat(cs.strokeWidth) > 0) return true;
        }
        return false;
    }
    const drawnElements = (svg) => [...svg.querySelectorAll(DRAWN)].filter(e => !e.closest(NOT_DRAWN)
        && getComputedStyle(e).display !== 'none' && getComputedStyle(e).visibility !== 'hidden');
    const meets = (a, b) => a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom;

    // Labels (text without a halo) drawn across a stroked element: points of the
    // glyphs' band (without the space of the ascenders and descenders), close
    // enough to meet a thin line; only the elements whose box meets the label,
    // and a bounded number of tests (large plots stay fast).
    function svgLabels(drawn) {
        const strokes = [];
        for (const e of drawn) {
            if (e.tagName.toLowerCase() === 'text' || !e.isPointInStroke) continue;
            const cs = getComputedStyle(e);
            if (cs.stroke === 'none' || !(parseFloat(cs.strokeWidth) > 0)
                || parseFloat(cs.strokeOpacity) === 0) continue;
            const m = e.getScreenCTM();
            if (m) strokes.push({e, rect: e.getBoundingClientRect(), inverse: m.inverse(),
                                 pad: parseFloat(cs.strokeWidth) * Math.abs(m.a || 1)});
        }
        const labels = [];
        let budget = 20000;             // isPointInStroke calls for the figure
        for (const text of drawn.filter(e => e.tagName.toLowerCase() === 'text').slice(0, 300)) {
            if (budget <= 0) break;
            if (hasHalo(text)) continue;
            const r = text.getBoundingClientRect();
            if (r.width <= 0 || r.height <= 0) continue;
            for (const s of strokes) {
                const box = {left: s.rect.left - s.pad, right: s.rect.right + s.pad,
                             top: s.rect.top - s.pad, bottom: s.rect.bottom + s.pad};
                if (!meets(r, box) || budget <= 0) continue;
                const nx = Math.min(40, Math.max(4, Math.ceil(r.width / 3)));
                const ny = Math.min(12, Math.max(3, Math.ceil(0.6 * r.height / 1.5)));
                let hits = 0;
                for (let i = 0; i < nx && hits < 2; i++) {
                    for (let j = 0; j < ny && hits < 2; j++) {
                        const x = r.left + r.width * (i + 0.5) / nx;
                        const y = r.top + r.height * (0.3 + 0.55 * (j + 0.5) / ny);
                        if (x < box.left || x > box.right || y < box.top || y > box.bottom) continue;
                        budget--;
                        if (s.e.isPointInStroke(new DOMPoint(x, y).matrixTransform(s.inverse))) hits++;
                    }
                }
                if (hits >= 2) { labels.push({text: excerpt(text.textContent, 40), over: s.e.tagName.toLowerCase()}); break; }
            }
        }
        return labels;
    }

    // An SVG image: analysed in a copy of its file (window.__layoutSvg, read
    // before), drawn out of the page at 1 px per unit of its viewBox; what it
    // draws beyond its viewBox is measured on its pixels (window.__layoutSvgInk).
    // Once per file and size.
    const svgImageCache = new Map();
    function svgImageChecks(img, drawn) {
        const url = img.currentSrc || img.src;
        const key = `${url} ${drawn.w}x${drawn.h}`;
        if (svgImageCache.has(key)) return svgImageCache.get(key);
        let result = null;
        const text = (window.__layoutSvg || {})[url];
        const source = text && new DOMParser().parseFromString(text, 'image/svg+xml').documentElement;
        if (source && source.tagName.toLowerCase() === 'svg') {
            const svg = document.importNode(source, true);
            const holder = document.createElement('div');
            // out of the page and transparent (not hidden: its elements are measured as drawn)
            Object.assign(holder.style, {position: 'absolute', left: '-20000px', top: '0', opacity: '0',
                                         pointerEvents: 'none'});
            holder.appendChild(svg);
            document.body.appendChild(holder);
            try {
                const vb = viewBoxOf(svg);
                if (vb) {
                    svg.setAttribute('width', vb.w); svg.setAttribute('height', vb.h);
                    const ink = (window.__layoutSvgInk || {})[url];
                    const sx = drawn.w / vb.w, sy = drawn.h / vb.h;
                    result = {overflow: ink ? {left: round(ink.left * sx), top: round(ink.top * sy),
                                               right: round(ink.right * sx), bottom: round(ink.bottom * sy)} : null,
                              labels: svgLabels(drawnElements(svg))};
                }
            } finally {
                holder.remove();
            }
        }
        svgImageCache.set(key, result);
        return result;
    }

    // An inline svg: cut at its box (unless its overflow is visible); what
    // its elements draw beyond the box.
    function inlineSvgChecks(svg) {
        const frame = svg.getBoundingClientRect();
        if (frame.width <= 0 || frame.height <= 0) return null;
        const drawn = drawnElements(svg);
        let overflow = null;
        if (getComputedStyle(svg).overflow !== 'visible') {
            let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
            for (const e of drawn) {
                const r = e.getBoundingClientRect();
                if (r.width <= 0 && r.height <= 0) continue;
                x0 = Math.min(x0, r.left); y0 = Math.min(y0, r.top);
                x1 = Math.max(x1, r.right); y1 = Math.max(y1, r.bottom);
            }
            if (x0 !== Infinity) overflow = {left: round(Math.max(0, frame.left - x0)), top: round(Math.max(0, frame.top - y0)),
                                             right: round(Math.max(0, x1 - frame.right)), bottom: round(Math.max(0, y1 - frame.bottom))};
        }
        return {overflow, labels: svgLabels(drawn)};
    }

    function svgFigures(el, skip = []) {
        const found = [];
        const images = (el.matches('img') ? [el] : [...el.querySelectorAll('img')])
            .filter(i => !inside(i, skip) && /\.svg(\?|#|$)/i.test(i.currentSrc || i.src));
        for (const img of images.slice(0, 6)) {
            const box = toRect(img.getBoundingClientRect());
            const drawn = drawnRect(img, box) || box;
            const checks = drawn.w > 0 && drawn.h > 0 ? svgImageChecks(img, drawn) : null;
            if (checks) found.push({src: basename(sourceOf(img)), ...checks});
        }
        const inline = (el.matches('svg') ? [el] : [...el.querySelectorAll('svg')])
            .filter(v => !inside(v, skip) && !v.closest('.katex') && !(v.parentElement && v.parentElement.closest('svg')));
        for (const svg of inline.slice(0, 6)) {
            const checks = inlineSvgChecks(svg);
            if (checks) found.push({src: svg.id ? '#' + svg.id : 'svg', ...checks});
        }
        return found;
    }

    function describe(el, skip = [], details = true) {
        const cs = getComputedStyle(el);
        const box = toRect(el.getBoundingClientRect());
        delete box.t;
        const fontSize = parseFloat(cs.fontSize) || 16;
        const stats = newStats();
        const ink = inkRects(el, fontSize, stats, skip, !details);
        const visual = unionRects(ink);
        const media = mediaInfo(el, skip);
        elementStats(el, stats);
        let signature = el.tagName.toLowerCase();
        if (el.className && typeof el.className === 'string') signature += '.' + el.className.trim().split(/\s+/).join('.');
        if (el.getAttribute('style')) signature += `[${clean(el.getAttribute('style'))}]`;
        const text = excerpt(el.innerText);
        if (text) signature += ` "${text}"`;
        if (media.length) signature += ' ' + media.map(m => m.src).join(', ');
        // line of the source (data-lhtml-src="file:line" of the builds for
        // development): of the block, else of the first block inside it
        const marked = el.hasAttribute('data-lhtml-src') ? el : el.querySelector('[data-lhtml-src]');
        const source = marked ? marked.getAttribute('data-lhtml-src') : null;
        return {
            kind: visual ? kindOf(el) : 'spacer',
            signature,
            dom_id: el.id || null,
            source,
            stable_id: el.id && source ? `explicit:${source.slice(0, source.lastIndexOf(':'))}:${el.id}`
                : marked?.getAttribute('data-lhtml-id') || null,
            provenance: marked?.hasAttribute('data-lhtml-provenance')
                ? JSON.parse(marked.getAttribute('data-lhtml-provenance')) : null,
            line: source ? parseInt(source.split(':').pop()) || null : null,
            box,
            visual,
            ink,
            unverified_canvas: (el.matches('canvas') ? [el] : [...el.querySelectorAll('canvas')])
                .some(c => !inside(c, skip) && isVisible(c)),
            position: cs.position,
            text_align: cs.textAlign,
            margin: ['Top', 'Right', 'Bottom', 'Left'].map(s => round(parseFloat(cs['margin' + s]) || 0)),
            font_size: round(fontSize),
            overflow: cs.overflow,
            scroll: {w: el.scrollWidth, h: el.scrollHeight, client_w: el.clientWidth, client_h: el.clientHeight},
            media,
            wrapped: details ? wrappedItems(el) : [],
            rows: details ? figureRows(el) : [],
            svg: details ? svgFigures(el, skip) : [],
            text: stats,
            // overlap marked as intentional in the source, e.g. ::(.overlay)[...]
            intentional: el.classList.contains('overlay'),
        };
    }

    const blocks = [];
    const blockOf = new Map();      // top-level element -> block
    let run = [];
    function flushRun() {
        const nodes = run; run = [];
        if (!nodes.some(n => clean(n.textContent))) return;
        const range = document.createRange();
        range.setStartBefore(nodes[0]);
        range.setEndAfter(nodes[nodes.length - 1]);
        const fontSize = parseFloat(getComputedStyle(root).fontSize) || 16;
        const ink = mergeRects([...range.getClientRects()].map(r => toRect(r, 'text')),
                               () => Math.max(8, fontSize));
        const visual = unionRects(ink);
        if (!visual) return;
        const stats = newStats();
        for (const n of nodes) {
            if (n.nodeType === Node.TEXT_NODE) { if (n.textContent.trim()) countText(n, stats); continue; }
            const walker = document.createTreeWalker(n, NodeFilter.SHOW_TEXT);
            let t;
            while ((t = walker.nextNode())) if (t.textContent.trim() && !isHiddenText(t.parentElement)) countText(t, stats);
            const s = elementStats(n, newStats());
            stats.formulas += s.formulas; stats.code_lines += s.code_lines; stats.items += s.items;
        }
        const marked = nodes.filter(n => n.nodeType === Node.ELEMENT_NODE)
            .map(n => n.hasAttribute('data-lhtml-src') ? n : n.querySelector('[data-lhtml-src]')).find(Boolean);
        const textValue = clean(nodes.map(n => n.textContent).join(' '));
        const free = JSON.parse(root.getAttribute('data-lhtml-free-text') || '[]')
            .find(row => textValue.includes(row.text));
        const source = marked?.getAttribute('data-lhtml-src') || free?.source || null;
        const stable_id = marked?.getAttribute('data-lhtml-id') || free?.stable_id || null;
        const provenance = marked?.hasAttribute('data-lhtml-provenance')
            ? JSON.parse(marked.getAttribute('data-lhtml-provenance')) : free?.provenance || null;
        const freeStats = newStats();
        for (const n of nodes) if (n.nodeType === Node.TEXT_NODE && clean(n.textContent)) countText(n, freeStats);
        const block = {design_text: freeStats, source, stable_id, provenance, line: source ? parseInt(source.split(':').pop()) : null,
                       design_role: 'body', kind: 'text', signature: `text "${excerpt(nodes.map(n => n.textContent).join(' '))}"`,
                       box: visual, visual, ink, position: 'static', margin: [0, 0, 0, 0],
                       text_align: getComputedStyle(root).textAlign,
                       font_size: round(fontSize), overflow: 'visible', scroll: null, media: [],
                       wrapped: [], rows: [], svg: [],
                       text: stats, intentional: false};
        blocks.push(block);
        for (const n of nodes) if (n.nodeType === Node.ELEMENT_NODE) blockOf.set(n, block);
    }
    for (const node of root.childNodes) {
        if (node.nodeType === Node.TEXT_NODE) { run.push(node); continue; }
        if (node.nodeType !== Node.ELEMENT_NODE) continue;
        if (['SCRIPT', 'STYLE', 'NOSCRIPT', 'TEMPLATE'].includes(node.tagName)
            || node.id === '__layout_overlay' || (excludeSelector && node.matches(excludeSelector))) continue;
        if (isInline(node)) { run.push(node); continue; }
        flushRun();
        if (isVisible(node)) {
            const positioned = node.matches('.overlay') ? [] : positionedDescendants(node);
            const block = describe(node, positioned);
            blocks.push(block);
            blockOf.set(node, block);
            for (const child of positioned) {
                const nested = describe(child);
                nested.inside = block;          // replaced by its number below
                blocks.push(nested);
                blockOf.set(child, nested);
            }
        }
    }
    flushRun();
    blocks.forEach((b, i) => { b.id = i + 1; });
    blocks.forEach(b => { if (b.inside) b.inside = b.inside.id; });

    // Owned ink: semantic children are removed from their parent's measurement.
    // Keep aggregate blocks unchanged for occupancy and existing reports.
    const subblocks = [], selected = new Map();
    const atomic = 'svg, img, video, canvas, iframe, pre, .katex';
    const semantic = '.col, .column, .credit, .legende, figure, figcaption, ul, ol, li, p, h1, h2, h3, h4, blockquote, td, th, pre, .katex, img, svg, video, canvas, iframe, [data-lhtml-src]';
    let truncated = false;
    function visit(el, parent, owner) {
        if (!isVisible(el) || el.matches('script, style, noscript, template')
            || (excludeSelector && el.matches(excludeSelector))) return;
        let current = parent;
        if (!parent || el.matches(semantic)) {
            if (subblocks.length >= 400) { truncated = true; return; }
            const role = el.matches('.katex') ? 'formula' : el.matches('.col, .column') ? 'column'
                : el.matches('.credit, .legende, figcaption') ? 'caption' : el.tagName.toLowerCase();
            current = {el, children: [], parent, owner, role, id: 's' + (subblocks.length + 1)};
            if (parent) parent.children.push(el);
            subblocks.push(current); selected.set(el, current);
        }
        if (!el.matches(atomic)) for (const child of el.children) visit(child, current, owner);
    }
    for (const [el, block] of blockOf) {
        if (!block.inside) visit(el, null, block.id);
    }
    const internal = subblocks.map(n => {
        const b = describe(n.el, n.children, false);
        const direct = n.el.hasAttribute('data-lhtml-src');
        const origin = direct ? n.el : n.el.closest('[data-lhtml-src]');
        if (origin) {
            b.source = origin.getAttribute('data-lhtml-src');
            b.line = parseInt(b.source.split(':').pop()) || null;
            b.provenance = JSON.parse(origin.getAttribute('data-lhtml-provenance') || 'null');
            const peers = n.parent ? n.parent.children.filter(e => selected.get(e).role === n.role) : [n.el];
            b.stable_id = (origin.getAttribute('data-lhtml-id') || b.source)
                + ':internal:' + n.role + ':' + peers.indexOf(n.el);
        }
        const declared = n.el.closest('[data-lhtml-role]')?.getAttribute('data-lhtml-role');
        const roles = ['title', 'heading', 'body', 'caption', 'reference', 'code', 'formula', 'figure', 'decorative'];
        b.design_role = roles.includes(declared) ? declared
            : n.el.closest('.katex') ? 'formula' : n.el.closest('pre, .code') ? 'code'
            : n.el.closest('.source, .reference') ? 'reference'
            : n.el.closest('.credit, .legende, figcaption') ? 'caption'
            : n.el.matches('img, svg, video, canvas, iframe') ? 'figure'
            : n.el.closest('h1') ? 'title' : n.el.closest('h2, h3, h4, h5, h6') ? 'heading' : 'body';
        b.figure_container = n.el.matches('figure, .media');
        b.design_lines = 0;
        if (n.el.matches('h1')) {
            const ys = [];
            for (const r of inkRects(n.el, b.font_size, null).filter(r => r.t === 'text')) {
                if (!ys.some(y => Math.abs(y - r.y) < b.font_size * .5)) ys.push(r.y);
            }
            b.design_lines = ys.length;
        }
        b.source_precision = direct ? 'direct' : 'inherited';
        b.id = n.id; b.parent = n.parent?.id || null; b.owner = n.owner; b.role = n.role;
        b.intentional = !!n.el.closest('.overlay');
        b.legacy_block = ownerOfInternal(n.el).id;
        const cs = getComputedStyle(n.el), r = n.el.getBoundingClientRect();
        b.frame = {x: round(r.left + scrollX + parseFloat(cs.borderLeftWidth)),
                   y: round(r.top + scrollY + parseFloat(cs.borderTopWidth)),
                   w: n.el.clientWidth, h: n.el.clientHeight};
        return b;
    });
    function ownerOfInternal(el) {
        for (let e = el; e; e = e.parentElement) if (blockOf.has(e)) return blockOf.get(e);
    }

    // Hidden text: along each line of text, find the topmost element that
    // actually paints at that point (opaque image pixel, background,
    // border). If it belongs to another block, the text is hidden there.
    function ownerOf(el) {
        for (let e = el; e && e !== root; e = e.parentElement) {
            if (blockOf.has(e)) return blockOf.get(e);
        }
        return null;    // text directly under the root
    }
    function paintsAt(el, cx, cy) {
        if (el.tagName === 'IMG') {
            const p = imagePixels(el);
            if (!p) return true;
            const r = el.getBoundingClientRect();
            const x = Math.min(p.cw - 1, Math.max(0, Math.floor((cx - r.left) / r.width * p.cw)));
            const y = Math.min(p.ch - 1, Math.max(0, Math.floor((cy - r.top) / r.height * p.ch)));
            return p.opaque(x, y);
        }
        return MEDIA.has(el.tagName) || paints(getComputedStyle(el));
    }
    for (const block of blocks) {
        const hidden = new Map();
        let total = 0;
        const step = Math.max(6, block.font_size / 2);
        for (const r of block.ink.filter(r => r.t === 'text')) {
            const cy = r.y + r.h / 2 - scrollY;
            for (let x = r.x + 2; x < r.x + r.w - 2 && total < 3000; x += step) {
                total++;
                const cx = x - scrollX;
                for (const el of document.elementsFromPoint(cx, cy)) {
                    const owner = ownerOf(el);
                    if (owner === block || owner === null) break;      // own content reached first
                    if (paintsAt(el, cx, cy)) {
                        const h = hidden.get(owner.id) || {x0: Infinity, y0: Infinity, x1: -Infinity, y1: -Infinity, samples: 0};
                        h.x0 = Math.min(h.x0, x); h.x1 = Math.max(h.x1, x + step);
                        h.y0 = Math.min(h.y0, r.y); h.y1 = Math.max(h.y1, r.y + r.h);
                        h.samples++;
                        hidden.set(owner.id, h);
                        break;
                    }
                }
            }
        }
        block.hidden_text = [...hidden].filter(([, h]) => h.samples >= 2).map(([by, h]) => ({
            by, x: round(h.x0), y: round(h.y0), w: round(h.x1 - h.x0), h: round(h.y1 - h.y0),
            samples: h.samples, total}));
    }

    // usable slide area: inside of the frame drawn by the body (slides
    // theme), i.e. its padding box; the viewport if the body draws no frame.
    // A slide has a frame that fits in the viewport, even when its content
    // overflows; a web page has a body taller than the viewport.
    const body = document.body;
    const bcs = getComputedStyle(body);
    const br = body.getBoundingClientRect();
    const px = (v) => parseFloat(v) || 0;
    const framed = br.width > 0 && br.height > 0 && br.height <= innerHeight;
    const area = framed ? {
        x: round(br.left + px(bcs.borderLeftWidth)),
        y: round(br.top + px(bcs.borderTopWidth)),
        w: round(br.width - px(bcs.borderLeftWidth) - px(bcs.borderRightWidth)),
        h: round(br.height - px(bcs.borderTopWidth) - px(bcs.borderBottomWidth)),
    } : {x: 0, y: 0, w: innerWidth, h: innerHeight};
    // Areas reserved by the theme (the navigation): the visible parts of the
    // excluded elements; the content must not cover them.
    const reserved = [];
    for (const el of (excludeSelector ? document.querySelectorAll(excludeSelector) : [])) {
        const parts = [el, ...el.querySelectorAll('*')].filter(e => {
            const cs = getComputedStyle(e);
            if (cs.display === 'none' || cs.visibility === 'hidden' || e.closest('.hidden')) return false;
            const r = e.getBoundingClientRect();
            return r.width > 0 && r.height > 0 && (e.children.length === 0 || paints(cs));
        }).map(e => toRect(e.getBoundingClientRect(), 'reserved'));
        const u = unionRects(parts);
        if (u) reserved.push({...u, name: el.id ? '#' + el.id : el.tagName.toLowerCase()});
    }
    return {root: document.querySelector(rootSelector) ? rootSelector : 'body', title: document.title,
            viewport: {w: innerWidth, h: innerHeight},
            layout_name: [...document.body.classList].find(c => c.startsWith('layout-'))?.slice(7) || 'flow',
            design_measurement: {roles: true, title_lines: true}, area, blocks, subblocks: internal, internal_measurement: {truncated, limit: 400, measured: internal.length}, reserved,
            scrolling: !framed && document.documentElement.scrollHeight > innerHeight + 1};
}


// Runs in the page: draws, above the content, the ink rectangles of each
// block with its number: outlines on the real render (filled=false), or
// solid rectangles on a white background (filled=true).
function drawOverlay(blocks, palette, filled) {
    const old = document.getElementById('__layout_overlay');
    if (old) old.remove();
    const layer = document.createElement('div');
    layer.id = '__layout_overlay';
    Object.assign(layer.style, {position: 'fixed', left: '0', top: '0', width: '100vw', height: '100vh',
                                zIndex: '2147483647', pointerEvents: 'none',
                                background: filled ? 'white' : 'transparent'});
    const rectDiv = (r, style) => {
        const d = document.createElement('div');
        Object.assign(d.style, {position: 'absolute', left: (r.x - scrollX) + 'px', top: (r.y - scrollY) + 'px',
                                width: r.w + 'px', height: r.h + 'px', boxSizing: 'border-box'}, style);
        layer.appendChild(d);
        return d;
    };
    for (const [index, b] of blocks.entries()) {
        if (b.kind === 'spacer') continue;
        const color = palette[index % palette.length];
        for (const r of (b.ink && b.ink.length ? b.ink : [b.visual || b.box])) {
            rectDiv(r, filled ? {background: color, opacity: '0.7'} : {border: `2px solid ${color}`});
        }
        for (const h of (b.hidden_text || [])) {
            rectDiv(h, {border: '4px dashed black', background: filled ? 'transparent' : 'rgba(255,0,0,0.15)'});
        }
        const v = b.visual || b.box;
        const label = rectDiv({x: v.x, y: v.y, w: 0, h: 0}, {width: 'auto', height: 'auto', padding: '2px 6px',
                              font: 'bold 22px sans-serif', color: 'white', background: color});
        label.textContent = '#' + b.id;
    }
    document.body.appendChild(layer);
}


// Reproducible renders: CSS animations at their start, videos at their first
// frame, animated GIFs replaced by their first frame (WebCodecs ImageDecoder).
async function freezeMedia(page) {
    await page.evaluate(async () => {
        for (const a of document.getAnimations()) { try { a.pause(); a.currentTime = 0; } catch (e) { /* ignore */ } }
        await Promise.all([...document.querySelectorAll('video')].map(v => new Promise(resolve => {
            v.autoplay = false;
            v.pause();
            const timer = setTimeout(resolve, 3000);
            const done = () => { clearTimeout(timer); resolve(); };
            if (v.readyState >= 2 && v.currentTime === 0) return done();
            v.addEventListener('seeked', done, {once: true});
            v.addEventListener('error', done, {once: true});
            if (v.readyState >= 1) v.currentTime = 0;
            else v.addEventListener('loadedmetadata', () => { v.currentTime = 0; }, {once: true});
        })));
        const gifs = [...document.images].filter(i => /\.gif(\?|#|$)/i.test(i.currentSrc || i.src));
        for (const img of gifs) img.dataset.layoutGifUrl = img.currentSrc || img.src;
        if (!('ImageDecoder' in window)) return;
        const load = (url) => new Promise((resolve, reject) => {      // fetch() does not read file://
            const xhr = new XMLHttpRequest();
            xhr.open('GET', url);
            xhr.responseType = 'arraybuffer';
            xhr.onload = () => resolve(xhr.response);
            xhr.onerror = reject;
            xhr.send();
        });
        for (const img of gifs) {
            try {
                img.dataset.layoutGifUrl = img.currentSrc || img.src;
                const decoder = new ImageDecoder({data: await load(img.currentSrc || img.src), type: 'image/gif'});
                const {image} = await decoder.decode({frameIndex: 0});
                const canvas = document.createElement('canvas');
                canvas.width = image.displayWidth; canvas.height = image.displayHeight;
                canvas.getContext('2d').drawImage(image, 0, 0);
                image.close(); decoder.close();
                img.dataset.layoutSrc = img.getAttribute('src');
                await new Promise(resolve => { img.onload = img.onerror = resolve; img.src = canvas.toDataURL(); });
            } catch (e) { /* the GIF as it is */ }
        }
    });
}


// The SVG images, for their analysis in the page: their text
// (window.__layoutSvg), and what each one draws beyond its viewBox, in units of
// the viewBox (window.__layoutSvgInk): the image is drawn on a canvas covering
// its viewBox and all its elements, and its pixels outside the viewBox are what
// is cut when it is shown (the ink: not the boxes of the glyphs).
async function loadSvgImages(page) {
    await page.evaluate(async () => {
        window.__layoutSvg = {};
        window.__layoutSvgInk = {};
        const read = (url) => new Promise(resolve => {
            const xhr = new XMLHttpRequest();         // fetch() does not read file://
            xhr.open('GET', url);
            xhr.onload = () => resolve(xhr.responseText || null);
            xhr.onerror = () => resolve(null);
            xhr.send();
        });
        const plain = (v) => /^\s*[\d.]+(px)?\s*$/.test(v || '') ? parseFloat(v) : NaN;
        async function inkBeyond(root) {
            const vbAttr = root.viewBox && root.viewBox.baseVal && root.viewBox.baseVal.width > 0 ? root.viewBox.baseVal : null;
            const vb = vbAttr ? {x: vbAttr.x, y: vbAttr.y, w: vbAttr.width, h: vbAttr.height}
                : {x: 0, y: 0, w: plain(root.getAttribute('width')), h: plain(root.getAttribute('height'))};
            if (!(vb.w > 0 && vb.h > 0)) return null;
            // extent of the elements (in units), with the copy laid out out of the page
            const svg = document.importNode(root, true);
            svg.setAttribute('viewBox', `${vb.x} ${vb.y} ${vb.w} ${vb.h}`);
            svg.setAttribute('width', vb.w); svg.setAttribute('height', vb.h);
            svg.setAttribute('preserveAspectRatio', 'none');
            const holder = document.createElement('div');
            Object.assign(holder.style, {position: 'absolute', left: '-20000px', top: '0', opacity: '0', pointerEvents: 'none'});
            holder.appendChild(svg);
            document.body.appendChild(holder);
            let ex = {x0: vb.x, y0: vb.y, x1: vb.x + vb.w, y1: vb.y + vb.h};
            try {
                const frame = svg.getBoundingClientRect();
                const u = frame.width / vb.w || 1;
                for (const e of svg.querySelectorAll('path, line, polyline, polygon, rect, circle, ellipse, text, image, use')) {
                    if (e.closest('defs, marker, clipPath, mask, pattern, symbol')) continue;
                    const r = e.getBoundingClientRect();
                    if (r.width <= 0 && r.height <= 0) continue;
                    const pad = (parseFloat(getComputedStyle(e).strokeWidth) || 0) + 1;
                    ex.x0 = Math.min(ex.x0, vb.x + (r.left - frame.left) / u - pad);
                    ex.y0 = Math.min(ex.y0, vb.y + (r.top - frame.top) / u - pad);
                    ex.x1 = Math.max(ex.x1, vb.x + (r.right - frame.left) / u + pad);
                    ex.y1 = Math.max(ex.y1, vb.y + (r.bottom - frame.top) / u + pad);
                }
            } finally {
                holder.remove();
            }
            const m = 0.05 * Math.max(vb.w, vb.h);
            ex = {x0: ex.x0 - m, y0: ex.y0 - m, x1: ex.x1 + m, y1: ex.y1 + m};
            const W = ex.x1 - ex.x0, H = ex.y1 - ex.y0;
            const scale = 1600 / Math.max(W, H);              // px per unit
            const cw = Math.max(1, Math.round(W * scale)), ch = Math.max(1, Math.round(H * scale));
            const copy = document.importNode(root, true);
            copy.setAttribute('viewBox', `${ex.x0} ${ex.y0} ${W} ${H}`);
            copy.setAttribute('width', cw); copy.setAttribute('height', ch);
            copy.setAttribute('preserveAspectRatio', 'none');
            copy.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
            const url = URL.createObjectURL(new Blob([new XMLSerializer().serializeToString(copy)], {type: 'image/svg+xml'}));
            try {
                const img = new Image();
                await new Promise((resolve, reject) => { img.onload = resolve; img.onerror = reject; img.src = url; });
                const canvas = document.createElement('canvas');
                canvas.width = cw; canvas.height = ch;
                const ctx = canvas.getContext('2d');
                ctx.drawImage(img, 0, 0, cw, ch);
                const data = ctx.getImageData(0, 0, cw, ch).data;
                // the viewBox on the canvas (px)
                const vx0 = (vb.x - ex.x0) * scale, vy0 = (vb.y - ex.y0) * scale;
                const vx1 = vx0 + vb.w * scale, vy1 = vy0 + vb.h * scale;
                const out = {left: 0, top: 0, right: 0, bottom: 0};
                for (let j = 0; j < ch; j++) {
                    for (let i = 0; i < cw; i++) {
                        if (data[4 * (j * cw + i) + 3] <= 32) continue;
                        if (i < vx0) out.left = Math.max(out.left, vx0 - i);
                        if (i + 1 > vx1) out.right = Math.max(out.right, i + 1 - vx1);
                        if (j < vy0) out.top = Math.max(out.top, vy0 - j);
                        if (j + 1 > vy1) out.bottom = Math.max(out.bottom, j + 1 - vy1);
                    }
                }
                for (const side in out) out[side] /= scale;   // units
                return out;
            } catch (e) {
                return null;
            } finally {
                URL.revokeObjectURL(url);
            }
        }
        const urls = [...new Set([...document.images].map(i => i.currentSrc || i.src)
            .filter(u => /\.svg(\?|#|$)/i.test(u)))];
        for (const url of urls.slice(0, 40)) {
            const text = await read(url);
            if (!text) continue;
            window.__layoutSvg[url] = text;
            const root = new DOMParser().parseFromString(text, 'image/svg+xml').documentElement;
            if (root && root.tagName.toLowerCase() === 'svg') window.__layoutSvgInk[url] = await inkBeyond(root);
        }
    });
}


async function waitForContent(page) {
    const explicit = await page.evaluate(async () => {
        const contract = window.__lhtmlReady;
        const trusted = contract?.version === 1 && contract.trusted();
        if (trusted) await contract.ready();
        await document.fonts.ready;
        await Promise.all([...document.images].filter(img => !img.complete).map(img =>
            new Promise(resolve => { img.onload = img.onerror = resolve; })));
        return trusted && !document.querySelector('video, audio');
    });
    // Legacy apps retain their settling period; explicit readiness avoids it.
    if (!explicit)
    // let deferred scripts (KaTeX auto-render, theme scripts) finish
    await new Promise(resolve => setTimeout(resolve, 150));
}


(async () => {
    const browser = await puppeteer.launch({headless: true, args: ['--allow-file-access-from-files']});
    const page = await browser.newPage();
    await page.setViewport({width, height});
    let failures = 0;
    let events = [];
    let resources = new Set();
    page.on('request', request => resources.add(request.url()));
    page.on('pageerror', error => events.push({type: 'javascript', message: error.message}));
    page.on('requestfailed', request => events.push({type: 'request', url: request.url(),
        message: request.failure()?.errorText || 'Request failed'}));
    page.on('response', response => { if (response.status() >= 400) events.push({type: 'http',
        url: response.url(), status: response.status()}); });
    let clockScript = null;
    async function ready() {
        let timer;
        try {
            await Promise.race([Promise.all((await localFrames(page)).map(frame => waitForContent(frame))),
                new Promise((_, reject) => { timer = setTimeout(() => reject(new Error('Content readiness timeout')), 15000); })]);
        } finally { clearTimeout(timer); }
    }
    async function measure(frame, checkedFrames) {
        const layout = await frame.evaluate(extractBlocks, frame === page.mainFrame() ? rootSelector : 'body',
                                           frame === page.mainFrame() ? excludeSelector : '');
        const health = await frame.evaluate(checkedFrames => ({
            images: [...document.images].filter(i => !i.complete || !i.naturalWidth).map(i => ({type: 'image', url: i.currentSrc || i.src})),
            fonts: [...document.fonts].filter(f => f.status === 'error').map(f => ({type: 'font', family: f.family})),
            math: [...document.querySelectorAll('.katex-error')].map(e => ({type: 'math', message: e.getAttribute('title') || e.textContent})),
            video: [...document.querySelectorAll('video')].filter(v => v.error).map(v => ({type: 'video', url: v.src, message: v.error.message})),
            clock: (window.__lhtmlVerificationClock?.errors || []).map(message => ({type: 'javascript', message})),
            unchecked: [...document.querySelectorAll('iframe, canvas')]
                .filter(e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0 &&
                    !(e.tagName === 'IFRAME' && checkedFrames.includes(e.src || 'about:srcdoc')); })
                .map(e => ({type: e.tagName.toLowerCase(), url: e.src || null,
                    reason: e.tagName === 'CANVAS' ? 'Raster geometry captured; canvas semantics are not verified' : 'Frame inaccessible or not sampled'}))
        }), checkedFrames);
        const errors = [...events, ...health.images, ...health.fonts, ...health.math, ...health.video, ...health.clock];
        layout.media_samples = await frame.evaluate(() => window.__lhtmlMediaSamples || []);
        layout.render_health = {status: errors.length ? 'incomplete' : 'ready', errors, unchecked: health.unchecked};
        return layout;
    }
    async function snapshot(out, withFrames) {
        fs.mkdirSync(out, {recursive: true});
        await page.evaluate(() => document.getElementById('__layout_overlay')?.remove());
        const frames = withFrames ? (await localFrames(page)).filter(f => f !== page.mainFrame()) : [];
        const layout = await measure(page.mainFrame(), frames.map(f => f.url()));
        layout.frame_layouts = [];
        if (withImages) await page.screenshot({optimizeForSpeed: true, path: path.join(out, 'render.png'), clip: {x: 0, y: 0, width, height}});
        for (const [i, frame] of frames.entries()) {
            const handle = await frame.frameElement();
            const box = await handle.boundingBox();
            const origin = await handle.evaluate(el => el.closest('[data-lhtml-src]')?.getAttribute('data-lhtml-src') || null);
            await loadSvgImages(frame);
            const inner = await measure(frame, []);
            inner.source = frame.url();
            const id = 'f' + (i + 1), folder = path.join(out, 'frames', id);
            fs.mkdirSync(folder, {recursive: true});
            if (withImages) await handle.screenshot({optimizeForSpeed: true, path: path.join(folder, 'render.png')});
            await handle.dispose();
            layout.frame_layouts.push({id, url: frame.url(), box, origin, layout: inner});
        }
        if (withImages && images !== 'render') {
            const clip = {x: 0, y: 0, width, height};
            await page.evaluate(drawOverlay, layout.subblocks, PALETTE, false);
            await page.screenshot({optimizeForSpeed: true, path: path.join(out, 'internal-overlay.png'), clip});
            await page.evaluate(drawOverlay, layout.blocks, PALETTE, false);
            await page.screenshot({optimizeForSpeed: true, path: path.join(out, 'overlay.png'), clip});
            await page.evaluate(drawOverlay, layout.blocks, PALETTE, true);
            await page.screenshot({optimizeForSpeed: true, path: path.join(out, 'blocks.png'), clip});
            await page.evaluate(() => document.getElementById('__layout_overlay')?.remove());
        }
        return layout;
    }
    for (const [index, entry] of pages.entries()) {
        // progress on stdout, read by layout_report.py: "progress <done> <total> <page>"
        console.log(`progress ${index} ${pages.length} ${entry.name || entry.html}`);
        events = [];
        resources = new Set();
        try {
            fs.mkdirSync(entry.out, {recursive: true});
            if (clockScript) { await page.removeScriptToEvaluateOnNewDocument(clockScript.identifier); clockScript = null; }
            if (entry.interactive?.enabled) clockScript = await page.evaluateOnNewDocument(interactive().installClock);
            // outputs of a previous --verify (agent extension): written again by --verify only
            for (const name of ['states', 'frames', 'issues', 'verification.json', 'changes.json'])
                fs.rmSync(path.join(entry.out, name), {recursive: true, force: true});
            // pages with streaming media (autoplay videos, iframes) never become
            // idle: wait for the load event, then for a short network idle
            await page.goto('file://' + path.resolve(entry.html), {waitUntil: 'load', timeout: 60000});
            const trustedFrames = await Promise.all((await localFrames(page)).map(frame =>
                frame.evaluate(() => window.__lhtmlReady?.version === 1 && window.__lhtmlReady.trusted() && !document.querySelector('video, audio') && ![...document.querySelectorAll('iframe')].some(el => /^https?:/.test(el.src)))));
            if (!trustedFrames.length || trustedFrames.some(trusted => !trusted))
                await page.waitForNetworkIdle({idleTime: 500, timeout: 5000}).catch(() => {});
            await ready();
            await freezeMedia(page);
            await loadSvgImages(page);
            const options = entry.interactive || {enabled: false};
            // --verify (agent extension) measures the local frames, with or without interactive states
            const withFrames = entry.interactive !== undefined;
            if (withFrames) {
                for (const frame of await localFrames(page)) {
                    if (frame !== page.mainFrame()) await freezeMedia(frame);
                }
            }
            if (options.enabled) await interactive().advance(page, 0);
            const layout = await snapshot(entry.out, withFrames);
            if (options.enabled) {
                const discovery = await interactive().discover(page, options);
                layout.interactive = {...discovery, enabled: true, states: [], exhaustive: false,
                    capabilities: {raf_clock: true, css_timeline: true, video_seek: true, gif_frames: true,
                        native_timers: false, random_seed: false, canvas_semantics: false}};
                delete layout.interactive.plans;
                for (const plan of discovery.plans) {
                    const out = path.join(entry.out, 'states', plan.name);
                    const state = {id: plan.name, plan, journal: [], status: 'failed'};
                    try {
                        events = [];
                        await page.goto('file://' + path.resolve(entry.html), {waitUntil: 'load', timeout: 30000});
                        await ready();
                        for (const frame of await localFrames(page)) await freezeMedia(frame);
                        await interactive().advance(page, 0);
                        state.journal = await interactive().apply(page, plan, state.journal, ready);
                        await loadSvgImages(page);
                        state.layout = await snapshot(out, true);
                        state.status = 'measured';
                    } catch (error) {
                        state.error = {type: 'interactive_state', message: error.message};
                        state.render_health = {status: 'failed', errors: [state.error], unchecked: []};
                    }
                    layout.interactive.states.push(state);
                }
            }
            layout.resources = [...resources].filter(url => !url.startsWith('data:'));
            fs.writeFileSync(path.join(entry.out, 'layout.json'), JSON.stringify(layout, null, 1));

        } catch (e) {
            failures += 1;
            console.error(`layout_measure: ${entry.html}: ${e.message}`);
        }
    }
    console.log(`progress ${pages.length} ${pages.length} done`);
    await browser.close();
    process.exit(0);
})();
