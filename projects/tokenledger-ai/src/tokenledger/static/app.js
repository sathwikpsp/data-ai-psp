"use strict";
const $ = (id) => document.getElementById(id);
const money = (n, digits = 2) => n == null ? "—" : new Intl.NumberFormat("en-US", {style:"currency", currency:"USD", minimumFractionDigits:digits, maximumFractionDigits:digits}).format(n);
const number = (n) => new Intl.NumberFormat("en-US").format(n);
const staticMode = document.querySelector('meta[name="tokenledger-mode"]').content === "static";
let token = "", snapshot = null, liveTimer = null;
const headers = () => token ? {"Authorization":"Bearer " + token} : {};

async function load() {
  $("refresh").disabled = true;
  $("status").className = "status";
  $("status").textContent = "Loading warehouse snapshot…";
  try {
    const response = await fetch(staticMode ? "./report.json" : "./api/v1/report", {headers:headers(), cache:"no-store"});
    if (response.status === 401) { $("auth").hidden = false; throw new Error("Enter your workspace API token to continue."); }
    if (!response.ok) throw new Error("The warehouse could not be reached. Check the service and retry.");
    snapshot = await response.json();
    if (staticMode) {
      const saved = sessionStorage.getItem("tokenledger-live");
      if (saved) snapshot = JSON.parse(saved);
    }
    $("auth").hidden = true;
    render(snapshot);
  } catch (error) {
    $("status").className = "status error";
    $("status").textContent = error.message;
  } finally { $("refresh").disabled = false; }
}

function render(data) {
  const o = data.overview, f = data.forecast;
  $("mode").textContent = staticMode ? "LIVE SIMULATION" : (data.rate_card_version.startsWith("demo-") ? "Synthetic demo" : "Usage workspace");
  $("status").textContent = data.pricing_note + (o.freshness === "stale" ? " · Historical snapshot: data is over 48 hours old." : "");
  $("total").textContent = money(o.cost_usd);
  $("requests").textContent = number(o.requests);
  $("tokens").textContent = number(o.tokens) + " tokens observed";
  $("unit-cost").textContent = money(o.cost_per_success_usd, 4);
  $("alerts-count").textContent = data.anomalies.alerts.length;
  $("window").textContent = o.first_event ? o.first_event.slice(0,10) + " → " + o.last_event.slice(0,10) : "Ingest usage to get started";
  $("team-count").textContent = o.teams + " teams";
  $("lineage").textContent = "Snapshot " + data.dataset_fingerprint.slice(0,12) + " · Rates " + data.rate_card_version + " · Rejected " + o.quality.rejected;
  const teams = $("teams"); teams.replaceChildren();
  o.by_team.forEach(team => {
    const row = document.createElement("tr");
    [team.team, money(team.cost_usd), (o.cost_usd ? 100*team.cost_usd/o.cost_usd : 0).toFixed(1)+"%", (100*(team.cache_ratio||0)).toFixed(1)+"%", (100*team.error_rate).toFixed(1)+"%"].forEach(value => {
      const cell = document.createElement("td"); cell.textContent = value; row.append(cell);
    }); teams.append(row);
  });
  const alerts = $("alerts"); alerts.replaceChildren();
  data.anomalies.alerts.slice(0,3).forEach(alert => {
    const card = document.createElement("div"); card.className = "alert";
    const top = document.createElement("div"); top.className = "alert-top";
    const team = document.createElement("span"); team.textContent = alert.team;
    const excess = document.createElement("span"); excess.className = "excess"; excess.textContent = "+" + money(alert.excess_usd);
    const detail = document.createElement("small"); detail.textContent = alert.day + " · " + alert.drivers.join(", ").replaceAll("_", " ");
    top.append(team, excess); card.append(top, detail); alerts.append(card);
  });
  if (!data.anomalies.alerts.length) alerts.textContent = data.anomalies.status === "ready" ? "No material cost spikes detected." : "At least 28 training days plus later scoring data are needed.";
  $("model-name").textContent = f.status === "ready" ? f.model.replaceAll("_", " ") + " · Holdout WAPE " + (f.backtest.selected.wape*100).toFixed(1)+"%" : "Forecast: " + f.status.replaceAll("_", " ");
  $("forecast-total").textContent = f.status === "ready" ? money(f.projected_usd) + " projected" : "";
  $("budget-forecast").textContent = money(f.projected_usd);
  updateBudget(); drawChart(data);
  if (staticMode && !liveTimer) liveTimer = setInterval(liveTick, 2500);
}

