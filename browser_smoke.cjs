// Run in an isolated Chrome profile. Session cookie is received via stdin, never logged.
const puppeteer=require('/usr/src/app/node_modules/puppeteer');
const fs=require('fs');
(async()=>{
 const cookie=fs.readFileSync(0,'utf8').trim();
 const browser=await puppeteer.launch({executablePath:'/usr/bin/google-chrome',headless:true,args:['--no-sandbox','--disable-dev-shm-usage']});
 try {
  const page=await browser.newPage(); const errors=[]; page.on('pageerror',e=>errors.push(e.message));
  const origin='http://100.103.199.63:18083';
  await page.setViewport({width:1440,height:1000});
  await page.goto(origin,{waitUntil:'networkidle2'});
  await page.screenshot({path:'/tmp/aduanhub-landing-blue.png',fullPage:true});
  await page.setViewport({width:390,height:844});
  await page.reload({waitUntil:'networkidle2'});
  const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth);
  if(overflow)throw Error('Mobile landing overflows');
  await page.screenshot({path:'/tmp/aduanhub-landing-mobile.png',fullPage:true});
  await page.setCookie({name:'session',value:cookie,url:origin,httpOnly:true});
  await page.setViewport({width:1440,height:1000});
  await page.goto(origin+'/tickets/10',{waitUntil:'networkidle2'});
  await page.waitForSelector('.chat-appearance');
  if(await page.$('select[name="unit"]'))throw Error('Duplicate assignment remains');
  await page.click('.chat-appearance summary');
  await page.select('#chat-palette','violet');
  const color=await page.$eval('.messages',el=>getComputedStyle(el).backgroundColor);
  if(color!=='rgb(241, 238, 249)')throw Error('Custom color did not apply: '+color);
  await page.reload({waitUntil:'networkidle2'});
  if(await page.$eval('#chat-palette',el=>el.value)!=='violet')throw Error('Preference not persisted');
  await page.click('.chat-appearance summary'); await page.click('#chat-appearance-reset');
  await page.click('.chat-appearance summary');
  await page.screenshot({path:'/tmp/aduanhub-chat-blue.png',fullPage:true});
  await page.setViewport({width:390,height:844});await page.reload({waitUntil:'networkidle2'});
  if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth)){
    console.log(await page.evaluate(()=>[...document.querySelectorAll('body *')].filter(e=>e.getBoundingClientRect().right>innerWidth+1).slice(0,20).map(e=>({tag:e.tagName,cls:e.className,right:e.getBoundingClientRect().right}))));
    await page.screenshot({path:'/tmp/aduanhub-chat-mobile.png',fullPage:true});throw Error('Mobile ticket overflows');
  }
  // Intercept every delivery request for a synthetic UI test. No message leaves this browser.
  await page.setRequestInterception(true);let synthetic=null;let state='sent';let posts=0;
  page.on('request',request=>{
    if(request.url().endsWith('/tickets/10/delivery')){
      if(request.method()==='POST'){
        posts++;const token=request.postData()?.match(/name="client_token"\r\n\r\n([^\r]+)/)?.[1];
        synthetic={id:999999,client_token:token,body:'UI-only smoke test',sender:'Test',delivery_status:state};
        request.respond({status:202,contentType:'application/json',body:JSON.stringify({message:synthetic})});
      }else request.respond({status:200,contentType:'application/json',body:JSON.stringify({messages:synthetic?[{...synthetic,delivery_status:state}]:[]})});
    }else request.continue();
  });
  await page.type('.chat-composer textarea','UI-only smoke test');await page.click('#composer-submit');
  await page.waitForSelector('[data-message-id="999999"] [data-status="sent"]');
  state='read';await page.waitForSelector('[data-message-id="999999"] [data-status="read"]',{timeout:10000});
  if(posts!==1)throw Error('Duplicate UI submission');
  if(errors.length)throw Error(errors.join('; '));
  console.log('PASS: desktop/mobile landing, responsive ticket, custom colors persist/reset, unified assignment, simulated send/read, no JS errors.');
 } finally { await browser.close(); }
})().catch(error=>{console.error(error.message);process.exit(1);});
