'use strict';
// Apps with asynchronous setup may register promises and explicitly opt in.
(() => {
    const tasks = [], errors = [];
    let optedIn = false;
    window.__lhtmlReady = {
        version: 1,
        optIn() { optedIn = true; },
        waitUntil(promise) { tasks.push(Promise.resolve(promise).catch(error => { errors.push(String(error)); })); },
        trusted() {
            return optedIn || [...document.scripts].every(script =>
                script.src && /\/theme\/(js\/(readiness|presentation_resize_page|menu|navigation)\.js|libs\/katex\/(katex\.min\.js|contrib\/auto-render\.min\.js))$/.test(new URL(script.src).pathname));
        },
        async ready() {
            let count;
            do { count = tasks.length; await Promise.all(tasks); } while (count !== tasks.length);
            if (errors.length) throw Error('Readiness failed: ' + errors.join('; '));
        }
    };
})();
