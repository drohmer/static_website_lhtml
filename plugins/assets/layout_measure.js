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
    function inkRects(el, fontSize, stats) {
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
            if (!node.textContent.trim() || isHiddenText(node.parentElement)) continue;
            if (stats) countText(node, stats);
            range.selectNodeContents(node);
            for (const r of range.getClientRects()) rects.push(toRect(r, 'text'));
            count++;
        }
        const descendants = el.getElementsByTagName('*');
        for (let i = 0; i < descendants.length && i < 3000; i++) {
            const cs = getComputedStyle(descendants[i]);
            if (cs.display === 'none' || cs.visibility === 'hidden') continue;
            own(descendants[i]);
        }
        return mergeRects(rects, (t) => t === 'text' ? Math.max(8, fontSize) : 0);
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

    function mediaInfo(el) {
        const items = ['IMG', 'VIDEO'].includes(el.tagName) ? [el] : [...el.querySelectorAll('img, video')];
        return items.slice(0, 6).map(img => {
            const box = toRect(img.getBoundingClientRect());
            const src = sourceOf(img);
            delete box.t;
            const content = img.tagName === 'IMG' ? {...imageShape(img).content} : {...box};
            delete content.t;
            return {src: basename(src), w: box.w, h: box.h, tag: img.tagName.toLowerCase(),
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
        while ((node = walker.nextNode())) {
            if (!node.textContent.trim() || isHiddenText(node.parentElement)) continue;
            const owner = node.parentElement.closest('li, h1, h2, h3, h4, h5, h6, .credit');
            if (owner !== el) continue;
            range.selectNodeContents(node);
            rects.push(...[...range.getClientRects()].filter(r => r.width > 0));
        }
        const lines = [];
        for (const r of rects.sort((a, b) => a.top - b.top || a.left - b.left)) {
            const line = lines.find(l => Math.abs(l.mid - (r.top + r.height / 2)) < r.height / 2);
            if (line) { line.x0 = Math.min(line.x0, r.left); line.x1 = Math.max(line.x1, r.right); }
            else lines.push({mid: r.top + r.height / 2, x0: r.left, x1: r.right});
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

    function describe(el) {
        const cs = getComputedStyle(el);
        const box = toRect(el.getBoundingClientRect());
        delete box.t;
        const fontSize = parseFloat(cs.fontSize) || 16;
        const stats = newStats();
        const ink = inkRects(el, fontSize, stats);
        const visual = unionRects(ink);
        const media = mediaInfo(el);
        elementStats(el, stats);
        let signature = el.tagName.toLowerCase();
        if (el.className && typeof el.className === 'string') signature += '.' + el.className.trim().split(/\s+/).join('.');
        if (el.getAttribute('style')) signature += `[${clean(el.getAttribute('style'))}]`;
        const text = excerpt(el.innerText);
        if (text) signature += ` "${text}"`;
        if (media.length) signature += ' ' + media.map(m => m.src).join(', ');
        return {
            kind: visual ? kindOf(el) : 'spacer',
            signature,
            box,
            visual,
            ink,
            position: cs.position,
            text_align: cs.textAlign,
            margin: ['Top', 'Right', 'Bottom', 'Left'].map(s => round(parseFloat(cs['margin' + s]) || 0)),
            font_size: round(fontSize),
            overflow: cs.overflow,
            scroll: {w: el.scrollWidth, h: el.scrollHeight, client_w: el.clientWidth, client_h: el.clientHeight},
            media,
            wrapped: wrappedItems(el),
            rows: figureRows(el),
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
        const block = {kind: 'text', signature: `text "${excerpt(nodes.map(n => n.textContent).join(' '))}"`,
                       box: visual, visual, ink, position: 'static', margin: [0, 0, 0, 0],
                       text_align: getComputedStyle(root).textAlign,
                       font_size: round(fontSize), overflow: 'visible', scroll: null, media: [],
                       wrapped: [], rows: [],
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
            const block = describe(node);
            blocks.push(block);
            blockOf.set(node, block);
        }
    }
    flushRun();
    blocks.forEach((b, i) => { b.id = i + 1; });

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
            viewport: {w: innerWidth, h: innerHeight}, area, blocks, reserved,
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
    for (const b of blocks) {
        if (b.kind === 'spacer') continue;
        const color = palette[(b.id - 1) % palette.length];
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
        if (!('ImageDecoder' in window)) return;
        const load = (url) => new Promise((resolve, reject) => {      // fetch() does not read file://
            const xhr = new XMLHttpRequest();
            xhr.open('GET', url);
            xhr.responseType = 'arraybuffer';
            xhr.onload = () => resolve(xhr.response);
            xhr.onerror = reject;
            xhr.send();
        });
        for (const img of [...document.images].filter(i => /\.gif(\?|#|$)/i.test(i.currentSrc || i.src))) {
            try {
                const decoder = new ImageDecoder({data: await load(img.currentSrc || img.src), type: 'image/gif'});
                const {image} = await decoder.decode({frameIndex: 0});
                const canvas = document.createElement('canvas');
                canvas.width = image.displayWidth; canvas.height = image.displayHeight;
                canvas.getContext('2d').drawImage(image, 0, 0);
                image.close();
                img.dataset.layoutSrc = img.getAttribute('src');
                await new Promise(resolve => { img.onload = img.onerror = resolve; img.src = canvas.toDataURL(); });
            } catch (e) { /* the GIF as it is */ }
        }
    });
}


async function waitForContent(page) {
    await page.evaluate(async () => {
        await document.fonts.ready;
        await Promise.all([...document.images].filter(img => !img.complete).map(img =>
            new Promise(resolve => { img.onload = img.onerror = resolve; })));
    });
    // let deferred scripts (KaTeX auto-render, theme scripts) finish
    await new Promise(resolve => setTimeout(resolve, 150));
}


(async () => {
    const browser = await puppeteer.launch({headless: true, args: ['--allow-file-access-from-files']});
    const page = await browser.newPage();
    await page.setViewport({width, height});
    let failures = 0;
    for (const [index, entry] of pages.entries()) {
        // progress on stdout, read by layout_report.py: "progress <done> <total> <page>"
        console.log(`progress ${index} ${pages.length} ${entry.name || entry.html}`);
        try {
            fs.mkdirSync(entry.out, {recursive: true});
            // pages with streaming media (autoplay videos, iframes) never become
            // idle: wait for the load event, then for a short network idle
            await page.goto('file://' + path.resolve(entry.html), {waitUntil: 'load', timeout: 60000});
            await page.waitForNetworkIdle({idleTime: 500, timeout: 5000}).catch(() => {});
            await waitForContent(page);
            await freezeMedia(page);
            const layout = await page.evaluate(extractBlocks, rootSelector, excludeSelector);
            fs.writeFileSync(path.join(entry.out, 'layout.json'), JSON.stringify(layout, null, 1));
            if (withImages) {
                const clip = {x: 0, y: 0, width, height};
                await page.screenshot({path: path.join(entry.out, 'render.png'), clip});
            }
            if (withImages && images !== 'render') {
                const clip = {x: 0, y: 0, width, height};
                await page.evaluate(drawOverlay, layout.blocks, PALETTE, false);
                await page.screenshot({path: path.join(entry.out, 'overlay.png'), clip});
                await page.evaluate(drawOverlay, layout.blocks, PALETTE, true);
                await page.screenshot({path: path.join(entry.out, 'blocks.png'), clip});
            }
        } catch (e) {
            failures += 1;
            console.error(`layout_measure: ${entry.html}: ${e.message}`);
        }
    }
    console.log(`progress ${pages.length} ${pages.length} done`);
    await browser.close();
    process.exit(failures ? 1 : 0);
})();
