'use strict';
// Crop the saved PNG, rather than rerendering a potentially animated slide.
const fs = require('fs');
const path = require('path');
const puppeteer = require('puppeteer');
(async () => {
    const folders = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
    const browser = await puppeteer.launch({headless: true});
    try {
        const page = await browser.newPage();
        for (const folder of folders) {
            const reportPath = path.join(folder, 'verification.json');
            const report = JSON.parse(fs.readFileSync(reportPath, 'utf8'));
            const imagePath = path.join(folder, 'render.png');
            if (!fs.existsSync(imagePath)) continue;
            await page.setContent('<style>html,body{margin:0}img{display:block}</style><img>');
            await page.evaluate(async data => {
                const img = document.querySelector('img');
                img.src = data; await img.decode();
            }, 'data:image/png;base64,' + fs.readFileSync(imagePath).toString('base64'));
            const size = await page.evaluate(() => ({w: document.images[0].naturalWidth, h: document.images[0].naturalHeight}));
            await page.setViewport({width: size.w, height: size.h});
            const issueDir = path.join(folder, 'issues');
            fs.rmSync(issueDir, {recursive:true, force:true});
            let count = 0;
            let currentImage = imagePath;
            for (const diagnostic of report.diagnostics) {
                const b = diagnostic.bounds;
                if (!b || count >= 20) continue;
                const targetImage = diagnostic.state_id ? path.join(folder, 'states', diagnostic.state_id, 'render.png') : imagePath;
                if (!fs.existsSync(targetImage)) continue;
                if (targetImage !== currentImage) {
                    await page.evaluate(async data => { document.images[0].src = data; await document.images[0].decode(); },
                        'data:image/png;base64,' + fs.readFileSync(targetImage).toString('base64'));
                    currentImage = targetImage;
                }
                const x = Math.max(0, Math.min(size.w, Math.floor(b.x0 - 32)));
                const y = Math.max(0, Math.min(size.h, Math.floor(b.y0 - 32)));
                const width = Math.min(size.w, Math.ceil(b.x1 + 32)) - x;
                const height = Math.min(size.h, Math.ceil(b.y1 + 32)) - y;
                if (width <= 0 || height <= 0) continue;
                fs.mkdirSync(issueDir, {recursive:true});
                const name = `issues/${++count}.png`;
                const encoded = await page.evaluate(({x,y,width,height}) => {
                    const canvas = document.createElement('canvas'); canvas.width = width; canvas.height = height;
                    canvas.getContext('2d').drawImage(document.images[0],x,y,width,height,0,0,width,height);
                    return canvas.toDataURL('image/png').split(',')[1];
                }, {x,y,width,height});
                fs.writeFileSync(path.join(folder,name),Buffer.from(encoded,'base64'));
                diagnostic.evidence.crop = name;
            }
            report.artifacts.crops = count;
            fs.writeFileSync(reportPath, JSON.stringify(report, null, 2));
        }
    } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
