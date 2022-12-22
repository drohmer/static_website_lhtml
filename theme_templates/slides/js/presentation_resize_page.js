"use strict";

const defaultWidth = 1920;
const defaultHeight = 1080;

resizePage(null);

window.addEventListener('resize', resizePage);

function resizePage(event) {

    // browser zoom (fixme)
    var browserZoomLevel = 1.0;//window.devicePixelRatio;
    // if(browserZoomLevel>1.1)
    //     document.querySelector("html").style.overflow = "auto"; // add scrollbar when zoomed


    const w = document.documentElement.clientWidth ||
    window.innerWidth  ||
    document.body.clientWidth;

    
    const h = document.documentElement.clientHeight || 
    window.innerHeight || 
    document.body.clientHeight; 


    const zoom = Math.min(w / defaultWidth, h / defaultHeight);

    const contentElement = document.querySelector('html');
    contentElement.style.transform = `scale(${zoom*browserZoomLevel})`;
    contentElement.style.transformOrigin = `top left`;
    const marginTop = (h - zoom * defaultHeight) / 2;
    const marginLeft = (w - zoom * defaultWidth) / 2;

    contentElement.style.width = `${defaultWidth}px`;
    contentElement.style.height = `${defaultHeight}px`;
    contentElement.style.marginTop = `${marginTop}px`;
    contentElement.style.marginLeft = `${marginLeft}px`;
}
