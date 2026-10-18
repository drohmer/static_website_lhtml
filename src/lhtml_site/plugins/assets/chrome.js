'use strict';

// Launching Chrome, shared by the scripts of this directory.
//
// The executable is chosen in this order:
//   1. --chrome=<path>, written by the generator from the configuration key
//      'chrome' (already resolved and checked by lhtml_site/configuration.py);
//   2. PUPPETEER_EXECUTABLE_PATH, the variable puppeteer itself reads;
//   3. the Chrome puppeteer downloaded;
//   4. if, and only if, that launch fails for want of a browser, a Chrome
//      installed on the machine, saying on stderr which one it took.
//
// Step 4 exists because a measurement must not fail for want of a browser
// next to the generator: recent npm versions do not run the install script
// of puppeteer, so `npm install` alone leaves no Chrome behind.

const fs = require('fs');

const INSTALLED = {
    darwin: ['/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
             '/Applications/Chromium.app/Contents/MacOS/Chromium',
             '/Applications/Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary'],
    linux: ['/usr/bin/google-chrome', '/usr/bin/google-chrome-stable', '/usr/bin/chromium',
            '/usr/bin/chromium-browser', '/snap/bin/chromium'],
    win32: ['C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
            'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe'],
};

const NO_BROWSER = /could not find|is not found|does not exist|no such file|ENOENT|browser was not found/i;

function exists(path) {
    try {
        return Boolean(path) && fs.statSync(path).isFile();
    } catch {
        return false;
    }
}

/** The executable asked for by the configuration or the environment, or ''. */
function executablePath(args) {
    return ((args && typeof args.chrome === 'string' ? args.chrome : '')
        || process.env.PUPPETEER_EXECUTABLE_PATH || '').trim();
}

/** The first Chrome installed on this machine, or ''. */
function installedChrome() {
    return (INSTALLED[process.platform] || []).find(exists) || '';
}

/** The options given to puppeteer.launch(), with the executable asked for. */
function launchOptions(args, options) {
    const asked = executablePath(args);
    return asked ? {...options, executablePath: asked} : {...options};
}

/**
 * Launch Chrome. Without an executable asked for, puppeteer uses the one it
 * downloaded; if there is none, a Chrome installed on the machine is used
 * rather than failing.
 */
async function launchBrowser(puppeteer, args, options) {
    try {
        return await puppeteer.launch(launchOptions(args, options));
    } catch (error) {
        const installed = !executablePath(args) && installedChrome();
        if (!installed || !NO_BROWSER.test(String((error && error.message) || error))) {
            throw error;
        }
        console.error('chrome: puppeteer has no Chrome of its own '
                      + '(npx puppeteer browsers install chrome); using ' + installed);
        return puppeteer.launch({...options, executablePath: installed});
    }
}

module.exports = {launchBrowser, launchOptions, executablePath, installedChrome};
