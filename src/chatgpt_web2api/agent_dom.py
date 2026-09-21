"""Read literal protocol code blocks; reject lossy inline Markdown rendering."""

AGENT_TEXT_JS = r"""
function web2apiAgentText(last) {
  if (!last) return {text:'',unsafe_markup:false,literal:false};
  var md=last.querySelector('.markdown')||last;
  var code=Array.from(md.querySelectorAll('pre code')).find(
    e=>(e.textContent||'').trim().startsWith('<web2api_response')
  );
  if (code) return {text:code.textContent||'',unsafe_markup:false,literal:true};
  return {text:md.textContent||'',literal:false,unsafe_markup:!!md.querySelector(
    'em,strong,a,del,s,code,table,ul,ol,h1,h2,h3,h4,blockquote'
  )};
}
"""
