'use strict';
// Comments on the render (generate.py --serve, lib/feedback.py): the button
// 💬 (or the key c) switches the comment mode; a click on a block then opens a
// form, and the comment is sent to the local server with the source of the
// block (data-lhtml-src="file:line" of the source map). The open comments of the
// page are shown as numbered pins; a click on a pin shows it, "Done" closes it.
(function () {
    const URL = '/__feedback/';
    const HEADERS = {'Content-Type': 'application/json', 'X-Feedback': '1'};
    const page = location.pathname;
    let active = false, hovered = null;

    // the slides theme scales <html> (presentation_resize_page.js): the layer
    // is in its coordinates, in CSS px of the page
    const html = document.documentElement;
    const zoom = () => html.getBoundingClientRect().width / (html.offsetWidth || 1) || 1;
    function pageRect(el) {
        const r = el.getBoundingClientRect(), h = html.getBoundingClientRect(), z = zoom();
        return {x: Math.round((r.left - h.left) / z), y: Math.round((r.top - h.top) / z),
                w: Math.round(r.width / z), h: Math.round(r.height / z)};
    }

    const layer = document.createElement('div');
    layer.id = '__feedback';
    Object.assign(layer.style, {position: 'absolute', left: '0', top: '0', width: '0', height: '0',
                                zIndex: '2147483646', font: '16px sans-serif'});
    html.appendChild(layer);

    const style = document.createElement('style');
    style.textContent = `
        #__feedback button { font: 16px sans-serif; cursor: pointer; }
        #__feedback .fb-toggle { position: absolute; left: 12px; top: 1030px; padding: 4px 8px;
            border: 1px solid #888; border-radius: 6px; background: white; opacity: 0.6; }
        #__feedback .fb-toggle.on { background: #ffd54f; opacity: 1; }
        #__feedback .fb-pin { position: absolute; min-width: 26px; height: 26px; border-radius: 13px;
            background: #e53935; color: white; text-align: center; line-height: 26px; cursor: pointer;
            font-weight: bold; box-shadow: 0 1px 4px rgba(0,0,0,0.4); }
        #__feedback .fb-box { position: absolute; width: 420px; padding: 10px; background: white;
            border: 2px solid #e53935; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.3); }
        #__feedback .fb-box textarea { width: 100%; height: 110px; box-sizing: border-box; font: 16px sans-serif; }
        #__feedback .fb-box .fb-src { color: #666; font-size: 13px; margin-bottom: 6px; word-break: break-all; }
        #__feedback .fb-box .fb-actions { text-align: right; margin-top: 6px; }
        .__fb-hover { outline: 3px dashed #e53935 !important; outline-offset: 2px; cursor: crosshair !important; }`;
    document.head.appendChild(style);

    const toggle = document.createElement('button');
    toggle.className = 'fb-toggle';
    toggle.title = 'Comment a block (key c)';
    toggle.textContent = '💬';
    layer.appendChild(toggle);

    function setActive(on) {
        active = on;
        toggle.classList.toggle('on', on);
        if (!on && hovered) { hovered.classList.remove('__fb-hover'); hovered = null; }
    }
    toggle.addEventListener('click', (e) => { e.stopPropagation(); setActive(!active); });

    const blockOf = (el) => el.closest('[data-lhtml-src]') || el.closest('body > *');
    const describe = (el) => (el.tagName.toLowerCase() + ' ' + (el.innerText || '').replace(/\s+/g, ' ').trim()).slice(0, 120);

    document.addEventListener('mouseover', (e) => {
        if (!active || layer.contains(e.target)) return;
        const block = blockOf(e.target);
        if (hovered && hovered !== block) hovered.classList.remove('__fb-hover');
        hovered = block;
        if (block) block.classList.add('__fb-hover');
    });
    document.addEventListener('click', (e) => {
        if (!active || layer.contains(e.target)) return;
        const block = blockOf(e.target);
        if (!block) return;
        e.preventDefault();
        e.stopPropagation();
        openForm(block);
    }, true);
    document.addEventListener('keydown', (e) => {
        if (e.target.closest && e.target.closest('#__feedback')) { e.stopPropagation(); return; }
        if (e.key === 'c' && !e.ctrlKey && !e.metaKey && !e.altKey) setActive(!active);
        if (e.key === 'Escape') { closeBox(); setActive(false); }
    }, true);

    let box = null;
    function closeBox() { if (box) { box.remove(); box = null; } }
    function placeBox(rect) {
        box.style.left = Math.max(10, Math.min(rect.x, 1920 - 450)) + 'px';
        box.style.top = Math.max(10, Math.min(rect.y + rect.h + 8, 1080 - 230)) + 'px';
    }

    function openForm(block) {
        closeBox();
        const rect = pageRect(block);
        const src = block.getAttribute('data-lhtml-src');
        box = document.createElement('div');
        box.className = 'fb-box';
        box.innerHTML = '<div class="fb-src"></div><textarea placeholder="Comment"></textarea>'
            + '<div class="fb-actions"><button class="fb-cancel">Cancel</button> <button class="fb-save">Save</button></div>';
        box.querySelector('.fb-src').textContent = src || '(source unknown)';
        layer.appendChild(box);
        placeBox(rect);
        const text = box.querySelector('textarea');
        text.focus();
        box.querySelector('.fb-cancel').onclick = closeBox;
        box.querySelector('.fb-save').onclick = async () => {
            if (!text.value.trim()) return;
            const response = await fetch(URL + 'comment', {method: 'POST', headers: HEADERS,
                body: JSON.stringify({page, src, block: describe(block), rect, comment: text.value})});
            if (response.ok) { closeBox(); setActive(false); loadPins(); }
            else box.querySelector('.fb-src').textContent = 'Not saved: ' + await response.text();
        };
    }

    function showComment(c, pin) {
        closeBox();
        box = document.createElement('div');
        box.className = 'fb-box';
        box.innerHTML = '<div class="fb-src"></div><div class="fb-text"></div>'
            + '<div class="fb-actions"><button class="fb-cancel">Close</button> <button class="fb-done">Done</button></div>';
        box.querySelector('.fb-src').textContent = `${c.id}. ${c.src || '(source unknown)'} · ${c.time}`;
        box.querySelector('.fb-text').textContent = c.comment;
        layer.appendChild(box);
        placeBox({x: parseInt(pin.style.left), y: parseInt(pin.style.top), w: 0, h: 26});
        box.querySelector('.fb-cancel').onclick = closeBox;
        box.querySelector('.fb-done').onclick = async () => {
            await fetch(URL + 'resolve', {method: 'POST', headers: HEADERS, body: JSON.stringify({id: c.id})});
            closeBox();
            loadPins();
        };
    }

    async function loadPins() {
        layer.querySelectorAll('.fb-pin').forEach(p => p.remove());
        let comments = [];
        try {
            comments = await (await fetch(URL + 'comments?page=' + encodeURIComponent(page))).json();
        } catch (e) { return; }
        for (const c of comments.filter(c => c.status === 'open')) {
            const block = c.src ? document.querySelector(`[data-lhtml-src="${CSS.escape(c.src)}"]`) : null;
            const rect = block ? pageRect(block) : c.rect;
            const pin = document.createElement('div');
            pin.className = 'fb-pin';
            pin.textContent = c.id;
            pin.title = c.comment;
            pin.style.left = Math.max(0, rect.x + rect.w - 13) + 'px';
            pin.style.top = Math.max(0, rect.y - 13) + 'px';
            pin.onclick = (e) => { e.stopPropagation(); showComment(c, pin); };
            layer.appendChild(pin);
        }
    }
    loadPins();
})();
