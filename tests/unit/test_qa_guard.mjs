import test from "node:test";
import assert from "node:assert/strict";
import net from "node:net";
import { assertPortsFree, ownsListener, startOwned, stopOwned, runGuarded, waitForServices } from "../../scripts/qa_process_guard.mjs";
const delay = ms => new Promise(r => setTimeout(r, ms));
async function port() { const s = net.createServer(); await new Promise(r => s.listen(0, "127.0.0.1", r)); const p = s.address().port; await new Promise(r => s.close(r)); return p; }
async function server(p) {
 const child = startOwned(process.execPath, ["-e", `require('net').createServer(()=>{}).listen(${p},'127.0.0.1')`], {stdio:'ignore'});
 for(let i=0;i<100&&!ownsListener(child,p);i++) await delay(20);
 assert.equal(ownsListener(child,p),true); return child;
}
test('occupied port rejected and unrelated owner is not killed', async () => {
 const p=await port(), other=await server(p);
 try { await assert.rejects(assertPortsFree([p]), /unavailable/); assert.equal(ownsListener(other,p),true); }
 finally { await stopOwned([{child:other}]); }
});
test('startup failure and unrelated listener cannot pass ownership', async () => {
 const p=await port(), other=await server(p), failed=startOwned('/definitely/not/a/program',[],{stdio:'ignore'});
 try { await assert.rejects(waitForServices([{child:failed,port:p,name:'fake'}], 'http://127.0.0.1:1',1000), /failed/); assert.equal(ownsListener(failed,p),false); }
 finally { await stopOwned([{child:failed},{child:other}]); }
});
test('lost listener interrupts guarded checks and owned cleanup works', async () => {
 const p=await port(), owned=await server(p), entries=[{child:owned,port:p,name:'owned'}];
 const killer=setTimeout(()=>owned.kill('SIGTERM'),250);
 try { await assert.rejects(runGuarded(process.execPath,['-e',"process.on('SIGTERM',()=>{}); setTimeout(()=>{},10000)"],{stdio:'ignore'},entries)); }
 finally { clearTimeout(killer); await stopOwned(entries); }
 assert.equal(ownsListener(owned,p),false);
});
