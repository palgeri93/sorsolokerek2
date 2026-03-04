import io
import os
import time
import random
import json
import uuid
from typing import List, Optional

import numpy as np
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

st.set_page_config(page_title="Sorsolókerék – Excel munkalapokkal", layout="centered")
st.title("🎡 Sorsolókerék – Excelből, munkalapok szerint")

st.write(
    "Tölts fel egy **.xlsx** fájlt több munkalappal. "
    "A gombok **pontosan** a munkalapok nevét viselik; a megnyomott gombnak megfelelő listából sorsol."
)

# ---------- Excel segédfüggvények ----------
def make_sample_workbook_bytes() -> bytes:
    df_a = pd.DataFrame({"Név": ["Anna","Bence","Csilla","Dávid","Emese","Feri"]})
    df_b = pd.DataFrame({
        "Név": ["Gabi","Hanna","Ivett","József","Kata","László"],
        "Súly": [1, 2, 1, 3, 1, 1],
    })
    df_c = pd.DataFrame({"Név": ["Máté","Nóra","Olívia","Péter","Réka","Sára"]})
    df_d = pd.DataFrame({"Név": ["Tamás","Ubul","Vera","Zita"]})
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df_a.to_excel(writer, sheet_name="Osztály A", index=False)
        df_b.to_excel(writer, sheet_name="Osztály B", index=False)
        df_c.to_excel(writer, sheet_name="Osztály C", index=False)
        df_d.to_excel(writer, sheet_name="Osztály D", index=False)
    buf.seek(0)
    return buf.read()

def read_sheet_names(xls_bytes: bytes) -> List[str]:
    xls = pd.ExcelFile(io.BytesIO(xls_bytes))
    return xls.sheet_names

def read_sheet_dataframe(xls_bytes: bytes, sheet_name: str) -> pd.DataFrame:
    df = pd.read_excel(io.BytesIO(xls_bytes), sheet_name=sheet_name)
    name_candidates = ["Név","Nev","név","name","Name"]
    name_col = next((c for c in name_candidates if c in df.columns), df.columns[0])
    df = df.rename(columns={name_col: "Név"})
    weight_col = next((c for c in ["Súly","súly","suly","Weight","weight"] if c in df.columns), None)
    if weight_col is not None:
        df = df.rename(columns={weight_col: "Súly"})
        df["Súly"] = pd.to_numeric(df["Súly"], errors="coerce").fillna(1.0).clip(lower=0.0)
    else:
        df["Súly"] = 1.0
    df["Név"] = df["Név"].astype(str).str.strip()
    df = df.replace({"Név": {"": pd.NA}}).dropna(subset=["Név"]).drop_duplicates(subset=["Név"]).reset_index(drop=True)
    return df[["Név","Súly"]]

def weighted_choice(names: List[str], weights: List[float]) -> int:
    w = np.array(weights, dtype=float)
    w = np.clip(w, 0, None)
    if w.sum() <= 0:
        return random.randrange(len(names))
    probs = w / w.sum()
    return int(np.random.choice(len(names), p=probs))

# ---------- Segéd: alapértelmezett fájl felkutatása ----------
def find_default_xlsx() -> Optional[bytes]:
    """Megpróbálja betölteni a sample_names.xlsx fájlt a script könyvtárából,
    a munkakönyvtárból vagy a /mnt/data alól. Az első találatot adja vissza bytes-ként."""
    candidates: list[tuple[str, str]] = []

    # 1) Script könyvtára
    try:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        candidates.append((os.path.join(script_dir, "sample_names.xlsx"), "__file__"))
    except Exception:
        pass

    # 2) Aktuális munkakönyvtár
    candidates.append((os.path.join(os.getcwd(), "sample_names.xlsx"), "cwd"))

    # 3) /mnt/data (pl. Streamlit Cloud / konténer környezet)
    candidates.append(("/mnt/data/sample_names.xlsx", "/mnt/data"))

    for path, origin in candidates:
        if os.path.exists(path):
            with open(path, "rb") as f:
                st.sidebar.caption(f"Alapértelmezett fájl betöltve innen: {path}")
                return f.read()
    return None

