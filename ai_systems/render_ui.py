"""Self-contained deutsche SPA für AI-Systems: eine HTML-Seite mit Inline-CSS
und Vanilla-JS (Hash-Router), gerendert vom Server — kein Build-Step, kein CDN.

Die Logo-SVG-Funktion ist bewusst aus scripts/render_dashboard.py KOPIERT
(nicht importiert), damit ai_systems/ ohne das Team-Board-Projekt lauffähig
bleibt. Das Logo pulsiert, solange ein API-Aufruf läuft (Busy-Zähler im JS).
"""
from __future__ import annotations

import math


def logo_svg(size: int = 40, cls: str = "") -> str:
    """Firmenlogo als Inline-SVG: 8 Ringsegmente (teal) + 1 rotes + innere Scheibe.

    Kopie von scripts/render_dashboard.py:pcb_logo_svg (self-contained)."""
    cx = cy = 100.0
    r_out, r_in, disc = 94.0, 54.0, 38.0
    pad = 5.0
    red_index = 1
    segs = []
    for k in range(8):
        a0 = math.radians(k * 45 + pad - 90)
        a1 = math.radians((k + 1) * 45 - pad - 90)
        x0o, y0o = cx + r_out * math.cos(a0), cy + r_out * math.sin(a0)
        x1o, y1o = cx + r_out * math.cos(a1), cy + r_out * math.sin(a1)
        x0i, y0i = cx + r_in * math.cos(a0), cy + r_in * math.sin(a0)
        x1i, y1i = cx + r_in * math.cos(a1), cy + r_in * math.sin(a1)
        d = (f"M{x0o:.2f},{y0o:.2f} A{r_out},{r_out} 0 0 1 {x1o:.2f},{y1o:.2f} "
             f"L{x1i:.2f},{y1i:.2f} A{r_in},{r_in} 0 0 0 {x0i:.2f},{y0i:.2f} Z")
        color = "pcb-red" if k == red_index else "pcb-teal"
        segs.append(f'<path class="pcb-seg {color}" style="--i:{k}" d="{d}"/>')
    disc_el = f'<circle class="pcb-teal pcb-disc" cx="{cx}" cy="{cy}" r="{disc}"/>'
    return (f'<svg class="pcb-logo {cls}" viewBox="0 0 200 200" width="{size}" height="{size}" '
            f'aria-label="AI-Systems" role="img">{"".join(segs)}{disc_el}</svg>')


