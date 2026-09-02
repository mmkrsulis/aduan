const puppeteer=require('/usr/src/app/node_modules/puppeteer');
const fs=require('fs');
(async()=>{
  const cookie=fs.readFileSync(0,'utf8').trim();
  const browser=await puppeteer.launch({executablePath:'/usr/bin/google-chrome',headless:true,args:['--no-sandbox','--disable-dev-shm-usage']});
  try{
    const page=await browser.newPage();
    const errors=[];
    page.on('pageerror',error=>errors.push(error.message));
    await page.setRequestInterception(true);
    page.on('request',request=>/fonts\.(googleapis|gstatic)\.com/.test(request.url())?request.abort():request.continue());
    const origin='http://aduan-hub:8080';
    await page.setCookie({name:'session',value:cookie,url:origin,httpOnly:true});

    await page.setViewport({width:1440,height:900});
    await page.goto(origin+'/dashboard',{waitUntil:'domcontentloaded'});
    await page.evaluate(()=>localStorage.removeItem('aduanhubSidebarCollapsed'));
    await page.reload({waitUntil:'domcontentloaded'});
    await page.click('#menu');
    await new Promise(resolve=>setTimeout(resolve,300));
    const collapsed=await page.evaluate(()=>({
      root:document.documentElement.classList.contains('sidebar-collapsed'),
      width:Math.round(document.querySelector('#side').getBoundingClientRect().width),
      expanded:document.querySelector('#menu').getAttribute('aria-expanded'),
      saved:localStorage.getItem('aduanhubSidebarCollapsed'),
      overflow:document.documentElement.scrollWidth>innerWidth
    }));
    if(!collapsed.root||collapsed.width!==76||collapsed.expanded!=='false'||collapsed.saved!=='1'||collapsed.overflow)throw Error('Desktop collapse failed: '+JSON.stringify(collapsed));
    await page.reload({waitUntil:'domcontentloaded'});
    if(!await page.evaluate(()=>document.documentElement.classList.contains('sidebar-collapsed')))throw Error('Desktop preference did not persist');
    await page.click('.nav-settings summary');
    const expanded=await page.evaluate(()=>({collapsed:document.documentElement.classList.contains('sidebar-collapsed'),open:document.querySelector('.nav-settings').open}));
    if(expanded.collapsed||!expanded.open)throw Error('Collapsed submenu did not expand the sidebar');
    await new Promise(resolve=>setTimeout(resolve,300));
    const shellColor=await page.$eval('#side',element=>getComputedStyle(element).backgroundImage);
    if(!shellColor.includes('linear-gradient'))throw Error('Sidebar shell palette was not applied');
    const customPalette=await page.evaluate(()=>{
      const original=document.documentElement.style.getPropertyValue('--accent');
      const before=getComputedStyle(document.querySelector('#side')).backgroundImage;
      document.documentElement.style.setProperty('--accent','#7c3aed');
      const after=getComputedStyle(document.querySelector('#side')).backgroundImage;
      document.documentElement.style.setProperty('--accent',original);
      return {before,after};
    });
    if(customPalette.before===customPalette.after)throw Error('Sidebar does not react to the configured accent');
    await page.screenshot({path:'/tmp/aduanhub-sidebar-blue.png',fullPage:false});
    await page.setViewport({width:1440,height:568});
    await page.evaluate(()=>document.querySelectorAll('.nav-settings').forEach(details=>details.open=true));
    const shortNav=await page.$eval('#side nav',element=>({scrolls:element.scrollHeight>element.clientHeight,scrollbar:getComputedStyle(element).scrollbarColor}));
    if(!shortNav.scrolls||shortNav.scrollbar.includes('auto'))throw Error('Short sidebar scrolling is not styled: '+JSON.stringify(shortNav));
    await page.screenshot({path:'/tmp/aduanhub-sidebar-scroll.png',fullPage:false});

    await page.setViewport({width:1015,height:842});
    await page.reload({waitUntil:'domcontentloaded'});
    const split=await page.evaluate(()=>({
      open:document.querySelector('#side').classList.contains('open'),
      hidden:document.querySelector('#side').getAttribute('aria-hidden'),
      mainWidth:Math.round(document.querySelector('main').getBoundingClientRect().width),
      cards:document.querySelectorAll('.metrics .metric').length,
      overflow:document.documentElement.scrollWidth>innerWidth,
      sideColumns:getComputedStyle(document.querySelector('.dashboard-side')).gridTemplateColumns.split(' ').length
    }));
    if(split.open||split.hidden!=='true'||split.mainWidth!==1015||split.cards!==4||split.overflow||split.sideColumns!==2)throw Error('Split-window layout failed: '+JSON.stringify(split));
    await page.screenshot({path:'/tmp/aduanhub-dashboard-1015.png',fullPage:true});
    await page.click('#menu');
    if(!await page.evaluate(()=>document.querySelector('#side').classList.contains('open')))throw Error('Split-window drawer did not open');
    await page.keyboard.press('Escape');

    await page.setViewport({width:390,height:844});
    await page.reload({waitUntil:'domcontentloaded'});
    let mobile=await page.evaluate(()=>({open:document.querySelector('#side').classList.contains('open'),hidden:document.querySelector('#side').getAttribute('aria-hidden'),overflow:document.documentElement.scrollWidth>innerWidth}));
    if(mobile.open||mobile.hidden!=='true'||mobile.overflow){
      const offenders=await page.evaluate(()=>[...document.querySelectorAll('body *')].filter(element=>element.getBoundingClientRect().right>innerWidth+1).slice(0,10).map(element=>({tag:element.tagName,className:element.className,right:Math.round(element.getBoundingClientRect().right),width:Math.round(element.getBoundingClientRect().width)})));
      throw Error('Mobile closed state failed: '+JSON.stringify({mobile,offenders}));
    }
    await page.click('#menu');
    await new Promise(resolve=>setTimeout(resolve,250));
    mobile=await page.evaluate(()=>({open:document.querySelector('#side').classList.contains('open'),hidden:document.querySelector('#side').getAttribute('aria-hidden'),backdrop:getComputedStyle(document.querySelector('#sidebar-backdrop')).visibility,expanded:document.querySelector('#menu').getAttribute('aria-expanded')}));
    if(!mobile.open||mobile.hidden!=='false'||mobile.backdrop!=='visible'||mobile.expanded!=='true')throw Error('Mobile open state failed: '+JSON.stringify(mobile));
    await page.keyboard.press('Escape');
    if(await page.evaluate(()=>document.querySelector('#side').classList.contains('open')))throw Error('Escape did not close drawer');
    await page.click('#menu');
    await page.click('#sidebar-backdrop');
    await page.click('#menu');
    await page.click('#sidebar-close');
    if(await page.evaluate(()=>document.querySelector('#side').classList.contains('open')))throw Error('Explicit close did not close drawer');
    if(errors.length)throw Error(errors.join('; '));
    console.log('PASS: desktop collapse/persistence/submenu and mobile drawer/backdrop/Escape/close, no overflow or JS errors.');
  }finally{await browser.close()}
})().catch(error=>{console.error(error.message);process.exit(1)});
