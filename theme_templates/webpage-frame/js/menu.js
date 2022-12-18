"use strict";


const toc = {{TOC}};


const tocElementMenu = document.querySelector('#toc');
const currentPageTitle = document.querySelector('#current-page-title').textContent;

tocElementMenu.innerHTML = '<strong>Table of content</strong>'

for (let element of toc)
{
    const title = element["title"];
    const link = element["path"];

    const pageEntry = document.createElement('div');
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