_CSS = """
:root{--bg:#f4f6f8;--card:#fff;--text:#1c2430;--muted:#66707d;--line:#e2e7ec;
  --teal:#0e7c86;--red:#d64541;--ok:#2e9e5b;--warn:#d9a01f;--err:#d64541;
  --chip:#eef3f6;--shadow:0 1px 3px rgba(20,30,40,.08)}
:root[data-theme=dark]{--bg:#12181f;--card:#1b232d;--text:#e8edf2;--muted:#93a0ad;
  --line:#2a3542;--chip:#232e3a;--shadow:0 1px 3px rgba(0,0,0,.4)}
*{box-sizing:border-box}
body{margin:0;font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif;
  background:var(--bg);color:var(--text)}
header{display:flex;align-items:center;gap:12px;padding:12px 20px;
  background:var(--card);border-bottom:1px solid var(--line);position:sticky;top:0;z-index:5}
header h1{font-size:19px;margin:0}
header .sub{color:var(--muted);font-size:13px}
header .spacer{flex:1}
.badge{background:var(--chip);color:var(--muted);border-radius:999px;
  padding:2px 10px;font-size:12px}
button{font:inherit;border:1px solid var(--line);background:var(--card);
  color:var(--text);border-radius:8px;padding:7px 14px;cursor:pointer}
button:hover{border-color:var(--teal)}
button.primary{background:var(--teal);border-color:var(--teal);color:#fff}
button.danger{color:var(--err);border-color:var(--err)}
button:disabled{opacity:.5;cursor:default}
main{max-width:1100px;margin:0 auto;padding:20px}
.crumbs{margin:0 0 14px;font-size:13px;color:var(--muted)}
.crumbs a{color:var(--teal);text-decoration:none}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:14px}
.tile,.card{background:var(--card);border:1px solid var(--line);border-radius:12px;
  padding:16px;box-shadow:var(--shadow)}
.tile{cursor:pointer;transition:transform .08s}
.tile:hover{transform:translateY(-2px);border-color:var(--teal)}
.tile .icon{font-size:30px}
.tile h3{margin:6px 0 2px;font-size:16px}
.tile .meta{color:var(--muted);font-size:13px}
.tile.new{display:flex;align-items:center;justify-content:center;color:var(--muted);
  border-style:dashed;min-height:110px}
.section{margin:22px 0}
.section h2{font-size:16px;margin:0 0 10px}
.agent-card{display:flex;flex-direction:column;gap:6px}
.agent-card .row{display:flex;align-items:center;gap:8px}
.agent-card h3{margin:0;font-size:15px;flex:1;cursor:pointer}
.agent-card h3:hover{color:var(--teal)}
.role{color:var(--muted);font-size:13px}
.dot{width:10px;height:10px;border-radius:50%;display:inline-block;background:var(--muted)}
.dot.success{background:var(--ok)}.dot.error{background:var(--err)}
.dot.running,.dot.waiting{background:var(--warn)}
.switch{position:relative;width:38px;height:20px;flex:none}
.switch input{display:none}
.switch span{position:absolute;inset:0;background:var(--chip);border:1px solid var(--line);
  border-radius:999px;transition:.15s}
.switch span:before{content:"";position:absolute;width:14px;height:14px;border-radius:50%;
  background:var(--muted);top:2px;left:2px;transition:.15s}
.switch input:checked+span{background:var(--teal);border-color:var(--teal)}
.switch input:checked+span:before{background:#fff;left:19px}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line)}
th{color:var(--muted);font-weight:600}
.chips{display:flex;flex-wrap:wrap;gap:8px}
.chip{background:var(--chip);border-radius:999px;padding:4px 12px;font-size:13px;
  display:flex;align-items:center;gap:6px}
.chip .x{cursor:pointer;color:var(--muted)}
.chip .x:hover{color:var(--err)}
label.check{display:flex;align-items:center;gap:8px;padding:4px 0;cursor:pointer}
.hint{color:var(--muted);font-size:12.5px}
input[type=text]{font:inherit;background:var(--bg);color:var(--text);
  border:1px solid var(--line);border-radius:8px;padding:7px 10px}
.formrow{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-top:8px}
dialog{border:1px solid var(--line);border-radius:14px;background:var(--card);
  color:var(--text);padding:0;width:min(680px,94vw);box-shadow:0 10px 40px rgba(0,0,0,.25)}
dialog::backdrop{background:rgba(10,15,20,.45)}
.dlg-head{display:flex;align-items:center;gap:10px;padding:14px 18px;
  border-bottom:1px solid var(--line)}
.dlg-head h3{margin:0;font-size:16px;flex:1}
.dlg-model{display:flex;align-items:center;gap:8px;flex-wrap:wrap;padding:8px 18px;
  border-bottom:1px solid var(--line);font-size:13px;color:var(--muted)}
.dlg-model input{font:inherit;padding:5px 8px;border-radius:7px;border:1px solid var(--line);
  background:var(--bg);color:var(--text);min-width:220px}
.dlg-model button{padding:5px 10px;font-size:13px}
.dlg-body{padding:16px 18px;max-height:56vh;overflow:auto}
.dlg-foot{padding:12px 18px;border-top:1px solid var(--line);display:flex;gap:8px}
.dlg-foot input{flex:1}
.msg{margin:8px 0;display:flex}
.msg .bubble{max-width:85%;padding:9px 13px;border-radius:14px;white-space:pre-wrap}
.msg.user{justify-content:flex-end}
.msg.user .bubble{background:var(--teal);color:#fff;border-bottom-right-radius:4px}
.msg.assistant .bubble{background:var(--chip);border-bottom-left-radius:4px}
.proposal{border:1px solid var(--teal);border-radius:12px;padding:12px;margin:10px 0}
.proposal h4{margin:0 0 4px}
.proposal details{margin-top:8px}
.proposal pre{background:var(--bg);padding:10px;border-radius:8px;overflow:auto;
  font-size:12px;max-height:240px}
.errorcard{border:1px solid var(--err);border-radius:12px;padding:12px;margin:10px 0;
  color:var(--err);font-size:13.5px}
.errorcard ul{margin:6px 0 0;padding-left:18px}
.pcb-logo .pcb-teal{fill:var(--teal)}
.pcb-logo .pcb-red{fill:var(--red)}
.pcb-logo.pulsing .pcb-seg{animation:pulse 1.2s infinite;animation-delay:calc(var(--i)*.12s)}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.25}}
.empty{color:var(--muted);text-align:center;padding:30px 0}
a{color:var(--teal)}
"""