# ---------- Oldalsáv: forrás és beállítások ----------
with st.sidebar:
    st.header("Forrásfájl")
    source = st.radio("Válaszd ki a forrást:", ["Feltöltött Excel", "Mintafájl"], index=0, horizontal=True)
    xls_bytes = None

    if source == "Feltöltött Excel":
        uploaded = st.file_uploader("Excel feltöltése (.xlsx)", type=["xlsx"])
        if uploaded is not None:
            xls_bytes = uploaded.read()
        else:
            # ÚJ: alapértelmezett sample_names.xlsx automatikus betöltése, ha elérhető
            xls_bytes = find_default_xlsx()
            if xls_bytes is None:
                st.info("Tölts fel egy Excel fájlt, vagy válaszd a Mintafájlt!")
    else:
        xls_bytes = make_sample_workbook_bytes()
        st.caption("Mintafájl betöltve: Osztály A / B / C / D (B lapon 'Súly').")

    st.header("Beállítások")
    remove_winner = st.checkbox("Nyertes eltávolítása ebből a körből", value=True)
    use_weights = st.checkbox("Súlyozott sorsolás (Súly/Weight oszlop)", value=True)
    duration = st.slider("Pörgetés hossza (mp)", min_value=1.5, max_value=8.0, value=3.0, step=0.5)
    turns = st.slider("Teljes körök száma", min_value=3, max_value=10, value=6, step=1)

    st.header("Hang és animáció")
    audio_enabled = st.toggle("Hang engedélyezése", value=True)
    tick_sound = st.checkbox("Kattogás pörgetés közben", value=True)
    ding_sound = st.checkbox("Ding a nyertesnél", value=True)
    high_fps = st.checkbox("Magas FPS (60)", value=True, help="Ha akadozik a gépen, kapcsold ki.")

if xls_bytes is None:
    st.stop()

# ---------- Munkalapok ----------
sheet_names = read_sheet_names(xls_bytes)
if len(sheet_names) == 0:
    st.error("A fájl nem tartalmaz munkalapokat.")
    st.stop()