function liveTick() {
  if (!snapshot) return;
  const teams = snapshot.overview.by_team;
  const team = teams[Math.floor(Math.random() * teams.length)];
  const requests = 2 + Math.floor(Math.random() * 7);
  const spike = Math.random() < 0.035;
  const cost = requests * (spike ? 0.65 : 0.018 + Math.random() * 0.025);
  const tokens = requests * Math.floor(1800 + Math.random() * 6000);
  snapshot.overview.requests += requests;
  snapshot.overview.tokens += tokens;
  snapshot.overview.cost_usd += cost;
  snapshot.overview.cost_microusd += Math.round(cost * 1e6);
  team.requests += requests; team.cost_usd += cost;
  const today = new Date().toISOString().slice(0,10);
  let point = snapshot.daily.at(-1);
  if (!point || point.day !== today) { point = {day:today,cost_usd:0}; snapshot.daily.push(point); }
  point.cost_usd += cost;
  snapshot.generated_at = new Date().toISOString();
  snapshot.overview.last_event = snapshot.generated_at;
  snapshot.overview.freshness = "fresh";
  snapshot.pricing_note = "Live browser telemetry simulation · new usage events every 2.5 seconds";
  if (spike) {
    snapshot.anomalies.alerts.unshift({id:"live:"+Date.now(),team:team.team,day:today,cost_usd:cost,baseline_usd:cost/4,excess_usd:cost*0.75,drivers:["request_volume"],severity:"medium"});
  }
  sessionStorage.setItem("tokenledger-live", JSON.stringify(snapshot));
  render(snapshot);
}

function updateBudget() {
  if (!snapshot) return;
  const value = Number($("budget").value), projected = snapshot.forecast.projected_usd;
  const target = $("budget-status"); target.className = "budget-status";
  if (projected == null) { target.textContent = "Not enough history to forecast"; return; }
  if (!Number.isFinite(value) || value <= 0) { target.textContent = "Enter a positive budget"; return; }
  target.textContent = projected > value ? money(projected-value) + " above your scenario budget" : money(value-projected) + " of projected headroom";
  if (projected > value) target.classList.add("warn");
}

function drawChart(data) {
  const root = $("chart"); root.replaceChildren();
  if (!data.daily.length) { root.textContent = "No usage yet. Run tokenledger demo or ingest usage events."; return; }
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns,"svg"); svg.setAttribute("viewBox","0 0 680 220");
  const make = (tag, attrs, text) => { const e=document.createElementNS(ns,tag); Object.entries(attrs).forEach(([k,v])=>e.setAttribute(k,v)); if(text)e.textContent=text; svg.append(e); return e; };
  const actual = data.daily, future = data.forecast.points || [], points = [...actual,...future.map(p=>({day:p.day,cost_usd:p.predicted_usd}))];
  const max = Math.max(1,...points.map(p=>p.cost_usd))*1.15;
  const start=Date.parse(points[0].day), end=Date.parse(points.at(-1).day);
  const x = (day) => 46+(Date.parse(day)-start)/Math.max(end-start,86400000)*620;
  const y = (value) => 186-value/max*169;
  for(let i=0;i<4;i++) { const value=max*i/3, yy=y(value); make("line",{x1:46,y1:yy,x2:668,y2:yy,stroke:"#e6ece2","stroke-dasharray":"3 4"}); make("text",{x:0,y:yy+3},"$"+value.toFixed(0)); }
  const line = (items) => items.map((p,i)=>(i?"L":"M")+x(p.day).toFixed(2)+","+y(p.cost_usd).toFixed(2)).join(" ");
  make("path",{d:line(actual)+" L"+x(actual.at(-1).day)+",186 L46,186 Z",fill:"#e7f1d9","fill-opacity":"0.6"});
  make("path",{d:line(actual),fill:"none",stroke:"#286b50","stroke-width":"2.2","stroke-linejoin":"round"});
  if(future.length)make("path",{d:line([actual.at(-1),...future.map(p=>({day:p.day,cost_usd:p.predicted_usd}))]),fill:"none",stroke:"#91a845","stroke-width":"2.2","stroke-dasharray":"5 4"});
  for(const point of [points[0], points[Math.floor(points.length/2)], points.at(-1)])make("text",{x:x(point.day),y:210,"text-anchor":point===points[0]?"start":point===points.at(-1)?"end":"middle"},point.day.slice(5));
  root.append(svg);
}