_JS = r"""
'use strict';
const $=s=>document.querySelector(s);
const esc=t=>String(t??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

/* --- Busy-Anzeige: Logo pulsiert, solange API-Aufrufe laufen --------------- */
let busy=0;
function setBusy(on){busy+=on?1:-1;$('#logo').classList.toggle('pulsing',busy>0);}
async function api(path,opts){
  setBusy(true);
  try{
    const resp=await fetch(path,Object.assign({headers:{'Content-Type':'application/json'}},opts));
    // Antwort defensiv lesen: bei Server-/Proxy-Fehlern kann der Body Text statt
    // JSON sein (z. B. "Internal Server Error") — dann keinen kryptischen
    // JSON-Parserfehler werfen, sondern eine verständliche Meldung bauen.
    let data={};
    if(resp.status!==204){
      const raw=await resp.text();
      if(raw){
        try{data=JSON.parse(raw);}
        catch{data={error:(resp.ok?raw:('Serverfehler '+resp.status+': '+raw.slice(0,200)))};}
      }
    }
    if(!resp.ok){const err=new Error(data.error||('Fehler '+resp.status));err.data=data;throw err;}
    return data;
  }finally{setBusy(false);}
}

/* --- Theme ------------------------------------------------------------------ */
function initTheme(){
  const saved=localStorage.getItem('ai-systems-theme');
  if(saved)document.documentElement.dataset.theme=saved;
  else if(matchMedia('(prefers-color-scheme: dark)').matches)
    document.documentElement.dataset.theme='dark';
}
function toggleTheme(){
  const cur=document.documentElement.dataset.theme==='dark'?'light':'dark';
  document.documentElement.dataset.theme=cur;
  localStorage.setItem('ai-systems-theme',cur);
}

/* --- Router ------------------------------------------------------------------ */
async function route(){
  const h=location.hash||'#/';
  try{
    let m;
    if((m=h.match(/^#\/abteilung\/(\d+)/)))await viewDepartment(+m[1]);
    else if((m=h.match(/^#\/agent\/(\d+)/)))await viewAgent(+m[1]);
    else await viewOverview();
  }catch(e){$('#main').innerHTML='<div class="empty">'+esc(e.message)+'</div>';}
}
window.addEventListener('hashchange',route);

/* --- Übersicht: Abteilungs-Kacheln ------------------------------------------- */
async function viewOverview(){
  const deps=await api('/api/departments');
  let html='<div class="grid">';
  for(const d of deps){
    html+=`<div class="tile" onclick="location.hash='#/abteilung/${d.id}'">
      <div class="icon">${esc(d.icon)}</div><h3>${esc(d.name)}</h3>
      <div class="meta">${d.agent_count} Mitarbeiter${d.agent_count===1?'':''} · ${esc(d.description)}</div>
    </div>`;
  }
  html+='<div class="tile new" onclick="createDepartment()">＋ Abteilung anlegen</div></div>';
  if(!deps.length)html+='<p class="empty">Noch keine Abteilungen — lege die erste an, um Mitarbeiter (Agenten) einzustellen.</p>';
  $('#main').innerHTML=html;
}
async function createDepartment(){
  const name=prompt('Name der neuen Abteilung (z. B. Vertrieb):');
  if(!name)return;
  const icon=prompt('Emoji-Icon für die Abteilung (leer = 🏢):')||'🏢';
  const description=prompt('Kurzbeschreibung (optional):')||'';
  try{await api('/api/departments',{method:'POST',body:JSON.stringify({name,icon,description})});}
  catch(e){alert(e.message);}
  route();
}

/* --- Abteilungs-Ansicht -------------------------------------------------------- */
async function viewDepartment(id){
  const [deps,agents,conns,rules]=await Promise.all([
    api('/api/departments'),api('/api/agents?department_id='+id),
    api(`/api/departments/${id}/connectors`),api(`/api/departments/${id}/rules`)]);
  const dep=deps.find(d=>d.id===id);
  if(!dep){location.hash='#/';return;}
  let html=`<p class="crumbs"><a href="#/">🏠 Firma</a> › ${esc(dep.icon)} ${esc(dep.name)}</p>
  <div class="section"><h2>${esc(dep.icon)} ${esc(dep.name)} <span class="hint">${esc(dep.description)}</span></h2>
  <div class="formrow">
    <button class="primary" onclick="openChat(${id},null)">＋ Mitarbeiter einstellen (mit Claude bauen)</button>
    <button onclick="openImport(${id})">↳ Vorhandenen n8n-Workflow übernehmen</button>
    <button onclick="renameDepartment(${id},'${esc(dep.name)}')">Umbenennen</button>
    <button class="danger" onclick="removeDepartment(${id},'${esc(dep.name)}')">Abteilung auflösen</button>
  </div></div>`;

  html+='<div class="section"><h2>Mitarbeiter</h2>';
  if(agents.length){
    html+='<div class="grid">';
    for(const a of agents){
      const st=a.last_status||'';
      const deployed=!!a.n8n_workflow_id;
      html+=`<div class="card agent-card">
        <div class="row"><span class="dot ${esc(st)}" title="Letzter Lauf: ${esc(st||'—')}"></span>
          <h3 onclick="location.hash='#/agent/${a.id}'">${esc(a.name)}</h3>
          <label class="switch" title="${deployed?'Aktivieren/Deaktivieren':'Noch nicht deployt'}">
            <input type="checkbox" ${a.active?'checked':''} ${deployed?'':'disabled'}
              onchange="toggleAgent(${a.id},this.checked)"><span></span></label></div>
        <div class="role">${esc(a.role||'—')}</div>
        <div class="hint">${deployed?'n8n-Workflow: '+esc(a.n8n_workflow_id):'Entwurf — noch nicht deployt'}</div>
      </div>`;
    }
    html+='</div>';
  }else html+='<p class="empty">Diese Abteilung hat noch keine Mitarbeiter.</p>';
  html+='</div>';

  html+='<div class="section card"><h2>🔌 Freigegebene Systeme (Konnektoren)</h2>'+
    '<p class="hint">Nur freigegebene Systeme darf Claude in Agenten dieser Abteilung verdrahten. „eingerichtet“ = Zugangsdaten sind als Umgebungsvariablen gesetzt.</p>';
  for(const c of conns){
    html+=`<label class="check"><input type="checkbox" data-conn="${esc(c.key)}" ${c.allowed?'checked':''}
      onchange="saveConnectors(${id})"> ${esc(c.label)}
      <span class="badge">${c.configured?'eingerichtet ✓':'Zugangsdaten fehlen'}</span>
      ${c.hosts.length?`<span class="hint">erlaubt implizit: ${esc(c.hosts.join(', '))}</span>`:''}</label>`;
  }
  html+='</div>';

  html+='<div class="section card"><h2>🛡️ Netzwerkregeln (Host-Allowlist)</h2>'+
    '<p class="hint">Agenten dieser Abteilung dürfen nur die hier gelisteten Hosts erreichen (geprüft beim Deployment). „*.example.com“ erlaubt alle Subdomains, nicht example.com selbst.</p><div class="chips">';
  for(const r of rules.rules){
    html+=`<span class="chip" title="${esc(r.note)}">${esc(r.pattern)}${r.agent_id?' (nur ein Agent)':''}
      <span class="x" onclick="removeRule(${r.id},${id})">✕</span></span>`;
  }
  for(const h of rules.implicit_hosts)
    html+=`<span class="chip" title="implizit über Konnektor-Freigabe">${esc(h)} 🔌</span>`;
  if(!rules.rules.length&&!rules.implicit_hosts.length)html+='<span class="hint">Noch keine Hosts freigeschaltet.</span>';
  html+=`</div><div class="formrow">
    <input type="text" id="rulePattern" placeholder="z. B. erp.example.com oder *.example.com">
    <input type="text" id="ruleNote" placeholder="Notiz (optional)">
    <button onclick="addRule(${id})">Host erlauben</button></div></div>`;
  $('#main').innerHTML=html;
}
async function saveConnectors(depId){
  const keys=[...document.querySelectorAll('input[data-conn]:checked')].map(i=>i.dataset.conn);
  try{await api(`/api/departments/${depId}/connectors`,{method:'PUT',body:JSON.stringify({keys})});}
  catch(e){alert(e.message);}
  route();
}
async function addRule(depId){
  const pattern=$('#rulePattern').value.trim();
  if(!pattern)return;
  try{await api(`/api/departments/${depId}/rules`,{method:'POST',
    body:JSON.stringify({pattern,note:$('#ruleNote').value.trim()})});}
  catch(e){alert(e.message);}
  route();
}
async function removeRule(ruleId,depId){
  await api('/api/rules/'+ruleId,{method:'DELETE'});route();
}
async function renameDepartment(id,old){
  const name=prompt('Neuer Name der Abteilung:',old);
  if(!name||name===old)return;
  try{await api('/api/departments/'+id,{method:'PATCH',body:JSON.stringify({name})});}
  catch(e){alert(e.message);}
  route();
}
async function removeDepartment(id,name){
  if(!confirm(`Abteilung „${name}“ wirklich auflösen? Alle Mitarbeiter (inkl. deployter n8n-Workflows) werden entfernt.`))return;
  try{await api('/api/departments/'+id,{method:'DELETE'});location.hash='#/';}
  catch(e){alert(e.message);}
}
async function toggleAgent(id,on){
  try{await api(`/api/agents/${id}/${on?'activate':'deactivate'}`,{method:'POST'});}
  catch(e){alert(e.message);}
  route();
}

/* --- Agenten-Detail ------------------------------------------------------------ */
async function viewAgent(id){
  const a=await api('/api/agents/'+id);
  const deps=await api('/api/departments');
  const dep=deps.find(d=>d.id===a.department_id)||{name:'?',icon:'🏢'};
  let html=`<p class="crumbs"><a href="#/">🏠 Firma</a> ›
    <a href="#/abteilung/${a.department_id}">${esc(dep.icon)} ${esc(dep.name)}</a> › ${esc(a.name)}</p>
  <div class="section card"><h2>${esc(a.name)} <span class="hint">${esc(a.role||'')}</span></h2>
    <p class="hint">${esc(a.description||'')}</p>
    <p class="hint">${a.n8n_workflow_id?('n8n-Workflow: '+esc(a.n8n_workflow_id)+' · '+(a.active?'aktiv':'inaktiv')):'Entwurf — noch nicht deployt'}</p>
    <div class="formrow">
      <button class="primary" onclick="openChat(${a.department_id},${a.id})">Feedback geben / weiterentwickeln (Chat)</button>
      <button onclick="renameAgent(${a.id},'${esc(a.name)}')">Umbenennen</button>
      <button class="danger" onclick="fireAgent(${a.id},'${esc(a.name)}')">Mitarbeiter entlassen</button>
    </div>
    <p class="hint">Der Chat merkt sich den bisherigen Verlauf dieses Mitarbeiters und
    kennt seine letzten Läufe (inkl. Fehlermeldungen) — einfach beschreiben, was
    besser werden soll.</p></div>
  <div class="section card"><h2>Ausführungsverlauf</h2>`;
  if(a.executions.length){
    html+='<table><tr><th>Status</th><th>Start</th><th>Ende</th></tr>';
    for(const e of a.executions){
      html+=`<tr><td><span class="dot ${esc(e.status)}"></span> ${esc(e.status)}</td>
        <td>${esc((e.startedAt||'').replace('T',' ').slice(0,19))}</td>
        <td>${esc((e.stoppedAt||'').replace('T',' ').slice(0,19))}</td></tr>`;
    }
    html+='</table>';
  }else html+='<p class="empty">Noch keine Läufe.</p>';
  html+='</div>';
  $('#main').innerHTML=html;
}
async function renameAgent(id,old){
  const name=prompt('Neuer Mitarbeitername:',old);
  if(!name||name===old)return;
  try{await api('/api/agents/'+id,{method:'PATCH',body:JSON.stringify({name})});}
  catch(e){alert(e.message);}
  route();
}
async function fireAgent(id,name){
  if(!confirm(`„${name}“ wirklich entlassen? Der n8n-Workflow wird gelöscht.`))return;
  try{await api('/api/agents/'+id,{method:'DELETE'});location.hash='#/';}
  catch(e){alert(e.message);}
}

/* --- Chat: Agent bauen / weiterentwickeln ---------------------------------------- */
let chatSession=null;
function proposalCard(p){
  return `<div class="proposal"><h4>💼 ${esc(p.agent_name||p.workflow.name)}</h4>
    <div class="role">${esc(p.agent_role||'')}</div>
    <details><summary>Workflow-JSON ansehen (${p.workflow.nodes.length} Schritte)</summary>
    <pre>${esc(JSON.stringify(p.workflow,null,2))}</pre></details>
    <div class="formrow"><button class="primary" onclick="deployProposal()">Übernehmen &amp; deployen</button>
    <span class="hint">…oder unten weiter besprechen.</span></div></div>`;
}
async function openChat(depId,agentId){
  chatSession=await api('/api/chat/sessions',{method:'POST',
    body:JSON.stringify({department_id:depId,agent_id:agentId})});
  $('#chatTitle').textContent=agentId?'Mitarbeiter weiterentwickeln (Verlauf bleibt erhalten)':'Neuen Mitarbeiter einstellen';
  const log=$('#chatLog');
  log.innerHTML='';
  // Fortlaufender Verlauf: bisherige Nachrichten (und den letzten Vorschlag) anzeigen.
  for(const m of (chatSession.messages||[])){
    log.insertAdjacentHTML('beforeend',
      `<div class="msg ${esc(m.role)}"><div class="bubble">${esc(m.content)}</div></div>`);
    if(m.proposal_json){
      try{
        log.insertAdjacentHTML('beforeend',proposalCard(
          {agent_name:m.agent_name,agent_role:m.agent_role,workflow:JSON.parse(m.proposal_json)}));
      }catch(e){/* defektes Alt-JSON nur überspringen */}
    }
  }
  if(!(chatSession.messages||[]).length){
    log.innerHTML='<div class="msg assistant"><div class="bubble">'+(agentId
      ?'Hallo! Sag mir, was dieser Mitarbeiter besser machen soll — ich kenne seinen Workflow und seine letzten Läufe.'
      :'Hallo! Beschreibe mir, was der neue Mitarbeiter tun soll — z. B. „Fasse mir jeden Morgen die ungelesenen Mails zusammen“.')+'</div></div>';
  }
  $('#chatInput').value='';
  await loadModelPicker();
  $('#chatDlg').showModal();
  log.scrollTop=log.scrollHeight;
  $('#chatInput').focus();
}
async function loadModelPicker(){
  try{
    const s=await api('/api/settings');
    const dl=$('#modelList');
    dl.innerHTML='';
    for(const m of (s.suggestions||[])){
      const o=document.createElement('option');o.value=m;dl.appendChild(o);
    }
    $('#modelInput').value=s.model||'';
    $('#modelInput').placeholder=s.default_model||'claude-fable-5';
    $('#modelSaved').textContent=s.demo_mode?'(Demo-Modus: Modell wird nicht genutzt)':'';
  }catch(e){/* Einstellungen optional — Chat funktioniert auch ohne */}
}
async function saveModel(){
  const model=$('#modelInput').value.trim();
  try{
    const s=await api('/api/settings',{method:'PUT',body:JSON.stringify({model})});
    $('#modelInput').value=s.model||'';
    $('#modelSaved').textContent='gespeichert ✓ (gilt für alle Agenten)';
    setTimeout(()=>{$('#modelSaved').textContent='';},2500);
  }catch(e){$('#modelSaved').textContent='Fehler: '+e.message;}
}
function appendMsg(role,text){
  $('#chatLog').insertAdjacentHTML('beforeend',
    `<div class="msg ${role}"><div class="bubble">${esc(text)}</div></div>`);
  $('#chatLog').scrollTop=$('#chatLog').scrollHeight;
}
async function sendChat(){
  const text=$('#chatInput').value.trim();
  if(!text||!chatSession)return;
  $('#chatInput').value='';
  appendMsg('user',text);
  $('#chatSend').disabled=true;
  try{
    const res=await api(`/api/chat/sessions/${chatSession.id}/message`,
      {method:'POST',body:JSON.stringify({text})});
    appendMsg('assistant',res.reply);
    if(res.problems&&res.problems.length){
      $('#chatLog').insertAdjacentHTML('beforeend',
        '<div class="errorcard">Der Vorschlag hat die Prüfung nicht bestanden:<ul>'+
        res.problems.map(p=>'<li>'+esc(p.reason)+'</li>').join('')+'</ul></div>');
    }
    if(res.proposal){
      $('#chatLog').insertAdjacentHTML('beforeend',proposalCard(res.proposal));
    }
    $('#chatLog').scrollTop=$('#chatLog').scrollHeight;
  }catch(e){appendMsg('assistant','Fehler: '+e.message);}
  finally{$('#chatSend').disabled=false;$('#chatInput').focus();}
}
async function deployProposal(){
  if(!chatSession)return;
  try{
    const res=await api(`/api/chat/sessions/${chatSession.id}/deploy`,{method:'POST'});
    $('#chatDlg').close();
    alert(`„${res.agent.name}“ ist eingestellt und als n8n-Workflow ${res.agent.n8n_workflow_id} deployt. Über den Schalter auf der Mitarbeiter-Karte kannst du ihn aktivieren.`);
    location.hash='#/abteilung/'+res.agent.department_id;route();
  }catch(e){
    const v=(e.data&&e.data.violations)||[];
    $('#chatLog').insertAdjacentHTML('beforeend',
      '<div class="errorcard">Deployment abgelehnt:<ul>'+
      (v.length?v.map(p=>'<li>'+esc(p.reason)+'</li>').join(''):'<li>'+esc(e.message)+'</li>')+
      '</ul>Beschreibe im Chat, was angepasst werden soll — oder erweitere die Netzwerkregeln der Abteilung.</div>');
    $('#chatLog').scrollTop=$('#chatLog').scrollHeight;
  }
}

/* --- Vorhandenen n8n-Workflow als Mitarbeiter übernehmen -------------------------- */
let importDepId=null;
async function openImport(depId){
  importDepId=depId;
  let list=[];
  try{list=await api('/api/n8n/workflows');}catch(e){alert(e.message);return;}
  const sel=$('#importSelect');
  sel.innerHTML='';
  if(!list.length){
    alert('Alle n8n-Workflows sind bereits Mitarbeitern zugeordnet (oder es gibt keine).');
    return;
  }
  for(const wf of list){
    const opt=document.createElement('option');
    opt.value=wf.id;
    opt.textContent=`${wf.name} (${wf.active?'aktiv':'inaktiv'})`;
    opt.dataset.name=wf.name;
    sel.appendChild(opt);
  }
  $('#importName').value=sel.selectedOptions[0].dataset.name;
  sel.onchange=()=>{$('#importName').value=sel.selectedOptions[0].dataset.name;};
  $('#importDlg').showModal();
}
async function doImport(){
  const name=$('#importName').value.trim();
  if(!name){alert('Bitte einen Mitarbeiternamen vergeben.');return;}
  try{
    const agent=await api('/api/agents/import',{method:'POST',body:JSON.stringify({
      department_id:importDepId,
      n8n_workflow_id:$('#importSelect').value,
      name,role:$('#importRole').value.trim()})});
    $('#importDlg').close();
    location.hash='#/agent/'+agent.id;route();
  }catch(e){alert(e.message);}
}

/* --- Start ----------------------------------------------------------------------- */
initTheme();
api('/api/status').then(s=>{if(s.demo_mode)$('#demoBadge').style.display='inline-block';});
route();
"""


