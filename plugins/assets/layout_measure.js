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

    function unionRects(rects) {
        let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
        for (const r of rects) {
            if (r.width <= 0 || r.height <= 0) continue;
            x0 = Math.min(x0, r.left); y0 = Math.min(y0, r.top);
            x1 = Math.max(x1, r.right); y1 = Math.max(y1, r.bottom);
        }
        if (x0 === Infinity) return null;
        return {x: round(x0 + scrollX), y: round(y0 + scrollY), w: round(x1 - x0), h: round(y1 - y0)};
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

    // Ink extent of an element: its text (glyph boxes), media, and the
    // descendants that paint a background or a border. Invisible layout
    // boxes (full-width blocks, struts) are ignored. null if nothing visible.
    function inkRect(el) {
        const rects = [];
        if (MEDIA.has(el.tagName) || paints(getComputedStyle(el))) rects.push(el.getBoundingClientRect());
        const range = document.createRange();
        const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
        let node, count = 0;
        while ((node = walker.nextNode()) && count < 5000) {
            if (!node.textContent.trim() || isHiddenText(node.parentElement)) continue;
            range.selectNodeContents(node);
            for (const r of range.getClientRects()) if (r.width > 1 && r.height > 1) rects.push(r);
            count++;
        }
        const descendants = el.getElementsByTagName('*');
        for (let i = 0; i < descendants.length && i < 3000; i++) {
            const d = descendants[i];
            const cs = getComputedStyle(d);
            if (cs.display === 'none' || cs.visibility === 'hidden') continue;
            if (MEDIA.has(d.tagName) || paints(cs)) rects.push(d.getBoundingClientRect());
        }
        return unionRects(rects);
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
            const r = img.getBoundingClientRect();
            return {src: basename(img.getAttribute('src')), w: round(r.width), h: round(r.height),
                    natural_w: img.naturalWidth, natural_h: img.naturalHeight};
        });
    }

    function describe(el) {
        const cs = getComputedStyle(el);
        const box = el.getBoundingClientRect();
        const visual = inkRect(el);
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
            box: {x: round(box.left + scrollX), y: round(box.top + scrollY), w: round(box.width), h: round(box.height)},
            visual,
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
        const visual = unionRects([...range.getClientRects()].filter(r => r.width > 1 && r.height > 1));
        if (!visual) return;
        const parentStyle = getComputedStyle(root);
        blocks.push({kind: 'text', signature: `text "${excerpt(nodes.map(n => n.textContent).join(' '))}"`,
                     box: visual, visual, position: 'static', margin: [0, 0, 0, 0],
                     font_size: round(parseFloat(parentStyle.fontSize) || 0), overflow: 'visible',
                     scroll: null, media: []});
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
    const area = br.width > 0 && br.height > 0 && br.height <= innerHeight ? {
        x: round(br.left + px(bcs.borderLeftWidth)),
        y: round(br.top + px(bcs.borderTopWidth)),
        w: round(br.width - px(bcs.borderLeftWidth) - px(bcs.borderRightWidth)),
        h: round(br.height - px(bcs.borderTopWidth) - px(bcs.borderBottomWidth)),
    } : {x: 0, y: 0, w: innerWidth, h: innerHeight};
    return {root: document.querySelector(rootSelector) ? rootSelector : 'body', title: document.title,
            viewport: {w: innerWidth, h: innerHeight}, area, blocks,
            scrolling: document.documentElement.scrollHeight > innerHeight + 1};
}


// Runs in the page: draws numbered outlines (filled=false) or solid
// rectangles on a white background (filled=true) above the content.
function drawOverlay(blocks, palette, filled) {
    const old = document.getElementById('__layout_overlay');
    if (old) old.remove();
    const layer = document.createElement('div');
    layer.id = '__layout_overlay';
    Object.assign(layer.style, {position: 'fixed', left: '0', top: '0', width: '100vw', height: '100vh',
                                zIndex: '2147483647', pointerEvents: 'none',
                                background: filled ? 'white' : 'transparent'});
    for (const b of blocks) {
        if (b.kind === 'spacer') continue;
        const r = b.visual || b.box;
        const color = palette[(b.id - 1) % palette.length];
        const d = document.createElement('div');
        Object.assign(d.style, {position: 'absolute', left: (r.x - scrollX) + 'px', top: (r.y - scrollY) + 'px',
                                width: r.w + 'px', height: r.h + 'px', boxSizing: 'border-box',
                                border: `3px solid ${color}`,
                                background: filled ? color : 'transparent', opacity: filled ? '0.7' : '1'});
        const label = document.createElement('div');
        label.textContent = '#' + b.id;
        Object.assign(label.style, {position: 'absolute', left: '0', top: '0', padding: '2px 6px',
                                    font: 'bold 22px sans-serif', color: 'white', background: color});
        d.appendChild(label);
        layer.appendChild(d);
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
