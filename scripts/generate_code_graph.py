#!/usr/bin/env python3
"""Generate an interactive, self-contained code dependency graph for ODE.

Scans the repository (Python AST imports + static/js layout), builds a
nodes/edges JSON model and embeds it into a single offline HTML file with a
vanilla-JS force-directed canvas visualization (no external dependencies,
matching the project policy).

Output: docs/assets/code_graph.html

Usage:
    python3 scripts/generate_code_graph.py
    python3 scripts/generate_code_graph.py --check
"""

from __future__ import annotations

import ast
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "docs" / "assets" / "code_graph.html"

PY_ROOTS = ["app.py", "build_windows_package.py", "inventory", "ode",
            "scripts", "baseline_rehearsal"]
JS_ROOT = ROOT / "static" / "js"

# Top-level groups drive node colors and filter checkboxes.
GROUPS = {
    "entry": "#f8fafc", "core": "#60a5fa", "warehouse": "#34d399",
    "reports": "#fbbf24", "monitoring": "#f472b6", "knowledge": "#a78bfa",
    "administration": "#fb923c", "services": "#2dd4bf", "shared": "#94a3b8",
    "models": "#64748b", "migration": "#e879f9", "webapp": "#38bdf8",
    "ode013": "#c084fc", "scripts": "#facc15", "frontend": "#4ade80",
    "other": "#cbd5e1",
}


def module_name(path: Path) -> str:
    rel = path.relative_to(ROOT)
    return ".".join(rel.with_suffix("").parts)


def group_of(path: Path) -> str:
    rel = path.relative_to(ROOT)
    parts = rel.parts
    if rel.name in {"app.py", "build_windows_package.py"}:
        return "entry"
    if parts[0] == "static":
        return "frontend"
    if parts[0] == "ode":
        return "ode013"
    if parts[0] in {"scripts", "baseline_rehearsal"}:
        return "scripts"
    if parts[0] == "inventory":
        if len(parts) == 2:
            return "webapp" if parts[1] in {"webapp.py"} else "core"
        return parts[1] if parts[1] in GROUPS else "other"
    return "other"


def collect_python() -> list[Path]:
    files: list[Path] = []
    for root in PY_ROOTS:
        path = ROOT / root
        if path.is_file():
            files.append(path)
        elif path.is_dir():
            files.extend(sorted(p for p in path.rglob("*.py")
                                if "__pycache__" not in p.parts))
    return files


def resolve_import(name: str, known: set[str]) -> str | None:
    """Match an imported dotted name to the longest known project module."""
    parts = name.split(".")
    while parts:
        candidate = ".".join(parts)
        if candidate in known:
            return candidate
        package = candidate + ".__init__"
        if package in known:
            return package
        parts.pop()
    return None


