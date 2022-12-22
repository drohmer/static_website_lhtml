'use strict';

const puppeteer = require('puppeteer');
const path = require('path');
const args = require('minimist')(process.argv.slice(2))

let width = '1925px';
let height = '1085px';
let input = 'index.html';
let output = 'output.pdf';
if(args['width']){width = args['width'];}
if(args['height']){height = args['height'];}
if(args['input']){input = args['input'];}
if(args['output']){output = args['output'];}


const url = `file:${input}`;


(async() => {    
const browser = await puppeteer.launch({
  args: [
       '--disable-gpu',
       '--disable-dev-shm-usage',
       '--disable-setuid-sandbox',
       '--no-first-run',
       '--no-sandbox',
       '--no-zygote',
       '--single-process',
  ]
});
const page = await browser.newPage(); 

//await page.setViewport({width:viewport_width, height:viewport_height});

await page.setDefaultNavigationTimeout(2000);
await page.goto(url ,{waitUntil: 'networkidle2'})
.catch(
  (err)=>{
    //null;
    console.log(err);
  }
  );

await page.waitForTimeout(500);


await page.pdf({
  path: output,
  width: width,
  height: height,
  margin: {
        top: "0px",
        left: "0px",
        right: "0px",
        bottom: "0px"
  }
});

await browser.close();    

})();

