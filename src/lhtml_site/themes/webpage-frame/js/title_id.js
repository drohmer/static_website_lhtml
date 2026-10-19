"use strict";

// The "Page content" column: the level-2 headings of the page that have an
// id (lhtml_site/headings.py gives them one), read in the page itself. No
// request: the column is the same over http and from a file opened on disk.

function create_new_link(level, title, id) {
    const div_element = document.createElement('div');
    div_element.classList.add("title_id-level-"+level);
    const a_element = document.createElement('a');
    a_element.textContent = title;
    a_element.href = '#'+id;
    div_element.appendChild(a_element)

    return div_element;
}

function page_headings() {
    const content = document.querySelector('#main-content-centered') || document.body;
    return Array.from(content.querySelectorAll('h2[id]'));
}

function main() {

    const title_id_element = document.querySelector('#title_id');
    if(!title_id_element){
        return;
    }

    const links = [];
    for(const heading of page_headings()){
        const title = heading.textContent.replace(/\s+/g, ' ').trim();
        if(title){
            links.push(create_new_link(2, title, heading.id));
        }
    }

    // A page without heading of its own keeps the column hidden, instead of
    // showing an empty box (the column is hidden by the theme, see main.css).
    if(links.length === 0){
        return;
    }
    title_id_element.innerHTML = '<div class="title">Page content</div>'
    for(const link of links){
        title_id_element.appendChild(link);
    }
    title_id_element.style.display = 'block';

}

main();
