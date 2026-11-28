// Optional real Chromium acceptance test. Run with Node + Playwright installed.
// NODE_PATH may point to an isolated temporary Playwright installation.
const {chromium}=require("playwright");
const assert=require("node:assert/strict");
const {spawn}=require("node:child_process");
const {createInterface}=require("node:readline");
const path=require("node:path");
const fs=require("node:fs/promises");
const dir=__dirname;
async function main(){
 const child=spawn("python3",[path.join(dir,"journal_browser_fixture.py")],{
  env:{...process.env,PYTHONPATH:path.join(dir,"../rootfs/app")},stdio:["pipe","pipe","inherit"]
 });
 const lines=createInterface({input:child.stdout})[Symbol.asyncIterator]();
 const command=async cmd=>{child.stdin.write(cmd+"\n");assert.equal((await lines.next()).value,"ok")};
 let browser;
 try{
  const port=(await lines.next()).value;assert.match(port,/^\d+$/);
  browser=await chromium.launch({headless:true});
  const page=await browser.newPage({viewport:{width:1440,height:900}});
  const errors=[];page.on("pageerror",e=>errors.push(e.message));
  const start=Date.now();
  await page.goto("http://127.0.0.1:"+port+"/log");
  await page.waitForFunction(()=>document.querySelectorAll(".entry").length===3000);
  console.log("Initial 3000 rows, large detail payloads:",Date.now()-start,"ms");
  assert.match(await page.locator(".entry").first().innerText(),/v0\.1\.9/);
  assert.match(await page.locator(".entry").last().innerText(),/TEST-2999/);
  assert.equal(await page.locator("#count").innerText(),"3000 / 3000");
  await page.locator("#follow").uncheck();
  await page.locator("#rows").evaluate(e=>e.scrollTop=0);
  await page.locator("#search").fill("TEST-0001");
  assert.equal(await page.locator(".entry:visible").count(),1);
  await page.locator(".entry:visible summary").click();
  await page.waitForFunction(()=>document.querySelector(".entry:not([hidden]) pre").textContent.includes("detail_0"));
  await page.locator("#search").fill("");
  await page.locator("#level").selectOption("warning");
  assert.equal(await page.locator(".entry:visible").count(),299);
  await page.locator("#level").selectOption("");
  await page.locator("#language").selectOption("en");
  await page.waitForFunction(()=>document.querySelectorAll(".entry").length===3000&&document.querySelector(".entry").textContent.includes("APPLICATION START"));
  assert.match(await page.locator(".entry").last().innerText(),/awaiting probe/);
  const dl=page.waitForEvent("download");
  await page.locator("#export").click();
  const download=await dl;
  assert.match(download.suggestedFilename(),/^digitalhouses_system_globals_app_.*\.log$/);
  const text=await fs.readFile(await download.path(),"utf8");
  assert.equal(text.trimEnd().split("\n").length,3000);
  assert.match(text,/TEST-2999/);
  await command("append");
  await page.waitForFunction(()=>document.querySelector(".entry:last-child").textContent.includes("NEW-ROW"));
  assert.equal(await page.locator(".entry").count(),3000);
  assert.match(await page.locator(".entry").first().innerText(),/TEST-0001/);
  await page.locator("#language").selectOption("ru");
  await page.waitForFunction(()=>document.querySelectorAll(".entry").length===3000&&document.querySelector(".entry").textContent.includes("ожидание проверки"));
  const home=await browser.newPage();
  const homeErrors=[];home.on("pageerror",e=>homeErrors.push(e.message));
  await home.goto("http://127.0.0.1:"+port+"/");
  await home.waitForFunction(()=>document.querySelector("#mode").textContent==="День");
  await home.locator('input[name="night_start"]').fill("21:30");
  // Wait until the initial notification baseline has been established.
  await home.waitForTimeout(500);
  await command("mode");
  await home.waitForFunction(()=>document.querySelector(".dh-toast-stack").textContent.includes("Ночной режим включён"));
  await home.waitForFunction(()=>document.querySelector("#mode").textContent==="Ночь");
  await home.waitForTimeout(3500);
  assert.equal(await home.locator('input[name="night_start"]').inputValue(),"21:30");
  assert.match(await home.locator(".dh-toast-stack").innerText(),/Ночной режим включён/);
  assert.deepEqual(homeErrors,[]);
  await home.close();
  console.log("PASS: toast survives live refresh; dirty form retained");
  await command("fail");
  await page.waitForFunction(()=>document.querySelector("#clear").disabled&&document.querySelector("#export").disabled&&document.querySelectorAll(".entry").length===0);
  assert.equal(await page.locator(".entry").count(),0);
  assert.match(await page.locator("#status").innerText(),/SQLite недоступна/);
  assert.deepEqual(errors,[]);
  console.log("PASS: full 3000 rows, search, severity, lazy details, RU/EN, full .log, eviction, SQLite failure");
 }finally{
  if(browser)await browser.close();
  child.stdin.end("exit\n");
 }
}
main().catch(e=>{console.error(e);process.exitCode=1});
