'use strict';

// The main frame and the visible local frames (file:, about:) of a page, at most
// 16 child frames: the frames whose content is waited for and measured.
async function localFrames(page) {
    const frames = [];
    for (const frame of page.frames()) {
        if (frames.length >= 17) break;
        if (frame === page.mainFrame()) { frames.push(frame); continue; }
        if (!frame.url().startsWith('file:') && !frame.url().startsWith('about:')) continue;
        const el = await frame.frameElement();
        const box = await el.boundingBox(); await el.dispose();
        if (box && box.width > 0 && box.height > 0) frames.push(frame);
    }
    return frames;
}

module.exports = {localFrames};
