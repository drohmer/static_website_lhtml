'use strict';

// What `lhtml-site doctor` asks Node (lhtml_site/doctor.py): whether
// puppeteer and minimist are found from the scripts of this directory, as
// the PDF export and the layout report look for them, and which Chrome they
// would launch (the order of chrome.js). One line of JSON on stdout.

const fs = require('fs');
const chrome = require('./chrome.js');

function resolve(name) {
    try {
        return require.resolve(name);
    } catch {
        return '';
    }
}

(async () => {
    const report = {node: process.version, puppeteer: resolve('puppeteer'), minimist: resolve('minimist'),
                    downloaded: '', asked: chrome.executablePath({}), installed: chrome.installedChrome()};
    if (report.puppeteer) {
        try {
            // The Chrome of the version of puppeteer installed (a promise since puppeteer 25)
            const path = await require('puppeteer').executablePath();
            report.downloaded = path && fs.existsSync(path) ? path : '';
        } catch {
            report.downloaded = '';
        }
    }
    console.log(JSON.stringify(report));
})();
