const puppeteer=require('/usr/src/app/node_modules/puppeteer');
const fs=require('fs');
(async()=>{
  const cookie=fs.readFileSync(0,'utf8').trim();
  const origin='http://100.103.199.63:18083';
  const browser=await puppeteer.launch({executablePath:'/usr/bin/google-chrome',headless:true,args:['--no-sandbox','--disable-dev-shm-usage']});
  try{
    const page=await browser.newPage();const errors=[];page.on('pageerror',error=>errors.push(error.message));
    await page.setCookie({name:'session',value:cookie,url:origin,httpOnly:true});
    await page.setViewport({width:1440,height:950});
    await page.goto(origin+'/settings?section=whatsapp',{waitUntil:'networkidle2'});
    await page.waitForFunction(()=>document.querySelector('#wa-connection-text')?.textContent.trim()==='Terhubung');
    const desktop=await page.evaluate(()=>({number:document.querySelector('#wa-active-number').textContent.trim(),steps:document.querySelectorAll('.wa-wizard-steps article').length,key:[...document.body.innerText].join('').includes('8af617619fdd28')}));
    if(desktop.number==='—'||desktop.steps!==3||desktop.key)throw Error('Desktop wizard invalid: '+JSON.stringify(desktop));
    await page.setViewport({width:390,height:844});await page.reload({waitUntil:'networkidle2'});
    if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth))throw Error('Mobile wizard overflows');
    const columns=await page.$eval('.wa-wizard-steps',element=>getComputedStyle(element).gridTemplateColumns.split(' ').length);
    if(columns!==1)throw Error('Mobile steps are not stacked');
    if(errors.length)throw Error(errors.join('; '));
    console.log('PASS: live OpenWA status, 3-step wizard, API key hidden, responsive mobile, no JS errors.');
  }finally{await browser.close()}
})().catch(error=>{console.error(error.message);process.exit(1)});
