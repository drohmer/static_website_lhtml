"use strict";


const toc = {{TOC}};


const tocElementMenu = document.querySelector('#toc');
const currentPageTitle = document.querySelector('#current-page-title').textContent;
const currentPageID = parseInt(document.querySelector('#current-page-id').textContent);

tocElementMenu.innerHTML = '<strong>Table of content</strong>'
const path_to_root = '../'.repeat(toc[currentPageID]["level"]);


let current_indent = 0;
let previous_level = 0;
let increase_future_indent = false;
let k=0;

for (let k=0; k<toc.length; k=k+1)
{
    const element = toc[k];
    
    
    if(k>0) {
        const previous_level = toc[k-1].level;
    }
    if(increase_future_indent==true){
        current_indent = current_indent +1;
        increase_future_indent = false;
    }
    
    const current_level = toc[k].level;
    if(current_level>previous_level) {
        increase_future_indent = true;
    }
    if(current_level<previous_level) {
        current_indent = current_indent -1;
    }
    previous_level = current_level;
    

    const title = element["title"];
    const link = path_to_root+element["path"];

    const pageEntry = document.createElement('div');
    pageEntry.classList.add('indent-'+current_indent);

    const linkElement = document.createElement('a');
    linkElement.href = link;
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


