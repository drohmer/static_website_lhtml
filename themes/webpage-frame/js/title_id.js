"use strict";

function convertJSON(response){
    return response.json();
}

async function fetch_title_id(filepath) {
    await fetch(filepath)
    .then(convertJSON)
    .then(load_title_id)
    .catch(error_fetch_title_id);
}
function error_fetch_title_id(error) {
    // No summary for this page (plugins/title_submenu.py did not run, or the
    // page has no heading of its own): the column stays hidden.
    console.log('No title_id file for this page (plugins/title_submenu.py)');
    console.log(error);
}

function create_new_link(level, title, id) {
    const div_element = document.createElement('div');
    div_element.classList.add("title_id-level-"+level);
    const a_element = document.createElement('a');
    a_element.textContent = title;
    a_element.href = '#'+id;
    div_element.appendChild(a_element)

    return div_element;
}

function load_title_id(data) {

    const title_id_element = document.querySelector('#title_id');

    const links = [];
    for(let k=0; k<data.length; k=k+1) {

        const level = data[k]['level'];
        const title = data[k]['title'];
        const id = data[k]['id'];

        if(level>1 && level<3){
            links.push(create_new_link(level, title, id));
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

async function main() {


    const filename = window.location.pathname.split('/').pop() || 'index.html';
    await fetch_title_id(filename + '.title_id.json');

}

main();