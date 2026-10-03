'use strict';

// Screenshot contact sheets (HTML pages of slide thumbnails written by
// layout_report.py) in headless Chrome (puppeteer).
//
// Usage:
//   node layout_contact.js --input=sheets.json [--width=1920]
//
// sheets.json: [{"html": "/abs/contact_01.html", "png": "/abs/contact_01.png"}, ...]

const fs = require('fs');
const path = require('path');
const puppeteer = require('puppeteer');
const args = require('minimist')(process.argv.slice(2));

const sheets = JSON.parse(fs.readFileSync(args.input, 'utf-8'));
const width = parseInt(args.width || 1920);

(async () => {
    const browser = await puppeteer.launch({headless: true, args: ['--allow-file-access-from-files']});
    const page = await browser.newPage();
    await page.setViewport({width, height: 600});
    let failures = 0;
    for (const sheet of sheets) {
        try {
            await page.goto('file://' + path.resolve(sheet.html), {waitUntil: 'networkidle0', timeout: 60000});
            await page.evaluate(async () => {
                await Promise.all([...document.images].filter(img => !img.complete).map(img =>
                    new Promise(resolve => { img.onload = img.onerror = resolve; })));
            });
            await page.screenshot({path: sheet.png, fullPage: true});
        } catch (e) {
            failures += 1;
            console.error(`layout_contact: ${sheet.html}: ${e.message}`);
        }
    }
    await browser.close();
    process.exit(failures ? 1 : 0);
})();