st.subheader("Munkalapok")
chosen = st.session_state.get("chosen_sheet")
cols_per_row = 4
rows = max(1, (len(sheet_names) + cols_per_row - 1) // cols_per_row)
for r in range(rows):
    cols = st.columns(cols_per_row)
    for c in range(cols_per_row):
        i = r * cols_per_row + c
        if i >= len(sheet_names):
            break
        sheet = sheet_names[i]
        if cols[c].button(sheet, key=f"btn_{sheet}"):
            st.session_state["chosen_sheet"] = sheet
            chosen = sheet

if not chosen and len(sheet_names) > 0:
    chosen = sheet_names[0]
    st.session_state["chosen_sheet"] = chosen

st.success(f"Kiválasztott munkalap: **{chosen}**")

# ---------- Névlista és kiválasztás a jobb oldali (oldalsáv) checkboxokkal ----------
df_sheet = read_sheet_dataframe(xls_bytes, chosen)
names_all = df_sheet["Név"].tolist()
weights_all = df_sheet["Súly"].tolist()
# ---------- Súlyok: felhasználói felülírás (szerkeszthető a felületen) ----------
# A Streamlit minden interakciónál újrafuttatja a scriptet, ezért a súlyokat session_state-ben tároljuk.
# Így a "Súly" oszlopot át tudod írni, és a sorsolás már ezt fogja használni.
if "weight_overrides_by_sheet" not in st.session_state:
    st.session_state["weight_overrides_by_sheet"] = {}

# Ha még nincs ilyen munkalaphoz súlytábla, vagy megváltozott a névlista (új Excel / módosult sheet),
# akkor inicializáljuk az Excelből beolvasott súlyokkal.
if (chosen not in st.session_state["weight_overrides_by_sheet"]) or    (set(st.session_state["weight_overrides_by_sheet"][chosen].keys()) != set(names_all)):
    st.session_state["weight_overrides_by_sheet"][chosen] = {n: float(w) for n, w in zip(names_all, weights_effective_all)}

# A ténylegesen használt súlylista (mindig a felülírt érték)
weights_effective_all = [float(st.session_state["weight_overrides_by_sheet"][chosen].get(n, 1.0)) for n in names_all]

# Session állapotok előkészítése
if "winners_by_sheet" not in st.session_state:
    st.session_state["winners_by_sheet"] = {}
if chosen not in st.session_state["winners_by_sheet"]:
    st.session_state["winners_by_sheet"][chosen] = []
previous_winners = st.session_state["winners_by_sheet"][chosen]

if "log_by_sheet" not in st.session_state:
    st.session_state["log_by_sheet"] = {}
if chosen not in st.session_state["log_by_sheet"]:
    st.session_state["log_by_sheet"][chosen] = []

# ÚJ: felhasználó által pipált névlista (alapértelmezetten mindenki be van kapcsolva)
if "selected_names_by_sheet" not in st.session_state:
    st.session_state["selected_names_by_sheet"] = {}
if chosen not in st.session_state["selected_names_by_sheet"]:
    st.session_state["selected_names_by_sheet"][chosen] = set(names_all)

with st.sidebar:
    st.header("Névszelekció")
    st.caption("Vedd ki a pipát annál, akit **ne** tegyünk a kerékbe.")

    # Gyors gombok: összes be / ki (FONTOS: a widgetek állapotát is frissítjük)
    bcol1, bcol2 = st.columns(2)
    with bcol1:
        if st.button("Összes be"):
            st.session_state["selected_names_by_sheet"][chosen] = set(names_all)
            for name in names_all:
                key = f"chk_{chosen}_{uuid.uuid5(uuid.NAMESPACE_DNS, name)}"
                st.session_state[key] = True
    with bcol2:
        if st.button("Összes ki"):
            st.session_state["selected_names_by_sheet"][chosen] = set()
            for name in names_all:
                key = f"chk_{chosen}_{uuid.uuid5(uuid.NAMESPACE_DNS, name)}"
                st.session_state[key] = False

    # Egyedi checkboxok – a kezdeti értéket explicit a session_state-ben állítjuk be,
    # mert a Streamlit a `value=` paramétert csak az első létrehozáskor használja.
    for name in names_all:
        key = f"chk_{chosen}_{uuid.uuid5(uuid.NAMESPACE_DNS, name)}"
        if key not in st.session_state:
            st.session_state[key] = name in st.session_state["selected_names_by_sheet"][chosen]
        st.checkbox(name, key=key)

    # A kiválasztás beolvasása a checkboxok tényleges állapotából
    new_selected: set[str] = set(n for n in names_all
                                 for k in [f"chk_{chosen}_{uuid.uuid5(uuid.NAMESPACE_DNS, n)}"]
                                 if st.session_state.get(k, False))
    # Frissítsük az állapotot a sheet-re
    st.session_state["selected_names_by_sheet"][chosen] = new_selected


st.divider()
st.header("Súlyozás")
st.caption("Itt tudod átírni a nevekhez tartozó **Súly** értékeket. 0 = nem kerül kiválasztásra súlyozással.")

# Szerkeszthető táblázat: Név fix, Súly szerkeszthető
weights_df = pd.DataFrame({
    "Név": names_all,
    "Súly": [float(st.session_state["weight_overrides_by_sheet"][chosen].get(n, 1.0)) for n in names_all],
})

edited_weights_df = st.data_editor(
    weights_df,
    key=f"weights_editor_{chosen}",
    use_container_width=True,
    hide_index=True,
    column_config={
        "Név": st.column_config.TextColumn("Név", disabled=True),
        "Súly": st.column_config.NumberColumn("Súly", min_value=0.0, step=1.0, format="%.2f"),
    },
)

# Mentés session_state-be (negatívból 0, üresből 1)
for _, row in edited_weights_df.iterrows():
    n = str(row["Név"]).strip()
    try:
        w = float(row["Súly"])
    except Exception:
        w = 1.0
    if np.isnan(w):
        w = 1.0
    w = max(0.0, w)
    st.session_state["weight_overrides_by_sheet"][chosen][n] = w

# Frissítsük az effektív súlylistát is, hogy a későbbi kód már ezt használja
weights_effective_all = [float(st.session_state["weight_overrides_by_sheet"][chosen].get(n, 1.0)) for n in names_all]

# Szűrés: először a felhasználói pipák, majd igény szerint a korábbi nyertesek eltávolítása
user_selected = st.session_state["selected_names_by_sheet"][chosen]
filtered_pairs = [(n, w) for n, w in zip(names_all, weights_effective_all) if n in user_selected]
if remove_winner and previous_winners:
    filtered_pairs = [(n, w) for n, w in filtered_pairs if n not in previous_winners]

names = [n for n, _ in filtered_pairs]
weights = [w for _, w in filtered_pairs]

if len(names) == 0:
    st.warning("Nincs aktív név a kerékben. Kapcsold be a megfelelő checkboxokat, vagy indíts új kört.")
    # Ha teljesen üres, mutassuk legalább az eredeti listát a táblában
    names = names_all
    weights = weights_effective_all

with st.expander("Névlista (aktuális)", expanded=False):
    st.write(pd.DataFrame({"Név": names, "Súly (aktuális)": weights}))

st.divider()
st.subheader("Pörgetés")

col_spin, col_reset, col_clearlog = st.columns([2,1,1])
with col_spin:
    spin = st.button("🎯 Pörgesd meg a kereket!", type="primary")
with col_reset:
    reset_round = st.button("🔄 Új kör indítása (csak ennél a lapnál)")
with col_clearlog:
    clear_log = st.button("🧹 Napló törlése (csak ennél a lapnál)")

if reset_round:
    st.session_state["winners_by_sheet"][chosen] = []
    st.success("Új kör kezdve: a korábbi nyertesek ismét részt vesznek.")

if clear_log:
    st.session_state["log_by_sheet"][chosen] = []
    st.success("A nyertes napló törölve ennél a munkalapnál.")

# Válasszuk ki előre a nyertest (Python oldal)
target_index = None
winner = None

if spin:
    if len(names) < 1:
        st.error("Nincs elérhető név a sorsoláshoz.")
    else:
        if use_weights and any(w > 0 for w in weights):
            target_index = weighted_choice(names, weights)
        else:
            target_index = random.randrange(len(names))
        winner = names[target_index]
        st.session_state["log_by_sheet"][chosen].append({
            "Időpont": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"),
            "Munkalap": chosen,
            "Nyertes": winner
        })
        if remove_winner and winner not in st.session_state["winners_by_sheet"][chosen]:
            st.session_state["winners_by_sheet"][chosen].append(winner)

# ---------- Canvas + WebAudio komponens ----------
def render_wheel_component(names: List[str], target_index: Optional[int] = None, duration_s: float = 3.0, turns: int = 6,
                           audio_enabled: bool = True, tick_sound: bool = True, ding_sound: bool = True, high_fps: bool = True):
    payload = {
        "names": names,
        "targetIndex": target_index,
        "duration": duration_s,
        "turns": turns,
        "audioEnabled": audio_enabled,
        "tickSound": tick_sound,
        "dingSound": ding_sound,
        "highFps": high_fps,
        "nonce": str(time.time()) if target_index is not None else "static"
    }
    config_json = json.dumps(payload)
    html_template = """
    <div style="display:flex;flex-direction:column;align-items:center;gap:8px">
      <canvas id="wheel" width="520" height="520" style="max-width:100%;border-radius:50%;box-shadow:0 6px 24px rgba(0,0,0,.2)"></canvas>
      <div id="winnerText" style="font:600 18px/1.2 system-ui, sans-serif; color:#166534; margin:4px 0 8px 0;"></div>
      <div style="display:flex;gap:12px;align-items:center">
        <button id="btnEnableAudio" style="padding:6px 10px;border:1px solid #999;border-radius:8px;cursor:pointer;">Hang engedélyezése</button>
        <span id="audioStatus" style="font:12px/1.2 sans-serif;color:#666">Ha nincs hang, kattints a gombra.</span>
      </div>
    </div>
    <script>
    const CONFIG = __CONFIG_JSON__;
    const canvas = document.getElementById('wheel');
    const ctx = canvas.getContext('2d');
    const size = canvas.width;
    const center = size/2;
    const radius = size/2 - 10;
    const deg2rad = d => d * Math.PI / 180;
    const names = CONFIG.names;
    const N = names.length || 1;
    const arcDeg = 360 / N;

    // WebAudio setup
    let audioCtx = null;
    let audioEnabled = CONFIG.audioEnabled;
    function ensureAudio() { if (!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)(); }
    function playBeep(freq=800, duration=0.05, gain=0.05) {
      if (!audioEnabled || !audioCtx) return;
      const o = audioCtx.createOscillator();
      const g = audioCtx.createGain();
      o.type = 'square';
      o.frequency.value = freq;
      g.gain.setValueAtTime(gain, audioCtx.currentTime);
      g.gain.exponentialRampToValueAtTime(0.0001, audioCtx.currentTime + duration);
      o.connect(g); g.connect(audioCtx.destination);
      o.start();
      o.stop(audioCtx.currentTime + duration);
    }

    const btn = document.getElementById('btnEnableAudio');
    const status = document.getElementById('audioStatus');
    btn.addEventListener('click', async () => {
      try {
        ensureAudio();
        await audioCtx.resume();
        audioEnabled = true;
        status.textContent = 'Hang: engedélyezve.';
      } catch(e) {
        status.textContent = 'Hang: nem sikerült engedélyezni.';
      }
    });

    function drawWheel(angle=0, highlightIndex=null) {
      const ctx = canvas.getContext('2d');
      ctx.clearRect(0,0,size,size);
      // pointer triangle at top
      ctx.save();
      ctx.translate(center, center);
      // draw slices
      for (let i=0;i<N;i++) {
        const start = deg2rad(i*arcDeg + angle);
        const end = deg2rad((i+1)*arcDeg + angle);
        ctx.beginPath();
        const hue = (i*360/N);
        ctx.fillStyle = `hsl(${hue}, 70%, 60%)`;
        ctx.moveTo(0,0);
        ctx.arc(0,0,radius,start,end);
        ctx.closePath();
        ctx.fill();
        // text
        ctx.save();
        const mid = (start+end)/2;
        ctx.rotate(mid);
        ctx.translate(radius*0.65, 0);
        ctx.rotate(Math.PI/2);
        ctx.fillStyle = '#111';
        ctx.font = 'bold 14px system-ui, sans-serif';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        const label = String(names[i]).slice(0,22);
        ctx.fillText(label, 0, 0);
        ctx.restore();
      }
      // circle outline
      ctx.beginPath();
      ctx.arc(0,0,radius,0,Math.PI*2);
      ctx.lineWidth = 4;
      ctx.strokeStyle = '#222';
      ctx.stroke();
      ctx.restore();
      // pointer
      ctx.beginPath();
      ctx.moveTo(center-12, 10);
      ctx.lineTo(center+12, 10);
      ctx.lineTo(center, 38);
      ctx.closePath();
      ctx.fillStyle = '#222';
      ctx.fill();
      // highlight ring if any
      if (highlightIndex !== null) {
        ctx.save();
        ctx.translate(center, center);
        const startA = deg2rad(highlightIndex*arcDeg + angle);
        const endA = deg2rad((highlightIndex+1)*arcDeg + angle);
        ctx.beginPath();
        ctx.arc(0,0,radius+2,startA,endA);
        ctx.lineWidth = 6;
        ctx.strokeStyle = '#000';
        ctx.stroke();
        ctx.restore();
      }
    }

    // static render
    drawWheel(0, null);
    const winnerEl = document.getElementById('winnerText');
    if (winnerEl) winnerEl.textContent = '';

    // animate if targetIndex provided
    if (CONFIG.targetIndex !== null && CONFIG.targetIndex !== undefined) {
      let fpsCap = CONFIG.highFps ? 60 : 30;
      let lastTickSector = -1;
      const targetIndex = CONFIG.targetIndex;
      const targetCenterDeg = targetIndex*arcDeg + arcDeg/2;
      const finalStart = 270 - targetCenterDeg; // to land with center at the TOP pointer
      const totalRotation = finalStart + CONFIG.turns*360;
      const dur = CONFIG.duration * 1000;
      const startTime = performance.now();
      function easeOutCubic(t){ return 1 - Math.pow(1-t,3); }

      function frame(now) {
        let t = Math.min(1, (now - startTime)/dur);
        let eased = easeOutCubic(t);
        let angle = eased * totalRotation;
        drawWheel(angle, t===1 ? targetIndex : null);
        if (t===1) {
          const winnerEl = document.getElementById('winnerText');
          if (winnerEl) winnerEl.textContent = `✅ Nyertes: ${names[targetIndex]}`;
        }

        if (CONFIG.tickSound && audioEnabled && audioCtx) {
          const a = (angle % 360 + 360) % 360;
          const sector = Math.floor(((360 - a + 270) % 360) / arcDeg);
          if (sector !== lastTickSector && t < 1) {
            playBeep(550, 0.03, 0.04);
            lastTickSector = sector;
          }
        }

        if (t < 1) {
          if (CONFIG.highFps) {
            requestAnimationFrame(frame);
          } else {
            setTimeout(()=>requestAnimationFrame(frame), 1000/fpsCap);
          }
        } else {
          if (CONFIG.dingSound && audioEnabled) { try { ensureAudio(); playBeep(900, 0.15, 0.1); } catch(e) {} }
        }
      }
      try { if (CONFIG.audioEnabled) ensureAudio(); } catch(e) {}
      requestAnimationFrame(frame);
    }
    </script>
    """
    html = html_template.replace("__CONFIG_JSON__", config_json)
    # Always use a unique key to avoid DuplicateWidgetID issues
    key_val = "wheel_" + str(uuid.uuid4())
    try:
        components.html(html, height=610, scrolling=False)
    except Exception as e:
        st.error(f"HTML komponens hiba: {type(e).__name__}: {e}")

if target_index is None:
    render_wheel_component(
        names=names,
        target_index=None,
        duration_s=duration,
        turns=turns,
        audio_enabled=audio_enabled,
        tick_sound=tick_sound,
        ding_sound=ding_sound,
        high_fps=high_fps
    )
else:
    render_wheel_component(
        names=names,
        target_index=target_index,
        duration_s=duration,
        turns=turns,
        audio_enabled=audio_enabled,
        tick_sound=tick_sound,
        ding_sound=ding_sound,
        high_fps=high_fps
    )

# Napló megjelenítés + export
st.divider()
st.subheader("Nyeremény napló")
log_df = pd.DataFrame(st.session_state["log_by_sheet"][chosen], columns=["Időpont","Munkalap","Nyertes"])
if log_df.empty:
    st.info("Még nincs bejegyzés.")
else:
    st.dataframe(log_df, use_container_width=True)
    csv = log_df.to_csv(index=False).encode("utf-8")
    st.download_button("Napló letöltése (CSV)", data=csv, file_name=f"nyertes_naplo_{chosen}.csv", mime="text/csv")
