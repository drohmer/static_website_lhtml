"use strict";


const toc = {{TOC}};


const tocElementMenu = document.querySelector('#toc');
const currentPageTitle = document.querySelector('#current-page-title').textContent;
const currentPageID = parseInt(document.querySelector('#current-page-id').textContent);

tocElementMenu.innerHTML = '<strong>Table of content</strong>'
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
    if(nourl_toc=="True"){
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
    tocElementMenu.appendChild(pageEntry);
}




// const url = "../../toc.json"

// function convertJSON(response){
//     return response.json();
// }
// function error_fetch_from_hal(error) {
//     console.log('Failed to fetch toc data');
//     console.log(error);
// }

// function load_toc_data(json) {
//     console.log(json);
//     const toc = document.querySelector('#toc');
//     for(const entry of json) {
//         toc.innerHTML += `<a href="../../${entry.path}">${entry.title}</a>`;
//     }
//     //toc.textContent = "hello 2";
//     //<div id="toc"> {{ table_of_content }} </div>
// }

// fetch(url)
//     .then(convertJSON)
//     .then(load_toc_data)
//     .catch(error_fetch_from_hal);


