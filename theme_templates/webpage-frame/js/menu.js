"use strict";


const toc = {{TOC}};


const tocElementMenu = document.querySelector('#toc');
const currentPageTitle = document.querySelector('#current-page-title').textContent;
const currentPageID = parseInt(document.querySelector('#current-page-id').textContent);

tocElementMenu.innerHTML = '<strong id="toc-title">Table of content</strong>'
const path_to_root = '../'.repeat(toc[currentPageID]["level"]);

const image_up = path_to_root+"theme/icons/up_enabled.svg";
const image_down = path_to_root+"theme/icons/down_enabled.svg";


function create_hierachy(toc) {
    let hierarchy = [];
    let current_level = 0;
    
    if(toc.length>0) {
        const element = toc[0];
        element["children"] = []
        element["parent"] = hierarchy
        hierarchy.push(element);
    }
    
    let container = [hierarchy];
    for (let k=1; k<toc.length; k=k+1)
    {   
        const element = toc[k];
        element["children"] = [];
        const last_element = toc[k-1];
       
        if(element["level-toc"]==last_element["level-toc"]) {
            container[container.length-1].push(element);
        }
        else if(element["level-toc"]>last_element["level-toc"]) {
            last_element["children"].push(element);
            container.push(last_element["children"]);
        }
        else if(element["level-toc"]<last_element["level-toc"]) {
            container.pop();
            container[container.length-1].push(element);
        }
    }
    return hierarchy
}

function display(toc) {
    for (let k=0; k<toc.length; k=k+1)
    {
        const element = toc[k];
       
        const title = element["title"];
        const link = path_to_root+element["path"];
    
        let level_toc = 0;
        if(element["level-toc"]!=undefined) {
            level_toc = element["level-toc"];
        }
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
}

function create_element(element) {
    const title = element["title"];
    const link = path_to_root+element["path"];
    let level_toc = element["level-toc"];
    const nourl_toc = element["nourl-toc"];


    const pageEntry = document.createElement('div');
    pageEntry.classList.add('indent-'+level_toc);
    pageEntry.classList.add('toc-entry');

    let linkElement; 
    if(nourl_toc!="True"){
        linkElement = document.createElement('a');
        linkElement.href = link;
    }
    else {
        linkElement = document.createElement('span');
        linkElement.classList.add("no-url");
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

    return pageEntry;
}

function apply_stored_expendable() {
    const all_expendable = document.querySelectorAll('.toc-expandable')
    for(let k=0; k<all_expendable.length; k=k+1) {
        const id = all_expendable[k].id;
        const group = id.substring(17, undefined);
        const expandable_trigger = document.querySelector('#expand-group-'+group+' img');
        if(localStorage.getItem('toc-expand-group-'+group)!=undefined) {
            const value = localStorage.getItem('toc-expand-group-'+group);
            if(value==="true") {
                all_expendable[k].classList.remove('hidden');
                expandable_trigger.src = image_up;
            }
        }
    }
}

function action_expend_toc(event) {
    const target = event.currentTarget;
    const id = target.id;
    const group = id.substring(13,undefined);

    const expandable = document.querySelector('#expandable-group-'+group);
    const expandable_trigger = document.querySelector('#expand-group-'+group+' img');
    if(expandable.classList.contains('hidden')) {
        expandable.classList.remove('hidden');
        expandable_trigger.src = image_up;
        localStorage.setItem("toc-expand-group-"+group, true);
    }
    else {
        expandable.classList.add('hidden');
        expandable_trigger.src = image_down;
        localStorage.setItem("toc-expand-group-"+group, false);
    }
}

let current_group_expendable_id = 1;
function add_element_recurse(parent, listing) {
    for(let k=0;k<listing.length; k=k+1) {

        let element = listing[k];
        if(element["hide_toc"]=="True") {continue;}
        let pageEntry = create_element(element);



        if(element["children"].length>0) {

            let group = 0;
            if(element['expandable-toc']!=undefined && element['expandable-toc']==="True") {
                group = current_group_expendable_id;
                current_group_expendable_id = current_group_expendable_id+1;

                const expandable = document.createElement('div');
                expandable.id = `expand-group-${group}`;
                expandable.classList.add('toc-expandable-trigger');
                expandable.innerHTML = `<img src="${image_down}" alt="expand">`;
                expandable.addEventListener('click', action_expend_toc);
                pageEntry.appendChild(expandable);
                pageEntry.appendChild(document.createElement('div'));
                pageEntry.classList.add('toc-expandable-title');
            }
            const child = document.createElement('div');
            child.id = `expandable-group-`+group;
            child.classList.add('toc-expandable');
            if(group!=0) {
                child.classList.add('hidden');
            }
            pageEntry.appendChild(child);
            add_element_recurse(child,element["children"]);
        }


        parent.appendChild(pageEntry);
    }
}

function display2(toc, hierarchy) {
    let parent = tocElementMenu;
    add_element_recurse(parent, hierarchy, -1);
    // for(let k=0;k<hierarchy.length; k=k+1) {

    //     if(hierarchy[k]["hide_toc"]=="True") {
    //         continue;
    //     }

    //     let pageEntry = create_element(hierarchy[k]);
    //     parent.appendChild(pageEntry);
    // }
}

function main() {

    // Set default level
    for (let k=0; k<toc.length; k=k+1) {
        let level = 0;
        if(toc[k]["level-toc"]==undefined) {
            toc[k]["level-toc"] = 0;
        }
    }

    // Create hierarchy
    const hierarchy = create_hierachy(toc);
    //display(toc);
    display2(toc, hierarchy);


    apply_stored_expendable();

}

main();







