'use strict';
// A verification-only rAF clock is installed before scripts in every frame.
// Native timers, randomness and arbitrary WebGL state are not virtualized.
function installClock() {
    const nativeRAF = window.requestAnimationFrame.bind(window);
    let time = 0, next = 1;
    const callbacks = new Map();
    window.requestAnimationFrame = callback => { const id = next++; callbacks.set(id, callback); return id; };
    window.cancelAnimationFrame = id => callbacks.delete(id);
    const errors = [];
    try { Object.defineProperty(performance, 'now', {value: () => time}); } catch (_) { /* capability recorded below */ }
    window.__lhtmlVerificationClock = {
        pending: () => callbacks.size,
        presentationReady: () => new Promise((resolve, reject) => {
            const timer = setTimeout(() => reject(new Error('Video presentation timeout')), 4000);
            nativeRAF(() => nativeRAF(() => { clearTimeout(timer); resolve(); }));
        }),
        errors,
        advance(target) {
            const steps = Math.max(1, Math.min(320, Math.ceil((target - time) / 16)));
            const start = time;
            for (let i = 1; i <= steps; i++) {
                time = start + (target - start) * i / steps;
                const pending = [...callbacks.values()]; callbacks.clear();
                for (const callback of pending) {
                    try { callback(time); } catch (error) { errors.push(error.message); }
                }
            }
        }
    };
}

const {localFrames} = require('../../plugins/assets/frames');

async function advance(page, time, fraction = null) {
    for (const frame of await localFrames(page)) {
        await frame.evaluate(async ({time, fraction}) => {
            window.__lhtmlVerificationClock?.advance(time);
            window.__lhtmlMediaSamples = [];
            for (const a of document.getAnimations()) {
                a.pause();
                const t = a.effect.getComputedTiming();
                const duration = Number.isFinite(t.activeDuration) ? t.activeDuration : t.duration;
                a.currentTime = fraction !== null && Number.isFinite(duration)
                    ? (t.delay || 0) + duration * fraction : time;
            }
            window.__lhtmlMediaSamples.push({type: 'raf', time_ms: time, pending: window.__lhtmlVerificationClock?.pending() || 0});
            await Promise.all([...document.querySelectorAll('video')].map(v => new Promise((resolve, reject) => {
                v.pause();
                if (!Number.isFinite(v.duration) || v.duration <= 0 || v.readyState < 1) {
                    if (fraction !== null) reject(new Error('Video metadata unavailable: ' + v.src)); else resolve();
                    return;
                }
                const target = Math.min(Math.max(0, v.duration - .01), fraction !== null ? v.duration * fraction : time / 1000);
                window.__lhtmlMediaSamples.push({type: 'video', url: v.src, time: target, duration: v.duration});
                if (Math.abs(v.currentTime - target) < .001 && v.readyState >= 2) { resolve(); return; }
                const timer = setTimeout(() => { clean(); reject(new Error('Video seek timeout: ' + v.src)); }, 4000);
                const clean = () => { clearTimeout(timer); v.removeEventListener('seeked', done); v.removeEventListener('error', fail); };
                const done = () => { clean(); resolve(); };
                const fail = () => { clean(); reject(new Error('Video decode failed: ' + v.src)); };
                v.addEventListener('seeked', done); v.addEventListener('error', fail); v.currentTime = target;
            })));
            if (document.querySelector('video')) {
                const settled = window.__lhtmlVerificationClock?.presentationReady;
                if (settled) await settled();
                else await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
            }
            for (const img of document.querySelectorAll('img[data-layout-gif-url]')) {
                if (typeof ImageDecoder === 'undefined') throw new Error('GIF decoder unavailable');
                const data = await new Promise((resolve, reject) => {
                    const xhr = new XMLHttpRequest(); xhr.open('GET', img.dataset.layoutGifUrl); xhr.responseType = 'arraybuffer';
                    xhr.timeout = 4000; xhr.onload = () => resolve(xhr.response); xhr.onerror = xhr.ontimeout = () => reject(new Error('GIF load failed'));
                    xhr.send();
                });
                const decoder = new ImageDecoder({data, type: 'image/gif'});
                try {
                    await decoder.tracks.ready;
                    const count = decoder.tracks.selectedTrack.frameCount;
                    let index = fraction !== null ? Math.min(count - 1, Math.floor(fraction * count)) : 0;
                    if (fraction === null && time > 0) {
                        let elapsed = 0;
                        for (let i = 0; i < Math.min(count, 240); i++) {
                            const {image} = await decoder.decode({frameIndex: i});
                            const duration = image.duration; image.close();
                            if (!duration || duration <= 0) throw new Error('GIF frame duration unavailable; use automatic frame samples');
                            elapsed += duration / 1000; index = i;
                            if (elapsed > time || i === count - 1) break;
                            if (i === 239) throw new Error('GIF frame budget exhausted');
                        }
                    }
                    const {image} = await decoder.decode({frameIndex: index});
                    const canvas = document.createElement('canvas'); canvas.width = image.displayWidth; canvas.height = image.displayHeight;
                    canvas.getContext('2d').drawImage(image, 0, 0); image.close();
                    await new Promise((resolve, reject) => { img.onload = resolve; img.onerror = reject; img.src = canvas.toDataURL(); });
                    window.__lhtmlMediaSamples.push({type: 'gif', url: img.dataset.layoutGifUrl, frame_index: index, frame_count: count});
                } finally { decoder.close(); }
            }
        }, {time, fraction});
    }
}