def render() -> str:
    logo = logo_svg(38)
    return f"""<!doctype html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AI-Systems — Virtuelle Firma</title>
<style>{_CSS}</style>
</head>
<body>
<header>
  <span id="logo">{logo}</span>
  <div><h1>AI-Systems</h1><div class="sub">Virtuelle Firma — n8n-Agenten mit Claude</div></div>
  <span class="badge" id="demoBadge" style="display:none">DEMO-MODUS</span>
  <div class="spacer"></div>
  <button onclick="toggleTheme()" title="Hell/Dunkel umschalten">🌓</button>
</header>
<main id="main"><p class="empty">Lade …</p></main>
<dialog id="importDlg">
  <div class="dlg-head"><h3>n8n-Workflow als Mitarbeiter übernehmen</h3>
    <button onclick="document.getElementById('importDlg').close()">✕</button></div>
  <div class="dlg-body">
    <p class="hint">Der Workflow bleibt in n8n unverändert — er bekommt nur einen
    Mitarbeiternamen und ist danach hier verwaltbar und per Chat weiterentwickelbar.</p>
    <div class="formrow"><label>Workflow:</label>
      <select id="importSelect" style="flex:1;font:inherit;padding:7px 10px;border-radius:8px;
        border:1px solid var(--line);background:var(--bg);color:var(--text)"></select></div>
    <div class="formrow"><label>Name:</label>
      <input type="text" id="importName" style="flex:1" placeholder="z. B. Berta Bestellung"></div>
    <div class="formrow"><label>Rolle:</label>
      <input type="text" id="importRole" style="flex:1" placeholder="z. B. Bestellbestätigerin (optional)"></div>
  </div>
  <div class="dlg-foot">
    <button class="primary" onclick="doImport()">Als Mitarbeiter übernehmen</button>
  </div>
</dialog>
<dialog id="chatDlg">
  <div class="dlg-head"><h3 id="chatTitle">Neuen Mitarbeiter einstellen</h3>
    <button onclick="document.getElementById('chatDlg').close()">✕</button></div>
  <div class="dlg-model">
    <span>🧠 Claude-Modell:</span>
    <input type="text" id="modelInput" list="modelList" placeholder="claude-fable-5">
    <datalist id="modelList"></datalist>
    <button onclick="saveModel()">übernehmen</button>
    <span id="modelSaved" class="hint"></span>
  </div>
  <div class="dlg-body" id="chatLog"></div>
  <div class="dlg-foot">
    <input type="text" id="chatInput" placeholder="Beschreibe, was der Agent tun soll …"
      onkeydown="if(event.key==='Enter')sendChat()">
    <button class="primary" id="chatSend" onclick="sendChat()">Senden</button>
  </div>
</dialog>
<script>{_JS}</script>
</body>
</html>"""
