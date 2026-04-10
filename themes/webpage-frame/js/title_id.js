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
    console.log('Failed to fetch title_id file');
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
    title_id_element.innerHTML = '<div class="title">Page content</div>'

    for(let k=0; k<data.length; k=k+1) {

        const level = data[k]['level'];
        const title = data[k]['title'];
        const id = data[k]['id'];

        const title_id_element = document.querySelector('#title_id');
        if(level>1 && level<3){
            const a_element = create_new_link(level, title, id);
            title_id_element.appendChild(a_element);
        }
    }

}

async function main() {


    await fetch_title_id("title_id.json");

}

main();