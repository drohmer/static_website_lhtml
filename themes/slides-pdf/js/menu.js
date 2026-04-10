"use strict";

const toc = {{TOC}};


const tocElementMenu = document.querySelector('#toc');
const currentPageTitle = document.querySelector('#current-page-title').textContent;
const currentPageID = parseInt(document.querySelector('#current-page-id').textContent);

tocElementMenu.innerHTML = ''
const path_to_root = '../'.repeat(toc[currentPageID]["level"]);

let counter = 0;
let page_index = 0;
for (let element of toc)
{
    const title = element["title"];
    const link = path_to_root+element["path"];

    const pageEntry = document.createElement('div');
    const linkElement = document.createElement('a');
    linkElement.href = link;
    linkElement.textContent = counter+' - '+title;

    if(currentPageID === counter) {
        linkElement.classList.add("current-page")
        page_index = counter;
    }
   
    pageEntry.appendChild(linkElement);
    tocElementMenu.appendChild(pageEntry);
    counter = counter + 1;
}

const currentPageElement = document.querySelector('#current-page-index');
const totalPageElement = document.querySelector('#total-page-number');
currentPageElement.textContent = page_index+1;
totalPageElement.textContent = counter;

const linkNextElement = document.querySelector('#link-next');
const linkPrevElement = document.querySelector('#link-prev');


if(page_index+1<counter){
    const url = toc[page_index+1]["path"];
    linkNextElement.innerHTML = `<a href=${path_to_root+url}><div class="next"></div></a>`;
}
else {
    linkNextElement.innerHTML = `<div class="next-inactive"></div>`;
}

if(page_index-1>=0) {
    const url = toc[page_index-1]["path"];
    linkPrevElement.innerHTML = `<a href=${path_to_root+url}><div class="prev"></div></a>`;
}
else {
    linkPrevElement.innerHTML = `<div class="prev-inactive"></div>`;
}
console.log(toc);
console.log(linkPrevElement.innerHTML, page_index, counter);