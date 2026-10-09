// Pruebas de contratos, límites y transporte HTTP; sin paquetes adicionales.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const core = require('../conversations/static/conversations/demo-core.js');
const origin = 'http://127.0.0.1:8000';
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
