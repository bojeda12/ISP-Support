// Pruebas de contratos, límites y transporte HTTP; sin paquetes adicionales.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const core = require('../conversations/static/conversations/demo-core.js');
const origin = 'http://127.0.0.1:8000';

test('sin selector de chats anteriores no se consulta ni sustituye el chat activo', async () => {
  const js = require('node:fs').readFileSync(require('node:path').join(__dirname, '../conversations/static/conversations/demo.js'), 'utf8');
  const code = js.slice(js.indexOf('  async function loadChats('), js.indexOf('  async function sync('));
  const state = {service:{id:1},conversationId:42,history:[{id:1,content:'Saved message'}]};
  const load = new Function('state','byId','api',code+';return loadChats;')(
    state, () => null, () => { throw new Error('Unexpected history management request'); });
  await load();
  assert.equal(state.conversationId,42);
  assert.deepEqual(state.history,[{id:1,content:'Saved message'}]);
});
test('inicio y continuación envían una sola referencia', () => {
  assert.deepEqual(core.chatPayload(' Hola ', 'es', 3, null), {message:'Hola',language:'es',service_id:3});
  assert.deepEqual(core.chatPayload('Hello', 'en', 3, 9), {message:'Hello',language:'en',conversation_id:9});
  for (const args of [['', 'es', 1], ['x'.repeat(2001), 'es', 1], ['Hi', 'fr', 1], ['Hi', 'en', -1]]) assert.throws(() => core.chatPayload(...args));
});
test('adaptive continuation omits forced language; manual switching is explicit', () => {
  assert.deepEqual(core.chatPayload('OK', null, 3, 9),{message:'OK',conversation_id:9});
  assert.equal(core.chatPayload('OK','es',3,9).language,'es');
});
test('límites JPEG/PNG antes de subir', () => {
  assert.ok(core.validPhoto({type:'image/png',size:5*1024*1024}));
  for (const file of [{type:'image/svg+xml',size:1},{type:'image/jpeg',size:0},{type:'image/png',size:5242881}]) assert.equal(core.validPhoto(file),false);
});

test('WebP permitido; HEIC/HEIF requieren conversión y SVG sigue rechazado', () => {
  assert.ok(core.validPhoto({type:'image/webp',size:1024}));
  for (const type of ['image/heic','image/heif','image/svg+xml','image/gif']) assert.equal(core.validPhoto({type,size:1024}),false);
  assert.equal(core.validPhoto({type:'image/webp',size:5242881}),false);
});
test('no permite URLs externas ni rutas fuera de la API', () => {
  assert.equal(core.safePath('/api/photos/1/content/', origin),'/api/photos/1/content/');
  for (const path of ['https://evil.example/api/x','//evil.example/api/x','javascript:alert(1)','/admin/']) assert.throws(() => core.safePath(path,origin));
});
test('cookie y CSRF en POST; sin token público', async () => {
  let captured;
  const result = await core.requestJSON('/api/chat/',{method:'POST',body:'{}'},async (url,options) => {
    captured=options;
    return new Response('{"status":"ok"}',{headers:{'content-type':'application/json'}});
  },'csrf-test',origin);
  assert.equal(result.status,'ok');
  assert.equal(captured.credentials,'same-origin');
  assert.equal(captured.headers['X-CSRFToken'],'csrf-test');
  assert.equal(captured.headers.Authorization,undefined);
  assert.equal(captured.redirect,'error');
});
test('errores HTTP conservan estado y no reintentan mutaciones', async () => {
  for (const status of [400,401,403,413,500,503]) {
    let calls=0;
    await assert.rejects(core.requestJSON('/api/chat/',{method:'POST'},async()=>{calls++;return new Response('',{status});},'csrf',origin),e=>e.status===status);
    assert.equal(calls,1);
  }
});
test('fallos de red y respuestas corruptas se muestran como inciertos', async () => {
  for (const transport of [async()=>{throw Error('offline');},async()=>new Response('<html>login</html>'),async()=>new Response('{',{headers:{'content-type':'application/json'}})]) {
    await assert.rejects(core.requestJSON('/api/chat/',{},transport,'',origin),e=>e.status===0);
  }
});

test('turno multipart vincula texto y foto sin Content-Type manual y conserva referencia única', () => {
  const {File}=require('node:buffer');
  const photo=new File(['fixture'],'rear.webp',{type:'image/webp'});
  const combined=core.turnPayload(' Is this connected? ',photo,null,3,9,'request-test');
  assert.equal(combined.get('message'),'Is this connected?');
  assert.equal(combined.get('photo').name,'rear.webp');
  assert.equal(combined.get('conversation_id'),'9');
  assert.equal(combined.has('service_id'),false);
  assert.equal(combined.get('request_id'),'request-test');
  assert.equal(core.turnPayload('',photo,'es',3,null,'r').get('message'),'');
  assert.equal(core.turnPayload('Hello',null,null,3,null,'r').has('photo'),false);
  assert.throws(()=>core.turnPayload('',null,null,3,null,'r'));
});

