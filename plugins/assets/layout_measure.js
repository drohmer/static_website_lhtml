'use strict';

// Measure the layout of generated pages in headless Chrome (puppeteer).
//
// Usage:
//   node layout_measure.js --input=pages.json [--root=body]
//        [--exclude="nav, footer"] [--width=1920] [--height=1080] [--images=1]
//
// pages.json: [{"html": "/abs/path/index.html", "out": "/abs/output/dir"}, ...]
// For each page, writes <out>/layout.json and, if images=1, <out>/overlay.png
// (real render + numbered outlines) and <out>/blocks.png (one solid
// rectangle per block).

const fs = require('fs');
const path = require('path');
const puppeteer = require('puppeteer');
const args = require('minimist')(process.argv.slice(2));

const pages = JSON.parse(fs.readFileSync(args.input, 'utf-8'));
const rootSelector = args.root || 'body';
const excludeSelector = args.exclude || 'nav, footer';
const width = parseInt(args.width || 1920);
const height = parseInt(args.height || 1080);
const withImages = String(args.images || '1') !== '0';

const PALETTE = ['#e6194b', '#3cb44b', '#4363d8', '#f58231', '#911eb4', '#42d4f4',
                 '#f032e6', '#bfef45', '#469990', '#9a6324', '#800000', '#808000',
                 '#000075', '#fabed4', '#ffd8b1', '#aaffc3'];


