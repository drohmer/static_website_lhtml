"use strict";


const toc = {{TOC}};


const tocElementMenu = document.querySelector('#toc');
const currentPageTitle = document.querySelector('#current-page-title').textContent;
const currentPageID = parseInt(document.querySelector('#current-page-id').textContent);

tocElementMenu.innerHTML = '<strong id="toc-title">Table of content</strong>'
const path_to_root = '../'.repeat(toc[currentPageID]["level"]);




for (let k=0; k<toc.length; k=k+1)
{
    const element = toc[k];
   
    const title = element["title"];
    const link = path_to_root+element["path"];
    const level_toc = element["level-toc"];
    const hide_toc = element["hide-toc"];
    const nourl_toc = element["nourl-toc"];
    if(hide_toc=="True") {
        continue;
    }

    const pageEntry = document.createElement('div');
    pageEntry.classList.add('indent-'+level_toc);

    let linkElement; 
    if(nourl_toc!="True"){
        linkElement = document.createElement('a');
        linkElement.href = link;
    }
    else {
        linkElement = document.createElement('span');
    }
    linkElement.textContent = title;

    if(title.trim() === currentPageTitle.trim()) {
        linkElement.classList.add("current-page")
    }
   
    pageEntry.appendChild(linkElement);

    if(element["delimiter"]!=null) {
        const delimiter = document.createElement('div');
        delimiter.classList.add("menu-delimiter");
        tocElementMenu.appendChild(delimiter);
    }

    tocElementMenu.appendChild(pageEntry);
}