test('envío multipart usa CSRF y deja que el navegador defina boundary', async () => {
  const body=core.turnPayload('Hello',null,null,3,null,'request-test');
  await core.requestJSON('/api/chat/turn/',{method:'POST',body},async(url,options)=>{
    assert.equal(options.body,body);
    assert.equal(options.headers['Content-Type'],undefined);
    assert.equal(options.headers['X-CSRFToken'],'csrf');
    return new Response('{}',{headers:{'content-type':'application/json'}});
  },'csrf',origin);
});

test('respuesta rápida conserva pregunta y usa el mismo multipart, también con foto', () => {
  const choice={id:'checked',question_message_id:42,scope:'basic_checks'};
  const body=core.turnPayload('',null,'en',3,9,'once',choice);
  assert.deepEqual(JSON.parse(body.get('quick_reply')),{id:'checked',question_message_id:42});
  assert.equal(body.get('conversation_id'),'9');
  assert.equal(body.has('service_id'),false);
  assert.equal(body.get('request_id'),'once');
  const {File}=require('node:buffer');
  const photo=new File(['fixture'],'rear.png',{type:'image/png'});
  assert.equal(core.turnPayload('',photo,'en',3,9,'once',choice).get('photo').name,'rear.png');
});

test('controles opcionales usan un solo envío y estilos móviles flexibles', () => {
  const fs=require('node:fs');
  const js=fs.readFileSync('conversations/static/conversations/demo.js','utf8');
  assert.match(js,/sendMessage\('', choice\)/);
  assert.match(js,/state\.busy \|\| !state\.confirmed/);
  assert.match(js,/turn\.id,turn\.quickReply/);
  assert.match(js,/button\.type = 'button'/);
  assert.match(js,/core\.turnPayload/);
  assert.doesNotMatch(js,/fetch\(['"]\/api\/(diagnostics|tickets)/);
  const css=fs.readFileSync('conversations/static/conversations/demo.css','utf8');
  assert.match(css,/\.quick-prompts\s*\{[^}]*flex-wrap:wrap/s);
  assert.match(css,/\.contextual-replies button[^}]*white-space: normal/s);
});

test('progreso corresponde a la solicitud pendiente y no usa temporizadores de diagnóstico', () => {
  const fs=require('node:fs');
  const js=fs.readFileSync('conversations/static/conversations/demo.js','utf8');
  assert.match(js,/busy\(true, true\); notice/);
  assert.match(js,/Reviewing your message and connection-check request/);
  assert.match(js,/Revisando tu mensaje y la solicitud de comprobación/);
  assert.match(js,/finally \{ busy\(false\)/);
  assert.doesNotMatch(js,/setTimeout\([^)]*(Checking your connection|Revisando tu conexi)/s);
});

test('sesión demo vencida conserva mensajes visibles y referencia hasta reconectar', async () => {
  const fs=require('node:fs');
  const source=fs.readFileSync('conversations/static/conversations/demo.js','utf8');
  const syncSource=source.slice(source.indexOf('  async function sync()'),source.indexOf('  async function sendMessage('));
  const state={service:{id:1},conversationId:23,history:[{id:187,content:'saved'}],before:100};
  let loaded=false,noticeText='';
  const sync=new Function('state','api','notice','ct','connection','controls','loadHistory','customerMode',syncSource+'; return sync;')(
    state,async()=>({service:null,conversation_id:null}),text=>{noticeText=text;},key=>key,()=>{},()=>{},()=>{loaded=true;},false);
  await sync();
  assert.equal(state.conversationId,23);
  assert.equal(state.history[0].id,187);
  assert.equal(state.service,null);
  assert.equal(loaded,false);
  assert.equal(noticeText,'expired');
});
const fs = require('node:fs');
for (const action of [{action:'new'},{conversation_id:'29'}]) {
  test('selección explícita envía una mutación autorizada: '+JSON.stringify(action), async()=> {
    const js=fs.readFileSync('conversations/static/conversations/demo.js','utf8');
    const code=js.slice(js.indexOf('  async function chooseChat('),js.indexOf("  byId('new-chat')"));
    const state={service:{id:2},busy:false,conversationId:29,history:[{id:211}],pendingTurn:{id:'old'}};
    let calls=[],synced=0;
    const choose=new Function('state','busy','notice','api','clearPhoto','byId','sync','errorMessage',code+';return chooseChat;')(
      state,value=>state.busy=value,()=>{},async(path,options)=>calls.push([path,options]),()=>{},()=>({value:'text'}),async()=>synced++,String);
    await choose(action);
    assert.equal(calls.length,1);assert.equal(calls[0][0],'/demo/conversation/');
    assert.equal(calls[0][1].method,'POST');assert.deepEqual(Object.fromEntries(calls[0][1].body),action);
    assert.equal(synced,1);assert.equal(state.pendingTurn,null);assert.equal(state.busy,false);
    assert.equal(state.history[0].id,211);
  });
}
test('fallo al cambiar de chat conserva historial y no reintenta',async()=> {
  const js=fs.readFileSync('conversations/static/conversations/demo.js','utf8');
  const code=js.slice(js.indexOf('  async function chooseChat('),js.indexOf("  byId('new-chat')"));
  const state={service:{id:2},history:[{id:211}],busy:false};let calls=0,noticeText='';
  const choose=new Function('state','busy','notice','api','clearPhoto','byId','sync','errorMessage',code+';return chooseChat;')(
    state,v=>state.busy=v,t=>noticeText=t,async()=>{calls++;throw Error('HTTP 403');},()=>{},()=>({}),()=>assert.fail('must not sync'),e=>e.message);
  await choose({conversation_id:'29'});assert.equal(calls,1);assert.equal(state.history[0].id,211);assert.equal(noticeText,'HTTP 403');assert.equal(state.busy,false);
});
test('historial activo agrega turnos y conserva fotografías, guías y páginas anteriores',async()=> {
  const js=require('node:fs').readFileSync('conversations/static/conversations/demo.js','utf8');
  const code=js.slice(js.indexOf('  async function loadHistory('),js.indexOf('  let chatOffset'));
  const state={conversationId:30,history:[{id:1,images:['guide']},{id:2,photo:{id:'photo'}}],before:1};
  let rows=[{id:3,content:'customer'},{id:4,ticket:{number:'ISP-TEST'}}];let renders=0;
  const load=new Function('state','api','renderMessages',code+';return loadHistory;')(state,async()=>({conversation_id:30,messages:rows,next_before:null}),()=>renders++);
  await load(true);
  assert.deepEqual(state.history.map(x=>x.id),[1,2,3,4]);assert.deepEqual(state.history[0].images,['guide']);assert.equal(state.history[1].photo.id,'photo');
  rows=[{id:0,content:'older'}];await load(true);assert.deepEqual(state.history.map(x=>x.id),[0,1,2,3,4]);assert.equal(renders,2);
});
test('vista cliente no sustituye silenciosamente una conversación activa',async()=> {
  const js=require('node:fs').readFileSync('conversations/static/conversations/demo.js','utf8');
  const code=js.slice(js.indexOf('  async function sync()'),js.indexOf('  async function sendMessage('));
  const state={service:{id:1},conversationId:30,history:[{id:1}],language:'es'};let notice='';
  const sync=new Function('state','api','notice','ct','connection','controls','customerMode',code+';return sync;')(state,async()=>({service:{id:2},conversation_id:31}),x=>notice=x,x=>x,()=>{},()=>{},true);
  assert.equal(await sync(),false);assert.equal(state.conversationId,30);assert.equal(state.service.id,1);assert.equal(state.history.length,1);assert.equal(state.review,true);assert.match(notice,/permanece visible/);
});
test('reconectar el mismo caso conserva todas las páginas cargadas',async()=> {
  const js=require('node:fs').readFileSync('conversations/static/conversations/demo.js','utf8');
  const code=js.slice(js.indexOf('  async function sync()'),js.indexOf('  async function sendMessage('));
  const history=Array.from({length:75},(_,i)=>({id:i+1}));
  const state={service:null,conversationId:30,history,before:1,language:'es'};
  const nodes=new Map();const byId=id=>{if(!nodes.has(id))nodes.set(id,{});return nodes.get(id);};let loaded=0;
  const sync=new Function('state','api','notice','ct','connection','controls','customerMode','byId','applyLanguage','loadHistory','loadChats','t',code+';return sync;')(
    state,async()=>({service:{id:1},conversation_id:30,language:'es',language_confirmed:true,conversation_status:'OPEN'}),()=>{},x=>x,()=>{},()=>{},true,byId,()=>{},async()=>loaded++,async()=>{},x=>x);
  await sync();assert.equal(state.conversationId,30);assert.equal(state.service.id,1);assert.equal(state.history,history);assert.equal(state.history.length,75);assert.equal(state.before,1);assert.equal(loaded,1);
});
