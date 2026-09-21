const fs=require('fs'),vm=require('vm'),assert=require('assert/strict'),os=require('os'),path=require('path');
const root=process.env.CONTINUE_EXTENSION_ROOT;
if(!root)throw Error('Set CONTINUE_EXTENSION_ROOT to the managed extension');
const core=fs.readFileSync(root+'/out/extension.js','utf8');
const gui=fs.readFileSync(root+'/gui/assets/index.js','utf8');
const helper=require(root+'/out/continue-full-access.local.cjs');
const marker=core.indexOf('"tools/evaluatePolicy",');
const start=core.indexOf('async ({ data: { toolName, basePolicy, parsedArgs, processedArgs } }) => {',marker);
const end=core.indexOf('\n          }\n        );',start)+'\n          }'.length;
assert(start>0&&end>start);
const handler=core.slice(start,end);
const guiStart=gui.indexOf('async function kzt('),guiEnd=gui.indexOf('async function _zt(',guiStart);
assert(guiStart>0&&guiEnd>guiStart);
const ui=vm.runInNewContext('('+gui.slice(guiStart,guiEnd)+')',{x2e:()=>false,Xk:'allowedWithPermission'});
const toolNames=JSON.parse(fs.readFileSync(require('path').join(__dirname,'continue-tool-names.json'),'utf8'));
const tools=toolNames.map(name=>({function:{name},defaultToolPolicy:'allowedWithPermission',evaluateToolCallPolicy:()=>{throw Error('Secondary evaluator must not run under explicit full access');}}));
const evaluate=vm.runInNewContext('('+handler+')',{require:()=>helper,configHandler:{loadConfig:async()=>({config:{tools}})}});
let checks=0;
(async()=>{
 assert(helper.isEnabled());checks++;
 for(const name of toolNames){
  for(const base of ['allowedWithoutPermission','allowedWithPermission','disabled']){
   const call={toolCall:{function:{name}},parsedArgs:{command:"$env:PATH='C:\\tools;'+$env:PATH; & 'C:\\tools\\php.exe' --version"},processedArgs:{resolvedPath:{isWithinWorkspace:false}}};
   const result=await ui({request:async(_,{toolName,basePolicy,parsedArgs,processedArgs})=>({status:'success',content:await evaluate({data:{toolName,basePolicy,parsedArgs,processedArgs}})})},tools,call,{[name]:base});
   assert.equal(result.policy,'allowedWithoutPermission');checks++;
  }
 }
 // Disabled mode delegates to the original evaluator and preserves the UI's Ask/Disabled policies.
 const fallback=vm.runInNewContext('('+handler+')',{require:()=>({isEnabled:()=>false}),configHandler:{loadConfig:async()=>({config:{tools:[{function:{name:'run_terminal_command'},evaluateToolCallPolicy:()=> 'allowedWithPermission'}]}})}});
 assert.equal((await fallback({data:{toolName:'run_terminal_command',basePolicy:'allowedWithoutPermission',parsedArgs:{},processedArgs:{}}})).policy,'allowedWithPermission');checks++;
 const tmp=fs.mkdtempSync(path.join(os.tmpdir(),'continue-policy-check-'));
 const file=path.join(tmp,'flag.json');
 for(const contents of ['{}','{"enabled":false,"scope":"all-configured-tools"}','{"enabled":"true","scope":"all-configured-tools"}','bad json']){
  fs.writeFileSync(file,contents);assert.equal(helper.isEnabled(file),false);checks++;
 }
 fs.unlinkSync(file);fs.rmdirSync(tmp);
 const report={passed:true,checks,tools:toolNames.length,usesInstalledCoreHandler:true,usesInstalledGuiResolver:true,terminalExecutionPerformed:false,mode:'all-configured-tools',disabledModePreservesOriginalPolicy:true};
 console.log(JSON.stringify(report));
})().catch(e=>{console.error(e);process.exitCode=1});