def python_edges(files: list[Path]) -> list[tuple[str, str]]:
    known = {module_name(f) for f in files}
    edges: set[tuple[str, str]] = set()
    for f in files:
        source = module_name(f)
        try:
            tree = ast.parse(f.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                if node.level:  # relative import
                    base = source.split(".")[: -node.level]
                    prefix = ".".join(base + ([node.module] if node.module else []))
                    names = [prefix] + [f"{prefix}.{a.name}" for a in node.names]
                elif node.module:
                    names = [node.module] + [f"{node.module}.{a.name}"
                                             for a in node.names]
            for name in names:
                target = resolve_import(name, known)
                if target and target != source:
                    edges.add((source, target))
    return sorted(edges)


def build_model() -> dict:
    nodes: list[dict] = []
    edges: list[dict] = []
    py_files = collect_python()
    index: dict[str, int] = {}

    for f in py_files:
        name = module_name(f)
        index[name] = len(nodes)
        nodes.append({
            "id": name,
            "label": str(f.relative_to(ROOT)),
            "group": group_of(f),
            "kind": "py",
            "lines": f.read_text(encoding="utf-8", errors="replace").count("\n") + 1,
        })
    for source, target in python_edges(py_files):
        edges.append({"s": index[source], "t": index[target], "k": "import"})

    # Frontend: files grouped under their folder; webapp serves them.
    webapp = index.get("inventory.webapp")
    css = ROOT / "static" / "css" / "main.css"
    for f in sorted(JS_ROOT.rglob("*.js")) + ([css] if css.is_file() else []):
        name = str(f.relative_to(ROOT))
        index[name] = len(nodes)
        nodes.append({
            "id": name, "label": name, "group": "frontend",
            "kind": "js" if f.suffix == ".js" else "css",
            "lines": f.read_text(encoding="utf-8", errors="replace").count("\n") + 1,
        })
        if webapp is not None:
            edges.append({"s": webapp, "t": index[name], "k": "serves"})

    return {"nodes": nodes, "edges": edges,
            "groups": GROUPS,
            "counts": {"nodes": len(nodes), "edges": len(edges)}}


TEMPLATE = """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<title>ODE — граф связей кодовой базы</title>
<style>
html,body{margin:0;height:100%;background:#05070f;color:#e2e8f0;
font:13px/1.45 -apple-system,"Segoe UI",Roboto,sans-serif;overflow:hidden}
#panel{position:fixed;left:0;top:0;bottom:0;width:248px;padding:14px;
background:#0b1120d9;backdrop-filter:blur(8px);overflow-y:auto;z-index:2;
border-right:1px solid #1e293b}
#panel h1{margin:0 0 2px;font-size:15px}
#panel p{margin:2px 0 10px;color:#94a3b8;font-size:11px}
#search{width:100%;box-sizing:border-box;padding:6px 8px;border-radius:7px;
border:1px solid #334155;background:#111a2e;color:#e2e8f0;margin-bottom:10px}
label.flt{display:flex;align-items:center;gap:6px;padding:2px 0;cursor:pointer}
label.flt input{accent-color:#60a5fa}
label.flt .dot{width:9px;height:9px;border-radius:50%;box-shadow:0 0 6px currentColor}
label.flt small{color:#64748b;margin-left:auto}
#info{position:fixed;right:12px;top:12px;max-width:300px;padding:10px 12px;
background:#0b1120e6;border:1px solid #1e293b;border-radius:9px;z-index:2;
display:none}
#info b{overflow-wrap:anywhere}
#stats{position:fixed;right:12px;bottom:10px;color:#475569;z-index:2;font-size:11px}
canvas{position:fixed;inset:0}
</style>
</head>
<body>
<div id="panel">
<h1>ODE — граф кода</h1>
<p id="meta"></p>
<input id="search" placeholder="Поиск файла/модуля…">
<div id="filters"></div>
<p style="margin-top:10px">Колесо — зум, тянуть фон — панорама, тянуть узел —
переместить, клик — закрепить. Размер узла — объём файла; линии — import
(Python) и serves (webapp → static). Цвет связи — цвет модуля-источника.</p>
</div>
<div id="info"></div>
<div id="stats"></div>
<canvas id="c"></canvas>
<script>
const DATA = __DATA__;
const canvas=document.getElementById('c'),ctx=canvas.getContext('2d');
let W,H;function resize(){W=canvas.width=innerWidth;H=canvas.height=innerHeight}
resize();addEventListener('resize',resize);
const N=DATA.nodes,E=DATA.edges,G=DATA.groups;
const R=n=>Math.max(3.2,Math.min(15,2.2*Math.sqrt(n.lines/30)));
// Кластерная инициализация: каждый модуль — свой сектор круга.
const groupList=[...new Set(N.map(n=>n.group))];
const anchors={};
groupList.forEach((g,i)=>{const a=i/groupList.length*Math.PI*2;
 anchors[g]={x:Math.cos(a)*520,y:Math.sin(a)*520}});
N.forEach(n=>{const c=anchors[n.group];
 n.x=c.x+(Math.random()-.5)*220;n.y=c.y+(Math.random()-.5)*220;
 n.vx=0;n.vy=0;n.pin=false;n.r=R(n)});
const adj=N.map(()=>[]);E.forEach(e=>{adj[e.s].push(e.t);adj[e.t].push(e.s)});
const deg=N.map((_,i)=>adj[i].length);
const visible=new Set(groupList);let query='';
const panel=document.getElementById('filters');
const counts={};N.forEach(n=>counts[n.group]=(counts[n.group]||0)+1);
for(const [g,color] of Object.entries(G)){
 if(!counts[g])continue;
 const l=document.createElement('label');l.className='flt';
 l.innerHTML=`<input type="checkbox" checked><span class="dot" style="background:${color};color:${color}"></span>${g}<small>${counts[g]}</small>`;
 l.querySelector('input').onchange=e=>{e.target.checked?visible.add(g):visible.delete(g);fitPending=true};
 panel.appendChild(l);
}
document.getElementById('meta').textContent=
 `${DATA.counts.nodes} узлов / ${DATA.counts.edges} связей · ODE 0.15.0`;
document.getElementById('search').oninput=e=>query=e.target.value.trim().toLowerCase();
// Камера: авто-fit, пока пользователь не вмешался.
let scale=1,ox=0,oy=0,userCam=false,fitPending=true;
let drag=null,panning=false,px=0,py=0,hover=-1,frame=0;
const toWorld=(x,y)=>[(x-ox)/scale,(y-oy)/scale];
function fit(){let x0=1e9,y0=1e9,x1=-1e9,y1=-1e9,seen=0;
 for(const n of N){if(!visible.has(n.group))continue;seen++;
  x0=Math.min(x0,n.x);y0=Math.min(y0,n.y);x1=Math.max(x1,n.x);y1=Math.max(y1,n.y)}
 if(!seen)return;
 const pad=70,availW=W-248-pad*2,availH=H-pad*2;
 const s=Math.min(availW/Math.max(x1-x0,1),availH/Math.max(y1-y0,1),2.2);
 const tScale=s,tox=248+pad+(availW-(x1-x0)*s)/2-x0*s,toy=pad+(availH-(y1-y0)*s)/2-y0*s;
 scale+=(tScale-scale)*0.08;ox+=(tox-ox)*0.08;oy+=(toy-oy)*0.08}
canvas.onwheel=e=>{e.preventDefault();userCam=true;
 const f=e.deltaY<0?1.12:0.89;const [wx,wy]=toWorld(e.clientX,e.clientY);
 scale*=f;ox=e.clientX-wx*scale;oy=e.clientY-wy*scale};
function pick(x,y){const [wx,wy]=toWorld(x,y);
 for(let i=N.length-1;i>=0;i--){const n=N[i];if(!visible.has(n.group))continue;
  const dx=wx-n.x,dy=wy-n.y,rr=n.r+4/scale;if(dx*dx+dy*dy<rr*rr)return i}return -1}
canvas.onmousedown=e=>{const i=pick(e.clientX,e.clientY);
 if(i>=0){drag=N[i];drag.moved=false;userCam=true}
 else{panning=true;userCam=true;px=e.clientX;py=e.clientY}};
canvas.onmousemove=e=>{
 if(drag){const [wx,wy]=toWorld(e.clientX,e.clientY);drag.x=wx;drag.y=wy;
  drag.vx=drag.vy=0;drag.moved=true}
 else if(panning){ox+=e.clientX-px;oy+=e.clientY-py;px=e.clientX;py=e.clientY}
 else{hover=pick(e.clientX,e.clientY);showInfo();
  canvas.style.cursor=hover>=0?'pointer':'default'}};
addEventListener('mouseup',()=>{if(drag&&!drag.moved)drag.pin=!drag.pin;
 if(drag&&drag.moved)drag.pin=true;drag=null;panning=false});
function showInfo(){const el=document.getElementById('info');
 if(hover<0){el.style.display='none';return}
 const n=N[hover];
 el.innerHTML=`<b>${n.label}</b><br><span style="color:${G[n.group]}">${n.group}</span>
  · ${n.kind} · ${n.lines} строк · связей: ${adj[hover].length}`;
 el.style.display='block'}
// Стабильная физика: линейные пружины, ограничение скорости, якоря кластеров.
const VMAX=6;
function step(){
 for(let i=0;i<N.length;i++){const a=N[i];if(!visible.has(a.group))continue;
  for(let j=i+1;j<N.length;j++){const b=N[j];if(!visible.has(b.group))continue;
   let dx=b.x-a.x,dy=b.y-a.y;const d2=dx*dx+dy*dy+1;
   if(d2<26000){const inv=1/Math.sqrt(d2),f=520/d2;dx*=inv;dy*=inv;
    a.vx-=dx*f;a.vy-=dy*f;b.vx+=dx*f;b.vy+=dy*f}}}
 for(const e of E){const a=N[e.s],b=N[e.t];
  if(!visible.has(a.group)||!visible.has(b.group))continue;
  let dx=b.x-a.x,dy=b.y-a.y;const d=Math.sqrt(dx*dx+dy*dy)+0.01;
  const rest=a.group===b.group?55:110;
  const f=Math.max(-2,Math.min(2,(d-rest)*0.012));dx/=d;dy/=d;
  a.vx+=dx*f;a.vy+=dy*f;b.vx-=dx*f;b.vy-=dy*f}
 for(const n of N){if(!visible.has(n.group))continue;
  const c=anchors[n.group];
  n.vx+=(c.x-n.x)*0.0016;n.vy+=(c.y-n.y)*0.0016;
  if(!n.pin&&n!==drag){
   n.vx=Math.max(-VMAX,Math.min(VMAX,n.vx*0.85));
   n.vy=Math.max(-VMAX,Math.min(VMAX,n.vy*0.85));
   n.x+=n.vx;n.y+=n.vy}}}
function draw(){
 ctx.setTransform(1,0,0,1,0,0);
 ctx.clearRect(0,0,W,H);
 // фон-виньетка
 const bg=ctx.createRadialGradient(W/2,H/2,80,W/2,H/2,Math.max(W,H)*.75);
 bg.addColorStop(0,'#0b1226');bg.addColorStop(1,'#04060d');
 ctx.fillStyle=bg;ctx.fillRect(0,0,W,H);
 ctx.save();ctx.translate(ox,oy);ctx.scale(scale,scale);
 const hl=new Set();if(hover>=0){hl.add(hover);adj[hover].forEach(i=>hl.add(i))}
 // связи: аддитивное свечение, цвет модуля-источника
 ctx.globalCompositeOperation='lighter';
 for(const e of E){const a=N[e.s],b=N[e.t];
  if(!visible.has(a.group)||!visible.has(b.group))continue;
  const lit=hover>=0&&(e.s===hover||e.t===hover);
  const dim=hover>=0&&!lit;
  ctx.strokeStyle=G[a.group];
  ctx.globalAlpha=lit?0.9:(dim?0.03:0.16);
  ctx.lineWidth=(lit?1.6:0.7)/scale+0.3;
  ctx.beginPath();ctx.moveTo(a.x,a.y);
  const mx=(a.x+b.x)/2-(b.y-a.y)*0.08,my=(a.y+b.y)/2+(b.x-a.x)*0.08;
  ctx.quadraticCurveTo(mx,my,b.x,b.y);ctx.stroke()}
 // узлы: ядро + ореол
 for(let i=0;i<N.length;i++){const n=N[i];if(!visible.has(n.group))continue;
  const match=query&&n.label.toLowerCase().includes(query);
  const dim=(query&&!match)||(hover>=0&&!hl.has(i));
  const color=G[n.group];
  ctx.globalAlpha=dim?0.10:0.85;
  const halo=ctx.createRadialGradient(n.x,n.y,0,n.x,n.y,n.r*3);
  halo.addColorStop(0,color);halo.addColorStop(1,'#0000');
  ctx.fillStyle=halo;ctx.beginPath();ctx.arc(n.x,n.y,n.r*3,0,7);ctx.fill();
  ctx.globalAlpha=dim?0.25:1;
  ctx.fillStyle=color;ctx.beginPath();ctx.arc(n.x,n.y,n.r,0,7);ctx.fill();
  ctx.globalAlpha=dim?0.2:0.95;
  ctx.fillStyle='#ffffff';ctx.beginPath();
  ctx.arc(n.x,n.y,Math.max(1,n.r*0.42),0,7);ctx.fill();
  if(n.pin){ctx.globalAlpha=1;ctx.strokeStyle='#f8fafc';
   ctx.lineWidth=1.2/scale;ctx.beginPath();
   ctx.arc(n.x,n.y,n.r+3/scale,0,7);ctx.stroke()}}
 // подписи — обычным смешиванием, чтобы читались
 ctx.globalCompositeOperation='source-over';ctx.globalAlpha=1;
 for(let i=0;i<N.length;i++){const n=N[i];if(!visible.has(n.group))continue;
  const match=query&&n.label.toLowerCase().includes(query);
  const show=match||hl.has(i)||scale>1.6||(deg[i]>7&&scale>0.7)||n.r>11;
  if(!show)continue;
  const dim=(query&&!match)||(hover>=0&&!hl.has(i));
  if(dim)continue;
  const size=11/scale;ctx.font=`${size}px sans-serif`;
  const text=n.label.split('/').pop();
  ctx.fillStyle='#020617';ctx.globalAlpha=0.7;
  ctx.fillText(text,n.x+n.r+4/scale+1/scale,n.y+3/scale+1/scale);
  ctx.globalAlpha=1;ctx.fillStyle='#e2e8f0';
  ctx.fillText(text,n.x+n.r+4/scale,n.y+3/scale)}
 ctx.restore();
 document.getElementById('stats').textContent=
  `zoom ${scale.toFixed(2)} · сгенерировано scripts/generate_code_graph.py`}
(function loop(){frame++;step();
 if(!userCam||fitPending){fit();if(frame>60)fitPending=false}
 draw();requestAnimationFrame(loop)})();
</script>
</body>
</html>
"""


def render_html() -> tuple[str, dict]:
    model = build_model()
    html = TEMPLATE.replace("__DATA__", json.dumps(model, ensure_ascii=False))
    return html, model


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate the self-contained ODE code dependency graph."
    )
    parser.add_argument(
        "--check", action="store_true",
        help="fail when docs/assets/code_graph.html is missing or stale",
    )
    args = parser.parse_args()
    html, model = render_html()
    if args.check:
        if not OUTPUT.is_file() or OUTPUT.read_text(encoding="utf-8") != html:
            print(f"graph: stale -> {OUTPUT.relative_to(ROOT)}")
            return 1
        print(f"graph: current ({model['counts']['nodes']} nodes, "
              f"{model['counts']['edges']} edges)")
        return 0
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(html, encoding="utf-8")
    print(f"graph: {model['counts']['nodes']} nodes, "
          f"{model['counts']['edges']} edges -> {OUTPUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