async function discover(page, options) {
    const kinds = new Set();
    for (const frame of await localFrames(page)) {
        for (const kind of await frame.evaluate(() => [
            document.getAnimations().length ? 'css_animation' : null,
            document.querySelector('video') ? 'video' : null,
            document.querySelector('img[data-layout-gif-url]') ? 'gif' : null,
            window.__lhtmlVerificationClock?.pending() ? 'requestAnimationFrame' : null,
        ].filter(Boolean))) kinds.add(kind);
    }
    const plans = [...options.plans];
    if (options.auto_media && kinds.size) {
        plans.push({name: 'auto-mid', time_ms: 500, fraction: .5, actions: [], expect: []},
                   {name: 'auto-late', time_ms: 1500, fraction: .9, actions: [], expect: []});
    }
    return {detected: [...kinds], truncated: plans.length > options.max_states,
        requested: plans.length, plans: plans.slice(0, options.max_states)};
}

async function targetFrame(page, selector) {
    if (!selector) return page.mainFrame();
    const element = await page.waitForSelector(selector, {visible: true, timeout: 4000});
    const frame = await element.contentFrame(); await element.dispose();
    if (!frame || (!frame.url().startsWith('file:') && !frame.url().startsWith('about:'))) {
        throw new Error('Frame unavailable or external: ' + selector);
    }
    return frame;
}

async function apply(page, plan, journal = [], ready = null) {
    const initial = new URL(page.url());
    for (const action of plan.actions || []) {
        const frame = await targetFrame(page, action.frame);
        const target = await frame.waitForSelector(action.selector, {visible: true, timeout: 4000});
        await target.dispose();
        if (action.type === 'click') await frame.click(action.selector);
        else if (action.type === 'key') { await frame.focus(action.selector); await page.keyboard.press(action.key); }
        else await frame.$eval(action.selector, (el, value) => {
            if (!el.matches('input, textarea, select')) throw new Error('Input action requires a form control');
            el.value = value; el.dispatchEvent(new Event('input', {bubbles: true})); el.dispatchEvent(new Event('change', {bubbles: true}));
        }, action.value);
        const current = new URL(page.url());
        if (initial.origin !== current.origin || initial.pathname !== current.pathname) throw new Error('Action navigated away from the slide');
        journal.push({...action, completed: true});
    }
    if (ready) await ready();
    await advance(page, plan.time_ms || 0, plan.fraction ?? null);
    for (const check of plan.expect || []) {
        const frame = await targetFrame(page, check.frame);
        const element = await frame.$(check.selector);
        const visible = element ? await element.evaluate(el => {
            const r = el.getBoundingClientRect(), cs = getComputedStyle(el);
            return r.width > 0 && r.height > 0 && cs.display !== 'none' && cs.visibility !== 'hidden' && Number(cs.opacity) !== 0;
        }) : false;
        if (element) await element.dispose();
        if (visible !== (check.visible ?? true)) throw new Error('Visibility assertion failed: ' + check.selector);
    }
    return journal;
}
module.exports = {installClock, localFrames, advance, discover, apply};
