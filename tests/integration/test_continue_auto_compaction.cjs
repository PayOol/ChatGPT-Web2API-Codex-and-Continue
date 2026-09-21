"use strict";
const assert=require('assert/strict'),fs=require('fs'),vm=require('vm');
const root=process.env.CONTINUE_EXTENSION_ROOT;
if(!root)throw Error('Set CONTINUE_EXTENSION_ROOT to the managed extension');
const helper=require(root+'/out/continue-auto-compaction.local.cjs');
const core=fs.readFileSync(root+'/out/extension.js','utf8'),gui=fs.readFileSync(root+'/gui/assets/index.js','utf8');
const nativeStart=core.indexOf('async function compactConversation({');
const nativeEnd=core.indexOf('\nvar ',nativeStart);
const native=vm.runInNewContext('('+core.slice(nativeStart,nativeEnd).trim()+')',{AbortController,stripImages:x=>x});
let checks=[];
function ok(name,fn){fn();checks.push(name);}
const history=Array.from({length:30},(_,i)=>({message:{id:'message'+i,role:i%2?'assistant':'user',content:(i%2?'Verified result ':'User instruction ')+i+' '+ 'test context '.repeat(80)},contextItems:[]}));
function input(id,h=history){return {sessionId:id,history:h,contextPercentage:.8,didPrune:false};}
let calls=0,captured;
const deps={compactConversation:native,model:{chat:async(messages,signal,options)=>{calls++;captured={messages,options};return {role:'assistant',content:'Objective: finish the task. Verified results and pending work retained.'};}}};
const opts={enabled:true};
(async()=>{
 const before=JSON.stringify(history);
 const low=await helper.maybeCompact({...input('low'),contextPercentage:.6},deps,opts);
 ok('No summary below threshold',()=>{assert.equal(low,null);assert.equal(calls,0);});
 const disabled=await helper.maybeCompact(input('disabled'),deps,{enabled:false});
 ok('Explicit disable respected',()=>assert.equal(disabled,null));
 const result=await helper.maybeCompact(input('first'),deps,opts);
 ok('Native compactor integrated and recent messages retained',()=>{assert.equal(calls,1);assert.equal(result.index,21);assert.equal(history.length-result.index-1,8);assert.ok(result.summaryChars<result.originalChars);});
 ok('Original history unchanged',()=>assert.equal(JSON.stringify(history),before));
 ok('Summary generation bounded and tool instructions excluded',()=>{assert.equal(captured.options.maxTokens,2500);assert.equal(captured.options.tools,undefined);assert.match(captured.messages.at(-1).content,/Do not execute tools/);});
 const cached=await helper.maybeCompact(input('first'),deps,opts);
 ok('Repeated identical history uses cached summary',()=>{assert.equal(calls,1);assert.deepEqual(cached,result);});
 const changed=structuredClone(history);changed[0].message.content+=' changed';
 const cooldown=await helper.maybeCompact(input('first',changed),deps,opts);
 ok('Cooldown prevents immediate new summary',()=>{assert.equal(cooldown,null);assert.equal(calls,1);});
 const prior=structuredClone(history);prior[21].conversationSummary='Previous verified work';
 const repeated=await helper.maybeCompact(input('prior',prior),deps,opts);
 ok('No new summary until enough new messages',()=>assert.equal(repeated,null));
 const grown=prior.concat(Array.from({length:10},(_,i)=>({message:{role:i%2?'assistant':'user',content:'New progress '.repeat(100)},contextItems:[]})));
 await helper.maybeCompact(input('grown',grown),deps,opts);
 ok('Previous summary incorporated into next summary',()=>assert.match(captured.messages[0].content,/Previous verified work/));
 const active=structuredClone(history);active[15].message.toolCalls=[{id:'open',function:{name:'read_file',arguments:'{}'}}];
 ok('Boundary does not cross unfinished tool call',()=>assert.equal(helper.boundary(active,{keepRecentMessages:8,minAdvance:8}),13));
 active[16].message={role:'tool',toolCallId:'open',content:'File read result'};
 ok('Closed tool pair can be summarized',()=>assert.equal(helper.boundary(active,{keepRecentMessages:8,minAdvance:8}),21));
 const original=[{message:{role:'assistant',content:[{type:'text',text:'analysis'},{type:'image_url',image_url:{url:'data:image/png;base64,TEST'}}],toolCalls:[{id:'done'}]},toolCallStates:[{toolCallId:'done',status:'done',output:[{content:'Confirmed execution output'}]}],contextItems:[{content:'attached evidence'}]}];
 const prepared=helper.prepare(original);
 ok('Attachments sanitized, stored tool result recovered without mutation',()=>{assert.equal(prepared.length,2);assert.equal(prepared[1].message.content,'Confirmed execution output');assert.match(prepared[0].message.content,/attached evidence/);assert.ok(!prepared[0].message.content.includes('base64'));assert.ok(Array.isArray(original[0].message.content));});
 const onlyUser=structuredClone(history);for(let i=1;i<onlyUser.length;i++)onlyUser[i].message.role='assistant';
 const retained=await helper.maybeCompact(input('verbatim',onlyUser),deps,opts);
 ok('Latest user request retained verbatim if within summarized prefix',()=>assert.ok(retained.summary.endsWith(onlyUser[0].message.content)));
 let unblock;const slow={...deps,model:{chat:()=>new Promise(resolve=>unblock=()=>resolve({role:'assistant',content:'Summary of work'}))}};
 const pending=helper.maybeCompact(input('concurrent'),slow,opts);
 const duplicate=await helper.maybeCompact(input('concurrent'),slow,opts);
 unblock();await pending;
 ok('Concurrent duplicate does not create a second request',()=>assert.equal(duplicate,null));
 const failed=await helper.maybeCompact(input('failure'),{...deps,model:{chat:async()=>{throw Error('test');}}},opts);
 ok('Failed summary preserves source history',()=>{assert.equal(failed.skipped,'summary_failed');assert.equal(JSON.stringify(history),before);});
 const huge=await helper.maybeCompact(input('huge'),{...deps,model:{chat:async()=>({content:'a'.repeat(12001)})}},opts);
 ok('Excessive summary rejected',()=>assert.equal(huge.skipped,'summary_failed'));
 const tiny=history.map(x=>({message:{role:x.message.role,content:'x'}}));
 const notReduced=await helper.maybeCompact(input('no-reduction',tiny),{...deps,model:{chat:async()=>({content:'a'.repeat(4000)})}},opts);
 ok('Non-reducing summary rejected',()=>assert.equal(notReduced.skipped,'summary_failed'));
 const prune=await helper.maybeCompact({...input('pruned'),contextPercentage:.2,didPrune:true},deps,opts);
 ok('Native pruning also triggers compaction',()=>assert.ok(prune.summary));
 const handlerStart=core.indexOf('on2("llm/compileChat", async (msg) => {');
 const handlerEnd=core.indexOf('\n        TTS.messenger',handlerStart);
 const handlerText=core.slice(handlerStart,handlerEnd);
 async function compileCase(error,summary){
  let handler,received;
  const model={compileChatMessages:()=>{if(error)throw Error(error);return {compiledChatMessages:['original'],didPrune:false,contextPercentage:.8};}};
  const ctx={configHandler:{loadConfig:async()=>({config:{selectedModelByRole:{chat:model}}})}};
  vm.runInNewContext('(function(){'+handlerText+'}).call(ctx)',{ctx,on2:(_name,fn)=>handler=fn,require:()=>({maybeCompact:async i=>{received=i;return summary;}}),compactConversation:native});
  return {result:await handler({data:{messages:[],options:{},autoCompaction:{sessionId:'core',history}}}),received};
 }
 const coreOk=await compileCase(null,{summary:'summary',index:21});
 ok('Installed core handler supplies compaction request and preserves compiled fields',()=>{assert.equal(coreOk.result.autoCompaction.summary,'summary');assert.equal(coreOk.result.contextPercentage,.8);assert.equal(coreOk.received.sessionId,'core');});
 const saturated=await compileCase('Not enough context available',{summary:'summary',index:21});
 ok('Already saturated context can compact before compilation succeeds',()=>{assert.equal(saturated.result.autoCompaction.summary,'summary');assert.equal(saturated.received.didPrune,true);});
 await assert.rejects(()=>compileCase('Not enough context available',null),/Not enough context/);checks.push('Unrecoverable context error remains explicit');
 await assert.rejects(()=>compileCase('Invalid model configuration',null),/Invalid model/);checks.push('Unrelated compile errors are not masked');
 // Execute actual installed GUI response branch, preserving the real guard/action sequence.
 const start=gui.indexOf('if(x.status==="success"&&x.content.autoCompaction)');
 const end=gui.indexOf('if(x.status==="error")',start);
 const branch=gui.slice(start,end);
 async function guiCase(change,afterSave){
  const controller=new AbortController();
  const a={session:{id:'session',history:structuredClone(history),streamAborter:controller,isStreaming:true}};
  let state={session:{...a.session,history:structuredClone(history)},draft:'preserved draft'};const events=[];
  if(change)change(state,controller);
  const action=type=>payload=>({type,payload});
  const dispatch=async event=>{events.push(event);if(event.type==='update'){const{index,updates}=event.payload;state.session.history[index]={...state.session.history[index],...updates};}if(event.type==='save'&&afterSave)afterSave(state,controller);return event;};
  await vm.runInNewContext('(async()=>{'+branch+'})()',{
   x:{status:'success',content:{autoCompaction:{index:21,summary:'verified summary'}}},a,i:()=>state,n:dispatch,e:undefined,t:7,
   compactionHistory:a.session.history,Fen:action('update'),Jen:action('pruned'),Yen:action('percentage'),ju:action('save'),k8e:action('resume'),Qh:x=>x
  });return {events,state};
 }
 const applied=await guiCase();
 ok('GUI saves summary and resumes same task exactly once',()=>{assert.equal(applied.events.filter(e=>e.type==='resume').length,1);assert.deepEqual(JSON.parse(JSON.stringify(applied.events.find(e=>e.type==='resume').payload)),{depth:7,skipLocalCompaction:true});assert.equal(applied.state.session.id,'session');assert.equal(applied.state.draft,'preserved draft');assert.deepEqual(JSON.parse(JSON.stringify(applied.state.session.history.slice(22))),history.slice(22));});
 ok('Saving does not open new Continue session or generate title',()=>assert.deepEqual(JSON.parse(JSON.stringify(applied.events.find(e=>e.type==='save').payload)),{openNewSession:false,generateTitle:false}));
 for(const [name,change] of [
  ['Switched session',s=>s.session.id='different'],
  ['Stopped task',s=>s.session.isStreaming=false],
  ['Aborted stream',(_s,c)=>c.abort()],
  ['Edited history',s=>s.session.history[29].message.content='changed'],
  ['New history item',s=>s.session.history.push({message:{role:'user',content:'new'}})]
 ]){const r=await guiCase(change);ok(name+' cannot apply stale summary',()=>assert.equal(r.events.length,0));}
 const stoppedDuringSave=await guiCase(null,s=>s.session.isStreaming=false);
 ok('Stop during save prevents resume',()=>assert.equal(stoppedDuringSave.events.filter(e=>e.type==='resume').length,0));
 ok('Full access patches retained',()=>{assert.ok(core.includes('continue-full-access.local.cjs'));assert.ok(gui.includes('o.content.fullAccess===true'));});
 console.log(JSON.stringify({passed:checks.length,checks},null,2));
})().catch(e=>{console.error(e);process.exitCode=1;});