// Runs in the page: extracts the top-level blocks under the content root.
function extractBlocks(rootSelector, excludeSelector) {
    const MEDIA = new Set(['IMG', 'VIDEO', 'SVG', 'CANVAS', 'IFRAME', 'svg']);
    const root = document.querySelector(rootSelector) || document.body;

    const round = (v) => Math.round(v);
    const clean = (s) => (s || '').replace(/\s+/g, ' ').trim();
    // cut by code points (not UTF-16 units) so that surrogate pairs (math symbols) stay whole
    const excerpt = (s, n = 60) => { const c = Array.from(clean(s)); return c.length > n ? c.slice(0, n).join('') + '…' : c.join(''); };
    const basename = (src) => (src || '').split('/').pop().split('?')[0];

    // Rectangles are {x, y, w, h} in page coordinates (CSS px)
    function toRect(r) {
        return {x: round(r.left + scrollX), y: round(r.top + scrollY), w: round(r.width), h: round(r.height)};
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

    // Merge the fragments of a same line of text (vertical overlap of at
    // least half their height, horizontal gap below `gap`) and drop the
    // rectangles contained in another one.
    function mergeRects(rects, gap) {
        let list = rects.filter(r => r.w > 1 && r.h > 1).map(r => ({...r}));
        let merged = true;
        while (merged) {
            merged = false;
            outer:
            for (let i = 0; i < list.length; i++) {
                for (let j = i + 1; j < list.length; j++) {
                    const a = list[i], b = list[j];
                    const overlapY = Math.min(a.y + a.h, b.y + b.h) - Math.max(a.y, b.y);
                    const gapX = Math.max(a.x, b.x) - Math.min(a.x + a.w, b.x + b.w);
                    if (contains(a, b) || contains(b, a)
                        || (overlapY >= 0.5 * Math.min(a.h, b.h) && gapX <= gap)) {
                        list[i] = unionRects([a, b]);
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

    // Rectangle of the drawn content of an image: pixels that are neither
    // transparent nor of the background color (taken from the corners).
    // The whole image if it cannot be analysed or has no uniform background.
    function imageContentRect(img) {
        const box = toRect(img.getBoundingClientRect());
        if (img.tagName !== 'IMG' || !img.complete || !img.naturalWidth) return box;
        const scale = Math.min(1, 200 / Math.max(img.naturalWidth, img.naturalHeight));
        const cw = Math.max(1, Math.round(img.naturalWidth * scale));
        const ch = Math.max(1, Math.round(img.naturalHeight * scale));
        let data;
        try {
            const canvas = document.createElement('canvas');
            canvas.width = cw; canvas.height = ch;
            const ctx = canvas.getContext('2d');
            ctx.drawImage(img, 0, 0, cw, ch);
            data = ctx.getImageData(0, 0, cw, ch).data;
        } catch (e) {
            return box;
        }
        const px = (x, y) => data.subarray(4 * (y * cw + x), 4 * (y * cw + x) + 4);
        const corners = [px(0, 0), px(cw - 1, 0), px(0, ch - 1), px(cw - 1, ch - 1)];
        const transparent = corners.some(c => c[3] < 16);
        const bg = corners[0];
        const close = (c) => Math.max(Math.abs(c[0] - bg[0]), Math.abs(c[1] - bg[1]), Math.abs(c[2] - bg[2])) <= 24;
        if (!transparent && !corners.every(close)) return box;
        const isContent = transparent ? (c) => c[3] >= 16 : (c) => c[3] >= 16 && !close(c);
        let x0 = cw, y0 = ch, x1 = -1, y1 = -1;
        for (let y = 0; y < ch; y++) {
            for (let x = 0; x < cw; x++) {
                if (isContent(px(x, y))) {
                    if (x < x0) x0 = x; if (x > x1) x1 = x;
                    if (y < y0) y0 = y; if (y > y1) y1 = y;
                }
            }
        }
        if (x1 < 0) return box;
        const sx = box.w / cw, sy = box.h / ch;
        return {x: round(box.x + x0 * sx), y: round(box.y + y0 * sy),
                w: round((x1 - x0 + 1) * sx), h: round((y1 - y0 + 1) * sy)};
    }

    function inkOf(el) {
        // ink rectangle of an element that is itself drawn (media, background, border)
        if (el.tagName === 'IMG') return imageContentRect(el);
        return toRect(el.getBoundingClientRect());
    }

    // Ink of an element: its text (lines), media (images trimmed to their
    // drawn content) and the descendants that paint a background or a
    // border, as a list of rectangles. Invisible layout boxes (full-width
    // blocks, struts) are ignored. Empty list if nothing is drawn.
    function inkRects(el, fontSize) {
        const rects = [];
        if (MEDIA.has(el.tagName) || paints(getComputedStyle(el))) rects.push(inkOf(el));
        const range = document.createRange();
        const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
        let node, count = 0;
        while ((node = walker.nextNode()) && count < 5000) {
            if (!node.textContent.trim() || isHiddenText(node.parentElement)) continue;
            range.selectNodeContents(node);
            for (const r of range.getClientRects()) rects.push(toRect(r));
            count++;
        }
        const descendants = el.getElementsByTagName('*');
        for (let i = 0; i < descendants.length && i < 3000; i++) {
            const d = descendants[i];
            const cs = getComputedStyle(d);
            if (cs.display === 'none' || cs.visibility === 'hidden') continue;
            if (MEDIA.has(d.tagName) || paints(cs)) rects.push(inkOf(d));
        }
        return mergeRects(rects, Math.max(8, fontSize));
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
        if (!cs.display.startsWith('inline') || cs.display !== 'inline') return false;
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

    function mediaInfo(el) {
        const imgs = el.tagName === 'IMG' ? [el] : [...el.querySelectorAll('img')];
        return imgs.slice(0, 6).map(img => {
            const box = toRect(img.getBoundingClientRect());
            return {src: basename(img.getAttribute('src')), w: box.w, h: box.h,
                    natural_w: img.naturalWidth, natural_h: img.naturalHeight,
                    box, content: imageContentRect(img)};
        });
    }

    function describe(el) {
        const cs = getComputedStyle(el);
        const box = el.getBoundingClientRect();
        const fontSize = parseFloat(cs.fontSize) || 16;
        const ink = inkRects(el, fontSize);
        const visual = unionRects(ink);
        const media = mediaInfo(el);
        let signature = el.tagName.toLowerCase();
        if (el.className && typeof el.className === 'string') signature += '.' + el.className.trim().split(/\s+/).join('.');
        if (el.getAttribute('style')) signature += `[${clean(el.getAttribute('style'))}]`;
        const text = excerpt(el.innerText);
        if (text) signature += ` "${text}"`;
        if (media.length) signature += ' ' + media.map(m => m.src).join(', ');
        return {
            kind: visual ? kindOf(el) : 'spacer',
            signature,
            box: toRect(box),
            visual,
            ink,
            position: cs.position,
            margin: ['Top', 'Right', 'Bottom', 'Left'].map(s => round(parseFloat(cs['margin' + s]) || 0)),
            font_size: round(parseFloat(cs.fontSize) || 0),
            overflow: cs.overflow,
            scroll: {w: el.scrollWidth, h: el.scrollHeight, client_w: el.clientWidth, client_h: el.clientHeight},
            media,
        };
    }

    const blocks = [];
    let run = [];
    function flushRun() {
        const nodes = run; run = [];
        if (!nodes.some(n => clean(n.textContent))) return;
        const range = document.createRange();
        range.setStartBefore(nodes[0]);
        range.setEndAfter(nodes[nodes.length - 1]);
        const fontSize = parseFloat(getComputedStyle(root).fontSize) || 16;
        const ink = mergeRects([...range.getClientRects()].map(toRect), Math.max(8, fontSize));
        const visual = unionRects(ink);
        if (!visual) return;
        blocks.push({kind: 'text', signature: `text "${excerpt(nodes.map(n => n.textContent).join(' '))}"`,
                     box: visual, visual, ink, position: 'static', margin: [0, 0, 0, 0],
                     font_size: round(fontSize), overflow: 'visible', scroll: null, media: []});
    }
    for (const node of root.childNodes) {
        if (node.nodeType === Node.TEXT_NODE) { run.push(node); continue; }
        if (node.nodeType !== Node.ELEMENT_NODE) continue;
        if (['SCRIPT', 'STYLE', 'NOSCRIPT', 'TEMPLATE'].includes(node.tagName)
            || node.id === '__layout_overlay' || (excludeSelector && node.matches(excludeSelector))) continue;
        if (isInline(node)) { run.push(node); continue; }
        flushRun();
        if (isVisible(node)) blocks.push(describe(node));
    }
    flushRun();
    blocks.forEach((b, i) => { b.id = i + 1; });

    // usable slide area: inside of the frame drawn by the body (slides
    // theme), i.e. its padding box; the viewport if the body draws no frame
    const body = document.body;
    const bcs = getComputedStyle(body);
    const br = body.getBoundingClientRect();
    const px = (v) => parseFloat(v) || 0;
    // a slide has a frame (body) that fits in the viewport, even when its
    // content overflows; a web page has a body taller than the viewport
    const framed = br.width > 0 && br.height > 0 && br.height <= innerHeight;
    const area = framed ? {
        x: round(br.left + px(bcs.borderLeftWidth)),
        y: round(br.top + px(bcs.borderTopWidth)),
        w: round(br.width - px(bcs.borderLeftWidth) - px(bcs.borderRightWidth)),
        h: round(br.height - px(bcs.borderTopWidth) - px(bcs.borderBottomWidth)),
    } : {x: 0, y: 0, w: innerWidth, h: innerHeight};
    return {root: document.querySelector(rootSelector) ? rootSelector : 'body', title: document.title,
            viewport: {w: innerWidth, h: innerHeight}, area, blocks,
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
        const v = b.visual || b.box;
        const label = rectDiv({x: v.x, y: v.y, w: 0, h: 0}, {width: 'auto', height: 'auto', padding: '2px 6px',
                              font: 'bold 22px sans-serif', color: 'white', background: color});
        label.textContent = '#' + b.id;
    }
    document.body.appendChild(layer);
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
    for (const entry of pages) {
        try {
            fs.mkdirSync(entry.out, {recursive: true});
            await page.goto('file://' + path.resolve(entry.html), {waitUntil: 'networkidle0', timeout: 60000});
            await waitForContent(page);
            const layout = await page.evaluate(extractBlocks, rootSelector, excludeSelector);
            fs.writeFileSync(path.join(entry.out, 'layout.json'), JSON.stringify(layout, null, 1));
            if (withImages) {
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
    await browser.close();
    process.exit(failures ? 1 : 0);
})();
