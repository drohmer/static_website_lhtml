"use strict";

let controlKeyIsPressed = false;
let mouseInsideTableOfContent = false;
let mouseInsideMenu = false;

document.addEventListener('keydown', keyPressed);
document.addEventListener('keyup',keyReleased);
document.addEventListener('wheel', mouseWheel, {passive:true});

const menuElement = document.querySelector('#menu');
const tocElement = document.querySelector('#toc');
menuElement.addEventListener('click', menuClick);



function goNext() {
    const linkElement = document.querySelector('#link-next a');
    if(linkElement!=null){
        linkElement.click();
    }
}
function goPrev() {
    const linkElement = document.querySelector('#link-prev a');
    if(linkElement!=null){
        linkElement.click();
    }
}

function keyPressed(event) {

    if (event.key === 'Control') {
        controlKeyIsPressed = true;
    }

    if ((event.key === 'ArrowRight') || (event.key === 'ArrowDown')) {
        goNext();
    }
    else if ((event.key === 'ArrowLeft') || (event.key === 'ArrowUp')) {
        goPrev();
    }
    
}

function keyReleased(event) {
    if (event.key === 'Control') {
        controlKeyIsPressed = false;
    }
}

function mouseWheel(event) {
    if (mouseInsideMenu === false && controlKeyIsPressed===false) {
        if (event.deltaY < 0) {
            goPrev();
        }
        else if (event.deltaY > 0) {
            goNext();
        }
    }
}


function menuClick()
{
    if (tocElement.classList.contains('hidden')) {
        tocElement.classList.remove('hidden');
        tocElement.addEventListener('pointerenter', enterToc);
        tocElement.addEventListener('pointerleave', leaveToc);
    }
    else {
        tocElement.classList.add('hidden');
        tocElement.removeEventListener('pointerenter', enterToc);
        tocElement.removeEventListener('pointerleave', leaveToc);
    }
}

function enterToc(event) {
    mouseInsideMenu = true;
}
function leaveToc(event) {
    mouseInsideMenu = false;
}