function staticAnswer(question) {
  const q=question.toLowerCase(); let answer, evidence=[];
  if(/anomal|spike|why|incident/.test(q)) {
    evidence=snapshot.anomalies.alerts.map(a=>({id:a.id,data:a}));
    answer=evidence.length?evidence.map(({id,data:a})=>a.team+" spent "+money(a.cost_usd)+" on "+a.day+" against a "+money(a.baseline_usd)+" weekday baseline. Signals: "+a.drivers.join(", ")+". ["+id+"]").join("\n\n"):"No material cost spikes detected.";
  } else if(/forecast|budget|future|next/.test(q)) {
    evidence=[{id:"forecast:14d",data:snapshot.forecast}];
    answer=snapshot.forecast.status==="ready"?"The next 14 days from the snapshot are projected at "+money(snapshot.forecast.projected_usd)+" using "+snapshot.forecast.model+". [forecast:14d]":"Forecast unavailable: "+snapshot.forecast.status;
  } else if(/cost|spend|team|expensive|summary|save|optim|cache|recommend/.test(q)) {
    evidence=snapshot.overview.by_team.map(t=>({id:"team:"+t.team,data:t}));
    answer=evidence.map(({id,data:t})=>t.team+": "+money(t.cost_usd)+"; cache share "+(100*(t.cache_ratio||0)).toFixed(1)+"%. Review cache eligibility and retries before changing routing. ["+id+"]").join("\n\n")||"No usage data.";
  } else answer="Ask about spending by team, cost spikes, the forecast, or optimization. This assistant cannot execute instructions or SQL.";
  return {answer,evidence};
}

async function ask(question) {
  $("answer").textContent="Checking the evidence…"; $("evidence-details").hidden=true;
  try {
    let result;
    if(staticMode)result=staticAnswer(question);
    else { const response=await fetch("./api/v1/explain",{method:"POST",headers:{...headers(),"Content-Type":"application/json"},body:JSON.stringify({question})}); if(!response.ok)throw new Error("Could not retrieve the answer. Check your connection or token."); result=await response.json(); }
    $("answer").textContent=result.answer;
    $("evidence-details").hidden=!result.evidence.length;
    $("evidence").textContent=JSON.stringify(result.evidence,null,2);
  } catch(error){$("answer").textContent=error.message;}
}
$("refresh").addEventListener("click",load);
$("unlock").addEventListener("click",()=>{token=$("token").value;$("token").value="";load();});
$("budget").addEventListener("input",updateBudget);
$("ask-form").addEventListener("submit",event=>{event.preventDefault();if(snapshot)ask($("question").value);});
document.querySelectorAll("[data-question]").forEach(button=>button.addEventListener("click",()=>{if(snapshot){$("question").value=button.dataset.question;ask(button.dataset.question);}}));
load();
