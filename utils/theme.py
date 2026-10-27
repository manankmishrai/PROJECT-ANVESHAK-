"""Visual theme for the Evidence-Ladder Scrutiny Copilot.

Concept: an archivist's case file. Warm ledger paper, ink-black type,
a vermilion "rubber stamp" accent, and a five-rung ladder motif that
mirrors the Evidence-Ladder model (Rung 0 -> Rung 4).

Pure presentation: no behaviour changes. Fonts load from Google Fonts
and fall back to system serif/sans/mono if offline.
"""
import streamlit as st

# Rung colours climb from cold grey (unverifiable) to deep teal (verified at source).
RUNG_COLORS = ["#8A8577", "#C98A1B", "#5C7A3A", "#1F6F6B", "#0B4F52"]

THEME_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Instrument+Serif:ital@0;1&family=Bricolage+Grotesque:opsz,wght@12..96,300..800&family=Martian+Mono:wght@300..700&display=swap');

:root {
  --paper: #F1EADB;
  --paper-deep: #E7DEC9;
  --card: #FBF7EC;
  --ink: #17130F;
  --ink-soft: #5B5346;
  --rule: #CFC4AB;
  --stamp: #C8401A;
  --teal: #1F6F6B;
  --night: #0E1E1B;
  --night-2: #16302B;
  --f-display: 'Instrument Serif', 'Iowan Old Style', Georgia, serif;
  --f-body: 'Bricolage Grotesque', 'Segoe UI', system-ui, sans-serif;
  --f-mono: 'Martian Mono', ui-monospace, 'SF Mono', Consolas, monospace;
}

/* ---------- atmosphere: ledger paper ---------- */
.stApp {
  background:
    radial-gradient(1200px 500px at 85% -10%, rgba(200,64,26,.10), transparent 60%),
    radial-gradient(900px 500px at -10% 110%, rgba(31,111,107,.10), transparent 60%),
    var(--paper);
  color: var(--ink);
  font-family: var(--f-body);
}
.block-container { padding-top: 2.2rem; padding-bottom: 3rem; max-width: 1280px; }
header[data-testid="stHeader"] { background: transparent; }

/* ---------- type ---------- */
.stApp p, .stApp li, .stApp label, .stApp input, .stApp textarea,
.stApp button p, .stApp [data-testid="stCaptionContainer"] { font-family: var(--f-body); }
h1, h2, h3, h4 { font-family: var(--f-display) !important; font-weight: 400 !important; letter-spacing: -.01em; color: var(--ink); }
h1 { font-size: 3.1rem !important; line-height: 1.02; }
h2 { font-size: 2.1rem !important; }
h3 { font-size: 1.55rem !important; }
h4 { font-size: 1.25rem !important; font-style: italic; color: var(--ink-soft); }
h1::after { content: ""; display: block; width: 72px; height: 4px; margin-top: .55rem; background: var(--stamp); }
code, pre, kbd { font-family: var(--f-mono) !important; font-size: .82em !important; }
code { background: rgba(23,19,15,.07) !important; color: var(--ink) !important; border-radius: 3px; padding: .1em .4em; }
[data-testid="stCaptionContainer"] { color: var(--ink-soft); letter-spacing: .01em; }
hr { border-color: var(--rule) !important; margin: 1.8rem 0 !important; }
.stMainBlockContainer [data-testid="stVerticalBlock"] { gap: 1.1rem; }
h2, h3, h4 { margin-top: .6rem !important; margin-bottom: .4rem !important; }

