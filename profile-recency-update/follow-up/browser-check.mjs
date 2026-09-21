import {chromium} from '/home/user/ARPY-decoder-Ui/incois-arpy-decoder/decoder-ui/frontend/node_modules/playwright/index.mjs';
import fs from 'node:fs';
const ROOT='/home/user/profile-recency-update/follow-up';
const expected=JSON.parse(fs.readFileSync(ROOT+'/updated-three.json'));
const utc=s=>new Date(s).toISOString().slice(0,16).replace('T',' ')+' UTC';
const browser=await chromium.launch();const page=await browser.newPage({viewport:{width:1720,height:1000},timezoneId:'Asia/Kolkata'});
const errors=[];page.on('pageerror',e=>errors.push(e.message));
const checks=[];
function check(name,ok){checks.push({name,ok});if(!ok)throw new Error(name);console.log('PASS',name);}
try{
 await page.goto('http://127.0.0.1:3000/',{waitUntil:'domcontentloaded'});
 await page.getByTitle('Open Dedicated Results & Oceanographic Analysis Workspace').click();
 await page.getByRole('button',{name:'[ Float Status ]',exact:true}).click();
 await page.getByTestId('float-status-page').waitFor();
 await page.getByTitle('Filter by data status',{exact:true}).selectOption('ACTIVE / RECENT PROFILE');
 await page.waitForFunction(()=>document.querySelectorAll('[data-testid^="fleet-row-"]').length===4);
 check('four recent-profile floats rendered',await page.locator('[data-testid^="fleet-row-"]').count()===4);
 for(const record of expected){
  const row=page.getByTestId('fleet-row-'+record.wmo);
  check(record.wmo+' updated profile date',await row.locator('[data-field="last_profile_iso"]').innerText()===utc(record.last_profile_iso));
  check(record.wmo+' recent-profile status',await row.locator('[data-field="data_status"]').innerText()==='ACTIVE / RECENT PROFILE');
  check(record.wmo+' zero approximate missed profiles',await row.locator('[data-field="approx_profiles_missed"]').innerText()==='0');
  await row.click();
  const drawer=page.getByTestId('fleet-detail');await drawer.waitFor();
  check(record.wmo+' expected next profile',await drawer.locator('[data-detail-label="Expected Next Profile"] > span').last().innerText()===utc(record.expected_next_profile_iso));
  check(record.wmo+' aggregate-lag warning cleared',await page.getByTestId('profile-history-lag').count()===0);
  if(record.wmo===1902844)await page.screenshot({path:ROOT+'/updated-1902844.png'});
  await page.getByTitle('Close detail',{exact:true}).click();
 }
 check('no browser runtime errors',errors.length===0);
 await page.screenshot({path:ROOT+'/four-recent-profiles.png'});
}finally{
 fs.writeFileSync(ROOT+'/browser-verification.json',JSON.stringify({checks,errors},null,2));
 await browser.close();
}
