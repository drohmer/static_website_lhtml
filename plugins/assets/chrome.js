'use strict';

// Options of puppeteer.launch() shared by the scripts of this directory.
//
// The Chrome executable is chosen in this order:
//   1. --chrome=<path>, written by the generator from the configuration key
//      'chrome' (already resolved and checked by lib/configuration.py);
//   2. PUPPETEER_EXECUTABLE_PATH, the variable puppeteer itself reads;
//   3. none: the Chrome downloaded by puppeteer
//      (npx puppeteer browsers install chrome).

function executablePath(args) {
    const value = (args && typeof args.chrome === 'string' ? args.chrome : '')
        || process.env.PUPPETEER_EXECUTABLE_PATH || '';
    return value.trim();
}

/** The options given to puppeteer.launch(), with the chosen executable. */
function launchOptions(args, options) {
    const executable = executablePath(args);
    return executable ? {...options, executablePath: executable} : {...options};
}

module.exports = {launchOptions, executablePath};