/* ---------- sidebar: evidence room ---------- */
[data-testid="stSidebar"] {
  background:
    linear-gradient(180deg, rgba(255,255,255,.03), transparent 30%),
    repeating-linear-gradient(90deg, transparent 0 47px, rgba(255,255,255,.025) 47px 48px),
    var(--night);
  border-right: 3px solid var(--stamp);
}
[data-testid="stSidebar"] * { color: #E9E2D0 !important; }
[data-testid="stSidebar"] [data-testid="stNavSectionHeader"] { font-family: var(--f-mono); text-transform: uppercase; letter-spacing: .14em; font-size: .66rem; opacity: .6; margin-top: .6rem; }
[data-testid="stSidebar"] [data-testid="stSidebarNavLink"] { padding: .45rem .75rem; margin-bottom: 2px; gap: .6rem; }
/* never let text-font rules touch Streamlit's icon glyphs */
[data-testid="stIconMaterial"], .material-symbols-rounded, .material-icons {
  font-family: 'Material Symbols Rounded', 'Material Icons' !important;
  letter-spacing: normal !important; text-transform: none !important; font-feature-settings: 'liga' !important;
}
[data-testid="stSidebarNav"] a[aria-current="page"], [data-testid="stSidebar"] a[aria-current="page"] {
  background: var(--night-2) !important; box-shadow: inset 3px 0 0 var(--stamp); border-radius: 2px;
}
[data-testid="stSidebar"] .stButton button { background: transparent; border: 1px solid rgba(233,226,208,.4); }
[data-testid="stSidebar"] .stButton button:hover { background: var(--stamp); border-color: var(--stamp); }

/* ---------- inputs & buttons ---------- */
.stButton > button, .stFormSubmitButton > button, .stDownloadButton > button {
  font-family: var(--f-mono); font-size: .74rem; text-transform: uppercase; letter-spacing: .1em;
  border-radius: 2px; border: 1.5px solid var(--ink); background: var(--card); color: var(--ink);
  box-shadow: 3px 3px 0 var(--ink); transition: transform .12s ease, box-shadow .12s ease, background .12s ease;
}
.stButton > button:hover, .stFormSubmitButton > button:hover, .stDownloadButton > button:hover {
  transform: translate(2px, 2px); box-shadow: 1px 1px 0 var(--ink); background: var(--stamp); border-color: var(--ink); color: #fff;
}
.stButton > button[kind="primary"], .stFormSubmitButton > button[kind="primary"] { background: var(--stamp); color: #fff; }
.stTextInput input, .stTextArea textarea, .stSelectbox [data-baseweb="select"] > div, .stNumberInput input {
  background: var(--card) !important; border: 1.5px solid var(--rule) !important; border-radius: 2px !important;
}
.stTextInput input:focus, .stTextArea textarea:focus { border-color: var(--stamp) !important; box-shadow: 0 0 0 3px rgba(200,64,26,.18) !important; }
[data-testid="stForm"] { background: var(--card); border: 1.5px solid var(--ink); border-radius: 2px; box-shadow: 4px 4px 0 rgba(23,19,15,.85); padding: 1.6rem; margin-right: 6px; }

/* ---------- metrics: index-card tiles ---------- */
[data-testid="stMetric"] {
  background: var(--card); border: 1px solid var(--rule); border-top: 4px solid var(--ink);
  padding: .9rem 1rem; border-radius: 2px;
}
[data-testid="stMetricLabel"] p { font-family: var(--f-mono); text-transform: uppercase; letter-spacing: .1em; font-size: .66rem; color: var(--ink-soft); }
[data-testid="stMetricValue"] { font-family: var(--f-display); font-size: 2.6rem; line-height: 1.05; }

/* ---------- expanders, alerts, tabs, tables: explicitly override Streamlit theme defaults ---------- */
[data-testid="stExpander"],
[data-testid="stExpander"] details,
[data-testid="stExpander"] details > summary,
[data-testid="stExpander"] summary,
[data-testid="stExpander"] [data-testid="stExpanderDetails"] {
  background: var(--card) !important; color: var(--ink) !important;
}
[data-testid="stExpander"] { border: 1px solid var(--rule) !important; border-radius: 10px !important; overflow: hidden; }
[data-testid="stExpander"] summary { font-weight: 600 !important; padding: .75rem 1rem !important; }
[data-testid="stExpander"] summary:hover { background: var(--paper-deep) !important; }
[data-testid="stExpander"] p, [data-testid="stExpander"] span,
[data-testid="stExpander"] label, [data-testid="stExpander"] th,
[data-testid="stExpander"] td { color: var(--ink) !important; }
[data-testid="stAlert"] { border-radius: 10px; border: 1px solid var(--rule); border-left-width: 5px; }
.stTabs [data-baseweb="tab-list"] { gap: .35rem; border-bottom: 1px solid var(--rule); background: transparent !important; }
.stTabs [data-baseweb="tab"] { padding: .65rem 1.1rem; margin-right: 2px; border-radius: 9px 9px 0 0; font-family: var(--f-body); font-size: .9rem; color: var(--ink-soft) !important; background: transparent !important; }
.stTabs [data-baseweb="tab"][aria-selected="true"] { background: var(--night-2) !important; color: #F8F4E9 !important; }
.stTabs [data-baseweb="tab-highlight"] { background: var(--stamp) !important; }
[data-testid="stDataFrame"], [data-testid="stTable"] { border: 1px solid var(--rule); border-radius: 8px; overflow: hidden; background: var(--card) !important; }
[data-testid="stDataFrame"] iframe { color-scheme: light !important; }
/* Keep metrics and controls readable regardless of inherited Streamlit theme */
[data-testid="stMetricValue"], [data-testid="stMetricValue"] div { color: var(--ink) !important; }
[data-testid="stMetricLabel"], [data-testid="stMetricLabel"] p { color: var(--ink-soft) !important; }
.stApp input, .stApp textarea, .stApp [data-baseweb="select"] *, .stApp [data-baseweb="input"] *,
.stApp [data-testid="stNumberInput"] input, .stApp [data-testid="stTextInput"] input {
  color: var(--ink) !important; -webkit-text-fill-color: var(--ink) !important; caret-color: var(--stamp) !important;
}
.stApp input::placeholder, .stApp textarea::placeholder { color: #827868 !important; -webkit-text-fill-color: #827868 !important; opacity: 1 !important; }
.stApp [data-testid="stMarkdownContainer"] p, .stApp [data-testid="stMarkdownContainer"] li { color: inherit; }
.stApp [data-testid="stDataFrame"] *, .stApp [data-testid="stTable"] * { color-scheme: light; }

/* ---------- finding / evidence cards (used by pages via .evidence-card) ---------- */
.evidence-card {
  position: relative; border-radius: 2px; padding: .95rem 1.1rem .95rem 1.2rem; margin-bottom: .7rem;
  border: 1px solid var(--rule); border-left: 6px solid #8A8577; background: var(--card);
  box-shadow: 2px 3px 0 rgba(23,19,15,.08);
}
.evidence-card strong { font-family: var(--f-mono); font-size: .8rem; letter-spacing: .04em; }

/* ---------- login hero ---------- */
.ladder-hero { display: grid; grid-template-columns: 1.25fr 1fr; gap: 2.5rem; align-items: end; margin: .5rem 0 2rem; }
.ladder-hero .eyebrow { font-family: var(--f-mono); font-size: .7rem; letter-spacing: .18em; text-transform: uppercase; color: var(--stamp); }
.project-mark { display: flex; flex-direction: column; align-items: flex-start; gap: .04rem; margin: .15rem 0 1rem; width: fit-content; position: relative; }
.project-kicker { font-family: var(--f-mono); color: var(--night-2); font-size: clamp(1rem, 1.6vw, 1.35rem); font-weight: 800; letter-spacing: .34em; padding-left: .28rem; }
.project-name { font-family: var(--f-display); font-size: clamp(4.5rem, 8.5vw, 7.4rem); line-height: .92; font-weight: 700; letter-spacing: -.035em; color: var(--stamp); text-shadow: 1px 1px 0 #F9F3E7, 2px 3px 0 rgba(36,69,54,.15); }
.project-name::after { content: ""; display: block; width: 68%; height: 4px; margin-top: .45rem; background: linear-gradient(90deg, var(--stamp), #D99A70, var(--night-2)); border-radius: 3px; }
.team-credit { display: inline-flex; align-items: center; gap: .55rem; margin: 0 0 .85rem; padding: .52rem .82rem; border: 1px solid #B85F39; border-left: 5px solid #C8401A; border-radius: 5px; background: #244536; color: #FBF7EC !important; box-shadow: 3px 3px 0 rgba(184,95,57,.22); font-family: var(--f-mono); font-size: .76rem; font-weight: 800; letter-spacing: .12em; text-transform: uppercase; }
.team-credit .team-dot { display: inline-block; width: 7px; height: 7px; border-radius: 50%; background: #E6A17D; box-shadow: 0 0 0 3px rgba(230,161,125,.15); }
.ladder-hero .title { font-family: var(--f-display); font-size: clamp(2.6rem, 6vw, 4.6rem); line-height: .96; margin: .4rem 0 .8rem; }
.ladder-hero .title em { color: var(--stamp); }
.ladder-hero .sub { color: var(--ink-soft); max-width: 46ch; line-height: 1.5; }
.rungs { display: flex; flex-direction: column; gap: 7px; }
.rung { display: flex; align-items: center; gap: .8rem; height: 38px; padding: 0 .9rem; color: #fff;
  font-family: var(--f-mono); font-size: .68rem; letter-spacing: .06em; text-transform: uppercase;
  transform-origin: left center; animation: rungIn .7s cubic-bezier(.2,.8,.2,1) both; }
.rung b { font-weight: 700; opacity: .75; }
@keyframes rungIn { from { opacity: 0; transform: scaleX(.15) translateX(-12px); } to { opacity: 1; transform: none; } }
@keyframes riseIn { from { opacity: 0; transform: translateY(14px); } to { opacity: 1; transform: none; } }

/* ---------- page-change loading: rung-coloured progress bar ---------- */
[data-testid="stStatusWidget"] { display: none !important; }   /* replace Streamlit's default running man */
.stApp::before {
  content: ""; position: fixed; top: 0; left: 0; right: 0; height: 4px; z-index: 999999; pointer-events: none;
  background: linear-gradient(90deg, #8A8577, #C98A1B, #5C7A3A, #1F6F6B, #0B4F52, #C8401A, #8A8577);
  background-size: 200% 100%; opacity: 0; transition: opacity .2s ease .12s;   /* short delay: no flash on instant reruns */
  animation: ladderBar 1.1s linear infinite;
}
.stApp::after {
  content: "Climbing the ladder\2026"; position: fixed; top: 12px; right: 18px; z-index: 999999; pointer-events: none;
  font-family: var(--f-mono); font-size: .64rem; letter-spacing: .16em; text-transform: uppercase;
  color: var(--paper); background: var(--ink); padding: .4rem .7rem; border-left: 4px solid var(--stamp);
  box-shadow: 3px 3px 0 var(--stamp); opacity: 0; transform: translateY(-6px);
  transition: opacity .2s ease .12s, transform .2s ease .12s;
}
.stApp[data-teststate="running"]::before, .stApp:has([data-testid="stStatusWidget"])::before { opacity: 1; }
.stApp[data-teststate="running"]::after,  .stApp:has([data-testid="stStatusWidget"])::after  { opacity: 1; transform: none; animation: pulseLabel 1.2s ease-in-out infinite; }
/* old page content dims and softens while the next one loads */
[data-stale="true"] { opacity: .35 !important; filter: saturate(.6); transition: opacity .25s ease; }
@keyframes ladderBar { from { background-position: 0 0; } to { background-position: -200% 0; } }
@keyframes pulseLabel { 0%, 100% { box-shadow: 3px 3px 0 var(--stamp); } 50% { box-shadow: 3px 3px 0 var(--teal); } }

/* staggered page-load reveal */
.stMainBlockContainer > [data-testid="stVerticalBlock"] > div:nth-child(-n+8) { animation: riseIn .55s cubic-bezier(.2,.8,.2,1) both; }
.stMainBlockContainer > [data-testid="stVerticalBlock"] > div:nth-child(2) { animation-delay: .05s; }
.stMainBlockContainer > [data-testid="stVerticalBlock"] > div:nth-child(3) { animation-delay: .10s; }
.stMainBlockContainer > [data-testid="stVerticalBlock"] > div:nth-child(4) { animation-delay: .15s; }
.stMainBlockContainer > [data-testid="stVerticalBlock"] > div:nth-child(5) { animation-delay: .20s; }
.stMainBlockContainer > [data-testid="stVerticalBlock"] > div:nth-child(6) { animation-delay: .25s; }
.stMainBlockContainer > [data-testid="stVerticalBlock"] > div:nth-child(7) { animation-delay: .30s; }
.stMainBlockContainer > [data-testid="stVerticalBlock"] > div:nth-child(8) { animation-delay: .35s; }

@media (max-width: 800px) { .ladder-hero { grid-template-columns: 1fr; } }
@media (prefers-reduced-motion: reduce) { * { animation: none !important; transition: none !important; } }
</style>
"""

RUNG_NAMES = [
    "Unverifiable",
    "Anomaly flagged",
    "Internally consistent",
    "Cryptographically intact",
    "Verified at source",
]


def inject_theme() -> None:
    st.markdown(THEME_CSS, unsafe_allow_html=True)


def ladder_hero_html(app_name: str, tagline: str) -> str:
    # Top rung (4) first so the ladder reads as climbing upward.
    rungs = []
    for i in reversed(range(5)):
        width = 52 + i * 12
        rungs.append(
            f'<div class="rung" style="background:{RUNG_COLORS[i]};width:{width}%;animation-delay:{(4 - i) * 0.12 + 0.2:.2f}s">'
            f"<b>R{i}</b>{RUNG_NAMES[i]}</div>"
        )
    return (
        '<div class="ladder-hero"><div>'
        '<div class="project-mark"><span class="project-kicker">PROJECT</span>'
        '<span class="project-name">ANVESHAK!</span></div>'
        f'<div class="sub">{tagline}</div></div>'
        f'<div class="rungs">{"".join(rungs)}</div></div>'
    )
