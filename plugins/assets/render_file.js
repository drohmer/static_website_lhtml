'use strict';

// Render files as PNG in headless Chrome, as the slides draw them (fonts,
// SVG text), without building the site: an image (SVG, PNG...) at its size,
// a page (HTML) at the size of the slide.
//
// Usage: node render_file.js --input=files.json [--width=1920] [--height=1080]
// files.json: [{"file": "/abs/fig.svg", "png": "/abs/out/fig.svg.png"}, ...]

const fs = require('fs');
const os = require('os');
const path = require('path');
const {pathToFileURL} = require('url');
const puppeteer = require('puppeteer');
const args = require('minimist')(process.argv.slice(2));

const files = JSON.parse(fs.readFileSync(args.input, 'utf-8'));
const width = parseInt(args.width || 1920);
const height = parseInt(args.height || 1080);

(async () => {
    const browser = await puppeteer.launch({headless: true, args: ['--allow-file-access-from-files']});
    const page = await browser.newPage();
    let failures = 0;
    for (const entry of files) {
        try {
            fs.mkdirSync(path.dirname(entry.png), {recursive: true});
            const url = pathToFileURL(path.resolve(entry.file)).href;
            if (/\.html?$/i.test(entry.file)) {
                await page.setViewport({width, height});
                await page.goto(url, {waitUntil: 'load', timeout: 60000});
                await page.waitForNetworkIdle({idleTime: 500, timeout: 5000}).catch(() => {});
                await page.screenshot({path: entry.png});
            } else {
                // an image on a white page, at its size (at most the slide)
                // (a page of file://, which may show the files: not about:blank)
                const holder = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'render-')), 'index.html');
                fs.writeFileSync(holder, `<html><body style="margin:0;background:white">
                    <img id="f" style="display:block;max-width:${width}px;max-height:${height}px" src="${url}">
                    </body></html>`);
                await page.setViewport({width, height});
                await page.goto(pathToFileURL(holder).href, {waitUntil: 'load'});
                fs.rmSync(path.dirname(holder), {recursive: true, force: true});
                const size = await page.evaluate(() => new Promise(resolve => {
                    const img = document.getElementById('f');
                    const done = () => resolve({ok: img.naturalWidth > 0, w: img.width, h: img.height});
                    if (img.complete) done(); else { img.onload = done; img.onerror = done; }
                }));
                if (!size.ok) throw new Error('cannot read the image');
                await document_fonts(page);
                const element = await page.$('#f');
                await element.screenshot({path: entry.png});
            }
            console.log(`${entry.file} -> ${entry.png}`);
        } catch (e) {
            failures += 1;
            console.error(`render_file: ${entry.file}: ${e.message}`);
        }
    }
    await browser.close();
    process.exit(failures ? 1 : 0);
})();

async function document_fonts(page) {
    await page.evaluate(async () => { await document.fonts.ready; });
}
